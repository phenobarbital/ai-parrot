"""Tests for ``DevLoopToolkit`` — the dev loop as agent tools.

The runner and flow are stubbed: what is under test is the toolkit's own
behaviour (tool generation, brief assembly, the deferred autonomy decision,
gate handling), not the eight-node flow it delegates to.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from parrot.flows.dev_loop.toolkit import DevLoopToolkit


class _Gate:
    """A pending approval gate, as the session host exposes it."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.status = "pending"
        self.prompt = f"approve {kind}?"


class _Host:
    """Minimal stand-in for ``SessionHost``."""

    def __init__(self, gates: Dict[str, _Gate]) -> None:
        self.state = SimpleNamespace(phase="awaiting_gate", gates=gates)


class _Runner:
    """Records what the toolkit asked of the runner."""

    def __init__(self, gates: Dict[str, _Gate] | None = None) -> None:
        self.gates = gates or {}
        self.host = _Host(self.gates)
        self.resolved: List[tuple] = []
        self.cancelled: List[str] = []
        self.briefs: List[Any] = []
        self._release = asyncio.Event()

    async def run(self, brief: Any, run_id: str = "", **_kw: Any) -> Any:
        self.briefs.append(brief)
        await self._release.wait()
        return SimpleNamespace(status="completed", responses={"qa": "ok"})

    def finish(self) -> None:
        self._release.set()

    def get_host(self, run_id: str) -> Any:
        return self.host

    async def resolve_gate(
        self, run_id: str, gate_id: str, resolution: str, resolved_by: str, **kw: Any
    ) -> Any:
        self.resolved.append((run_id, gate_id, resolution, resolved_by))
        self.gates[gate_id].status = resolution
        return SimpleNamespace(sequence=len(self.resolved))

    async def cancel_run(self, run_id: str, requested_by: str) -> Any:
        self.cancelled.append(run_id)
        return SimpleNamespace(sequence=0)


def _toolkit(runner: _Runner, **kwargs: Any) -> DevLoopToolkit:
    """A toolkit wired to a stub runner, bypassing flow construction."""
    toolkit = DevLoopToolkit(gate_poll_seconds=0.01, **kwargs)
    toolkit._runner_for = lambda mode: runner  # type: ignore[method-assign]
    return toolkit


_FULL_BRIEF = {
    "summary": "500 on GET /api/v1/xyz",
    "description": "always",
    "repo": "navigator-api",
    "acceptance_commands": ["pytest tests/test_xyz.py"],
}


class TestToolGeneration:
    def test_every_public_method_becomes_a_prefixed_tool(self):
        names = {tool.name for tool in DevLoopToolkit().get_tools()}
        assert names == {
            "devloop_start_dev_loop",
            "devloop_dev_loop_status",
            "devloop_dev_loop_runs",
            "devloop_dev_loop_approve",
            "devloop_dev_loop_cancel",
        }

    def test_start_schema_exposes_the_report_fields(self):
        (tool,) = [
            t for t in DevLoopToolkit().get_tools()
            if t.name.endswith("start_dev_loop")
        ]
        properties = tool.args_schema.model_json_schema()["properties"]
        assert {"summary", "repo", "error_text", "approval_mode"} <= set(properties)

    def test_gate_flags_in_flow_kwargs_are_rejected(self):
        """They are derived per run, so accepting them would be a silent lie."""
        with pytest.raises(ValueError, match="must not set the gate flags"):
            DevLoopToolkit(flow_kwargs={"require_deployment_approval": True})


class TestStart:
    @pytest.mark.asyncio
    async def test_returns_immediately_with_a_run_id(self):
        """A run takes minutes; the tool must not wait for it."""
        runner = _Runner()
        toolkit = _toolkit(runner)
        out = await asyncio.wait_for(
            toolkit.start_dev_loop(**_FULL_BRIEF), timeout=1
        )
        assert out["run_id"].startswith("run-")
        assert out["status"] == "running"
        runner.finish()

    @pytest.mark.asyncio
    async def test_error_text_becomes_an_inline_log_source(self):
        runner = _Runner()
        toolkit = _toolkit(runner)
        await toolkit.start_dev_loop(**_FULL_BRIEF, error_text="KeyError: 'x'")
        await asyncio.sleep(0)
        brief = runner.briefs[0]
        assert [s.kind for s in brief.log_sources] == ["inline"]
        assert "KeyError" in brief.log_sources[0].locator
        runner.finish()

    @pytest.mark.asyncio
    async def test_acceptance_commands_become_shell_criteria(self):
        runner = _Runner()
        toolkit = _toolkit(runner)
        await toolkit.start_dev_loop(**_FULL_BRIEF)
        await asyncio.sleep(0)
        criteria = runner.briefs[0].acceptance_criteria
        assert [c.kind for c in criteria] == ["shell"]
        assert criteria[0].command == "pytest tests/test_xyz.py"
        runner.finish()

    @pytest.mark.asyncio
    async def test_starts_locked_down_by_default(self):
        """Autonomy is decided after the plan, so both gates start on."""
        runner = _Runner()
        toolkit = _toolkit(runner)
        out = await toolkit.start_dev_loop(**_FULL_BRIEF)
        assert out["approval_mode"] == "every_step"
        assert sorted(out["gates"]) == ["deployment", "plan"]
        runner.finish()

    @pytest.mark.asyncio
    async def test_an_underspecified_report_says_what_is_missing(self):
        toolkit = _toolkit(_Runner())
        with pytest.raises(ValueError) as excinfo:
            await toolkit.start_dev_loop(summary="the api is broken")
        message = str(excinfo.value)
        assert "affected_component" in message and "repo" in message
        assert "acceptance_criteria" in message
        assert "No brief enricher is configured" in message

    @pytest.mark.asyncio
    async def test_the_enricher_fills_what_the_report_omits(self):
        class _Enricher:
            async def enrich(self, draft):
                draft["affected_component"] = "navigator-api"
                draft["acceptance_criteria"] = [
                    {"kind": "shell", "name": "suite", "command": "pytest"}
                ]
                return draft

        runner = _Runner()
        toolkit = _toolkit(runner, brief_enricher=_Enricher())
        out = await toolkit.start_dev_loop(summary="500 on /api/v1/xyz")
        assert out["brief"]["affected_component"] == "navigator-api"
        runner.finish()

    @pytest.mark.asyncio
    async def test_a_failing_enricher_does_not_block_a_complete_report(self):
        """Enrichment is advisory; a full brief must still start."""
        class _Broken:
            async def enrich(self, draft):
                raise RuntimeError("graph down")

        runner = _Runner()
        toolkit = _toolkit(runner, brief_enricher=_Broken())
        out = await toolkit.start_dev_loop(**_FULL_BRIEF)
        assert out["status"] == "running"
        runner.finish()

    @pytest.mark.asyncio
    async def test_invalid_approval_mode_is_rejected(self):
        toolkit = _toolkit(_Runner())
        with pytest.raises(ValueError, match="approval_mode must be one of"):
            await toolkit.start_dev_loop(**_FULL_BRIEF, approval_mode="whenever")


class TestApprovalAndAutonomy:
    @pytest.mark.asyncio
    async def test_status_reports_pending_gates(self):
        runner = _Runner({"g1": _Gate("plan_approval")})
        toolkit = _toolkit(runner)
        out = await toolkit.start_dev_loop(**_FULL_BRIEF)
        status = await toolkit.dev_loop_status(out["run_id"])
        assert [g["gate_id"] for g in status["pending_gates"]] == ["g1"]
        assert status["pending_gates"][0]["kind"] == "plan_approval"
        runner.finish()

    @pytest.mark.asyncio
    async def test_approving_with_ask_keeps_later_gates_manual(self):
        runner = _Runner({"g1": _Gate("plan_approval")})
        toolkit = _toolkit(runner)
        out = await toolkit.start_dev_loop(**_FULL_BRIEF)
        run_id = out["run_id"]
        await toolkit.dev_loop_approve(run_id, "g1", then="ask")
        # A later gate appears and must stay pending.
        runner.gates["g2"] = _Gate("deployment_approval")
        await asyncio.sleep(0.05)
        assert runner.gates["g2"].status == "pending"
        assert (await toolkit.dev_loop_status(run_id))["autonomous"] is False
        runner.finish()

    @pytest.mark.asyncio
    async def test_approving_with_autonomous_auto_approves_later_gates(self):
        runner = _Runner({"g1": _Gate("plan_approval")})
        toolkit = _toolkit(runner)
        out = await toolkit.start_dev_loop(**_FULL_BRIEF)
        run_id = out["run_id"]
        await toolkit.dev_loop_approve(run_id, "g1", then="autonomous")
        runner.gates["g2"] = _Gate("deployment_approval")
        for _ in range(100):
            await asyncio.sleep(0.01)
            if runner.gates["g2"].status == "approved":
                break
        assert runner.gates["g2"].status == "approved"
        status = await toolkit.dev_loop_status(run_id)
        assert status["autonomous"] is True
        assert "g2" in status["auto_approved"]
        runner.finish()

    @pytest.mark.asyncio
    async def test_rejecting_does_not_grant_autonomy(self):
        """`then` must not be honoured on a rejection."""
        runner = _Runner({"g1": _Gate("plan_approval")})
        toolkit = _toolkit(runner)
        out = await toolkit.start_dev_loop(**_FULL_BRIEF)
        await toolkit.dev_loop_approve(
            out["run_id"], "g1", resolution="rejected", then="autonomous"
        )
        assert (await toolkit.dev_loop_status(out["run_id"]))["autonomous"] is False
        runner.finish()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "kwargs,match",
        [
            ({"resolution": "maybe"}, "resolution must be"),
            ({"then": "later"}, "then must be"),
        ],
    )
    async def test_invalid_approval_arguments(self, kwargs, match):
        runner = _Runner({"g1": _Gate("plan_approval")})
        toolkit = _toolkit(runner)
        out = await toolkit.start_dev_loop(**_FULL_BRIEF)
        with pytest.raises(ValueError, match=match):
            await toolkit.dev_loop_approve(out["run_id"], "g1", **kwargs)
        runner.finish()

    @pytest.mark.asyncio
    async def test_unknown_run_lists_the_known_ones(self):
        toolkit = _toolkit(_Runner())
        with pytest.raises(KeyError, match="unknown run_id"):
            await toolkit.dev_loop_status("run-nope")


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_runs_lists_what_was_started(self):
        runner = _Runner()
        toolkit = _toolkit(runner)
        await toolkit.start_dev_loop(**_FULL_BRIEF)
        listing = await toolkit.dev_loop_runs()
        assert len(listing["runs"]) == 1
        assert listing["runs"][0]["kind"] == "bug"
        runner.finish()

    @pytest.mark.asyncio
    async def test_completion_is_recorded(self):
        runner = _Runner()
        toolkit = _toolkit(runner)
        out = await toolkit.start_dev_loop(**_FULL_BRIEF)
        runner.finish()
        await asyncio.sleep(0.05)
        status = await toolkit.dev_loop_status(out["run_id"])
        assert status["status"] == "completed"
        assert status["nodes"] == {"qa": "ok"}

    @pytest.mark.asyncio
    async def test_a_failing_run_is_recorded_not_raised(self):
        """Nothing awaits the run task, so a failure must land on the record."""
        class _Boom(_Runner):
            async def run(self, brief, run_id="", **_kw):
                raise RuntimeError("flow exploded")

        runner = _Boom()
        toolkit = _toolkit(runner)
        out = await toolkit.start_dev_loop(**_FULL_BRIEF)
        await asyncio.sleep(0.05)
        status = await toolkit.dev_loop_status(out["run_id"])
        assert status["status"] == "failed"
        assert "flow exploded" in status["error"]

    @pytest.mark.asyncio
    async def test_cancel_marks_the_run(self):
        runner = _Runner()
        toolkit = _toolkit(runner)
        out = await toolkit.start_dev_loop(**_FULL_BRIEF)
        result = await toolkit.dev_loop_cancel(out["run_id"])
        assert result["cancelled"] is True
        assert runner.cancelled == [out["run_id"]]
        runner.finish()

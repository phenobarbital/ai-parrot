"""Unit tests for the IdeationNode <-> ComplementaryResearchCoordinator seam
(FEAT-482 Module 5).

Uses the same scripted-dispatcher pattern as ``test_ideation_node.py``
(no Claude SDK, no Redis) plus a scripted fake coordinator.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from parrot import conf
from parrot.flows.dev_flow.models import DevRequestBrief, IdeationOutput
from parrot.flows.dev_flow.nodes.ideation import IdeationNode
from parrot.flows.dev_flow.research_partner import (
    ComplementaryFindings,
    ResearchFindings,
)
from parrot.flows.dev_loop.models import FeatureBrief
from parrot.flows.dev_loop.session_state import SessionHost

RUN_ID = "run-ideation-partner01"

Q1 = "Which store backs the telemetry?"


class ScriptedDispatcher:
    """Returns a pre-scripted IdeationOutput per dispatch, recording payloads."""

    def __init__(self, outputs: list[IdeationOutput]) -> None:
        self._outputs = list(outputs)
        self.calls: list[dict[str, Any]] = []

    async def dispatch(
        self,
        *,
        brief: Any,
        profile: Any,
        output_model: Any,
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Any = None,
    ) -> Any:
        self.calls.append({"brief": brief})
        if not self._outputs:
            raise AssertionError("ScriptedDispatcher exhausted — unexpected dispatch")
        return self._outputs.pop(0)


class _FakeCoordinator:
    """Stand-in for ComplementaryResearchCoordinator — never raises."""

    def __init__(self, result: ComplementaryFindings | None = None):
        self._result = result
        self.calls: list[dict[str, Any]] = []

    async def research(self, **kwargs: Any) -> ComplementaryFindings | None:
        self.calls.append(kwargs)
        return self._result


def _brief(**extra) -> DevRequestBrief:
    return DevRequestBrief(
        kind="new_feature",
        title="compression budget telemetry",
        description="Add per-tool telemetry to the compression budget.",
        **extra,
    )


def _output(**over) -> IdeationOutput:
    base = {
        "document_path": "sdd/proposals/telemetry.brainstorm.md",
        "document_kind": "brainstorm",
        "slug": "telemetry",
        "committed": True,
    }
    base.update(over)
    return IdeationOutput(**base)


def _findings(rendered: str = "# findings", document_path: str = "sdd/proposals/telemetry.research.md"):
    return ComplementaryFindings(
        backend="gpt",
        model="gpt-5.6-sol",
        findings=ResearchFindings(summary="A relevant precedent exists."),
        document_path=document_path,
        rendered=rendered,
        duration_ms=42.0,
    )


@pytest.fixture
def doc(tmp_path, monkeypatch):
    proposals = tmp_path / "sdd" / "proposals"
    proposals.mkdir(parents=True)
    path = proposals / "telemetry.brainstorm.md"
    path.write_text("# Brainstorm", encoding="utf-8")
    monkeypatch.setattr(conf, "PROJECT_ROOT", tmp_path, raising=False)
    return path


async def _answer_gate(host: SessionHost, answers: dict[str, str]) -> None:
    await asyncio.sleep(0.01)
    gate_id = next(g for g, gate in host.state.gates.items() if gate.status == "pending")
    host.resolve_gate(gate_id, "approved", resolved_by="alice", answers=answers)


class TestIdeationPartnerSeam:
    async def test_passes_partner_findings_to_first_dispatch(self, doc):
        """_IdeationBrief.partner_findings populated on round 1."""
        dispatcher = ScriptedDispatcher([_output()])
        findings = _findings(rendered="# The partner found X")
        coordinator = _FakeCoordinator(result=findings)
        node = IdeationNode(dispatcher=dispatcher, coordinator=coordinator)

        result = await node.execute({"run_id": RUN_ID, "dev_brief": _brief()})

        assert len(dispatcher.calls) == 1
        sent_brief = dispatcher.calls[0]["brief"]
        assert sent_brief.partner_findings == "# The partner found X"
        assert sent_brief.partner_findings_path == "sdd/proposals/telemetry.research.md"
        assert isinstance(result, FeatureBrief)
        # The coordinator saw the slugified title, project-root cwd, round-1 brief.
        assert len(coordinator.calls) == 1
        assert coordinator.calls[0]["slug"] == "compression-budget-telemetry"

    async def test_resume_round_skips_partner(self, doc):
        """Round 2+ does not re-run the partner and passes empty partner fields."""
        dispatcher = ScriptedDispatcher(
            [_output(open_questions=[Q1], committed=True), _output()]
        )
        coordinator = _FakeCoordinator(result=_findings())
        node = IdeationNode(dispatcher=dispatcher, coordinator=coordinator)
        host = SessionHost(RUN_ID)
        ctx = {"run_id": RUN_ID, "dev_brief": _brief(), "session_host": host}

        resolver = asyncio.ensure_future(_answer_gate(host, {Q1: "pgvector"}))
        await asyncio.wait_for(node.execute(ctx), timeout=5)
        await resolver

        # The coordinator was called exactly once (round 1), never again.
        assert len(coordinator.calls) == 1
        # Round 1 carried the findings; round 2 (resume) carries none.
        assert dispatcher.calls[0]["brief"].partner_findings != ""
        assert dispatcher.calls[1]["brief"].partner_findings == ""
        assert dispatcher.calls[1]["brief"].partner_findings_path == ""

    async def test_unchanged_when_coordinator_none(self, doc):
        """GUARD: dispatch payload's partner fields are empty, and every other
        field is unaffected, when no coordinator is injected (default)."""
        dispatcher = ScriptedDispatcher([_output()])
        node = IdeationNode(dispatcher=dispatcher)  # no coordinator kwarg at all

        await node.execute({"run_id": RUN_ID, "dev_brief": _brief()})

        sent_brief = dispatcher.calls[0]["brief"]
        assert sent_brief.partner_findings == ""
        assert sent_brief.partner_findings_path == ""
        # Every pre-existing field is exactly what pre-feature behavior produced.
        assert sent_brief.mode == "brainstorm"
        assert sent_brief.title == "compression budget telemetry"
        assert sent_brief.description == "Add per-tool telemetry to the compression budget."
        assert sent_brief.context == ""
        assert sent_brief.answers == {}
        assert sent_brief.document_path == ""
        assert sent_brief.round == 1

    async def test_degraded_partner_does_not_fail_run(self, doc):
        """Coordinator returns None => run completes single-agent."""
        dispatcher = ScriptedDispatcher([_output()])
        coordinator = _FakeCoordinator(result=None)
        node = IdeationNode(dispatcher=dispatcher, coordinator=coordinator)

        result = await node.execute({"run_id": RUN_ID, "dev_brief": _brief()})

        assert isinstance(result, FeatureBrief)
        sent_brief = dispatcher.calls[0]["brief"]
        assert sent_brief.partner_findings == ""
        assert sent_brief.partner_findings_path == ""

    async def test_hitl_loop_bounds_unchanged(self, doc, monkeypatch):
        """max_rounds and fail-closed gate expiry behave as before, with a
        coordinator wired in."""
        monkeypatch.setattr(conf, "DEV_FLOW_IDEATION_MAX_ROUNDS", 2, raising=False)
        dispatcher = ScriptedDispatcher([_output(open_questions=[Q1]) for _ in range(3)])
        coordinator = _FakeCoordinator(result=_findings())
        node = IdeationNode(dispatcher=dispatcher, coordinator=coordinator)
        host = SessionHost(RUN_ID)
        ctx = {"run_id": RUN_ID, "dev_brief": _brief(), "session_host": host}

        async def _approve_every_gate():
            for _ in range(2):
                await asyncio.sleep(0.01)
                gate_id = next(
                    g for g, gate in host.state.gates.items() if gate.status == "pending"
                )
                host.resolve_gate(
                    gate_id, "approved", resolved_by="alice", answers={Q1: "an answer"}
                )

        resolver = asyncio.ensure_future(_approve_every_gate())
        await asyncio.wait_for(node.execute(ctx), timeout=5)
        await resolver

        # 1 initial + 2 max_rounds re-dispatches = 3 total dispatch calls.
        assert len(dispatcher.calls) == 3
        # The coordinator still only ran once, on round 1.
        assert len(coordinator.calls) == 1

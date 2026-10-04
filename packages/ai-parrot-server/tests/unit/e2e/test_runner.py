"""Focused runner contract tests (TASK-3533)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.e2e.models import E2EPlan, ProcessIdentity, RunState, ScenarioSpec, SourceIdentity, TargetConfig
from parrot.e2e import runner


def _plan(*scenarios: ScenarioSpec) -> E2EPlan:
    """Create a minimal valid plan for pure runner decision tests."""
    return E2EPlan(
        feature_id="FEAT-581",
        spec_path="sdd/specs/agentic-e2e-testing.spec.md",
        policy="required",
        scenarios=list(scenarios),
    )


def _scenario(**changes: object) -> ScenarioSpec:
    """Create one valid deterministic scenario with simple override support."""
    values: dict[str, object] = {
        "id": "scenario-a",
        "tier": "deterministic",
        "required": True,
        "node_ids": ["tests/e2e/test_runner.py::test_case"],
    }
    values.update(changes)
    return ScenarioSpec(**values)


def test_required_missing_or_blocked_coverage_is_blocked() -> None:
    """Required nodes that never execute must map to the documented blocked exit."""
    scenario = _scenario()
    status, exit_code, gate_satisfied = runner._verdict_status(_plan(scenario), [], {}, True, None)

    assert (status, exit_code, gate_satisfied) == ("BLOCKED", 3, False)


def test_source_mutation_overrides_an_apparent_pass() -> None:
    """A source change during execution is evidence-invalid, never a pass."""
    scenario = _scenario()
    passed = runner._results_for_nodes(scenario, "passed", "")

    status, exit_code, gate_satisfied = runner._verdict_status(_plan(scenario), passed, {}, False, None)

    assert (status, exit_code, gate_satisfied) == ("FAIL", 4, False)


def test_live_lane_requires_opt_in_and_provider_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No paid/live lane starts from ambient credentials or flag alone."""
    monkeypatch.delenv("PARROT_TEST_REAL_LLM", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert runner._live_enabled() is False

    monkeypatch.setenv("PARROT_TEST_REAL_LLM", "1")
    assert runner._live_enabled() is False

    monkeypatch.setenv("GOOGLE_API_KEY", "configured")
    assert runner._live_enabled() is True


def test_unmet_prerequisite_is_recorded_as_blocked() -> None:
    """Coverage is retained as BLOCKED instead of silently dropping a scenario."""
    scenario = _scenario(prerequisites=["setup"])

    assert runner._scenario_block_reason(scenario, []) == "prerequisite_not_passed:setup"
    blocked = runner._results_for_nodes(scenario, "blocked", "prerequisite_not_passed:setup")
    assert blocked[0].outcome == "blocked"


def test_atomic_writer_creates_private_evidence_file(tmp_path: Path) -> None:
    """Evidence writes are atomically replaced and restricted to the owner."""
    evidence = tmp_path / "run" / "e2e-verdict.json"

    runner._write_json(evidence, {"run_id": "run-1"})

    assert evidence.read_text(encoding="utf-8") == '{"run_id":"run-1"}'
    assert evidence.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_run_plan_executes_declared_nodes_and_cleans_targets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The orchestration boundary starts only selected targets and records cleanup."""
    scenario = _scenario(target_ids=["target-a"])
    plan = E2EPlan(
        feature_id="FEAT-581",
        spec_path="sdd/specs/agentic-e2e-testing.spec.md",
        policy="required",
        targets={"target-a": TargetConfig(kind="mcp-toolkit")},
        scenarios=[scenario],
    )
    identity = SourceIdentity(
        commit="a" * 40,
        manifest_sha256="a" * 64,
        spec_sha256="b" * 64,
        plan_sha256="c" * 64,
        environment_sha256="d" * 64,
        worktree=str(tmp_path.resolve()),
    )
    stopped: list[str] = []

    class FakeSupervisor:
        """Minimal lifecycle fake with observable start/stop calls."""

        def __init__(self, **_kwargs: object) -> None:
            self._runs: dict[str, object] = {}

        async def start(self, target_id: str, _config: TargetConfig) -> RunState:
            run_id = f"run-{target_id}"
            self._runs[run_id] = object()
            process = ProcessIdentity(pid=1, pgid=1, create_time=identity_capture_time(), boot_id="boot", owned=True)
            return RunState(
                feature_id="FEAT-581",
                run_id=run_id,
                worktree=str(tmp_path.resolve()),
                owner_id="owner-1",
                controller_identity=process,
                supervisor_identity=process,
                process_identity=process,
                target_id=target_id,
                status="ready",
                control_socket="/tmp/control",
                started_at=identity_capture_time(),
                deadline=identity_capture_time(),
                log_path="/tmp/log",
            )

        async def stop(self, run_id: str) -> RunState:
            stopped.append(run_id)
            self._runs.pop(run_id, None)
            process = ProcessIdentity(pid=1, pgid=1, create_time=identity_capture_time(), boot_id="boot", owned=True)
            return RunState(
                feature_id="FEAT-581",
                run_id=run_id,
                worktree=str(tmp_path.resolve()),
                owner_id="owner-1",
                controller_identity=process,
                supervisor_identity=process,
                process_identity=process,
                target_id="target-a",
                status="stopped",
                control_socket="/tmp/control",
                started_at=identity_capture_time(),
                deadline=identity_capture_time(),
                log_path="/tmp/log",
                cleanup_complete=True,
            )

    monkeypatch.setattr(runner, "load_plan", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(runner, "capture_identity", lambda *_args, **_kwargs: _identity_async(identity))
    monkeypatch.setattr(runner, "E2ESupervisor", FakeSupervisor)
    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", lambda *_args, **_kwargs: _process_async())
    monkeypatch.setattr(
        runner,
        "_load_bridge",
        lambda _path: {
            "collected_node_ids": scenario.node_ids,
            "exit_status": 0,
            "results": [
                {
                    "node_id": scenario.node_ids[0],
                    "outcome": "passed",
                    "setup_outcome": "passed",
                    "call_outcome": "passed",
                    "teardown_outcome": "passed",
                    "duration_s": 0.1,
                }
            ],
        },
    )
    monkeypatch.setattr(runner, "_sha256", lambda _path: "e" * 64)

    verdict = await runner.run_plan(tmp_path / "e2e-plan.md", worktree=tmp_path, owner_id="owner-1")

    assert verdict.status == "PASS"
    assert verdict.selected_node_ids == scenario.node_ids
    assert verdict.cleanup_results == {"run-target-a": True}
    assert stopped == ["run-target-a"]
    assert (tmp_path / "sdd/state/FEAT-581/e2e/latest.json").is_file()


async def _identity_async(identity: SourceIdentity) -> SourceIdentity:
    """Return a stable identity from an async collaborator fake."""
    return identity


async def _process_async() -> object:
    """Return a process-shaped fake for the runner subprocess seam."""

    class Process:
        """A completed child process."""

        async def wait(self) -> None:
            return None

    return Process()


def identity_capture_time():
    """Return a timezone-aware timestamp for synthetic process state."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)

"""Engine-bound validation capability and runner binaries on the attempt profile (FEAT-709, TASK-4534)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from parrot.flows.dev_loop.models import LLMCodeDispatchProfile
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine, _EngineValidationCapability
from parrot.flows.dev_loop.test_scope.datatypes import ValidationVerdict

from .test_engine_dispatch import _roster, fake_builder_factory
from .test_engine_validation_gate import EXECUTION_ID, FakeSupervisor, _engine, _run_one


def _bare_engine() -> SddCoderEngine:
    engine = SddCoderEngine.__new__(SddCoderEngine)
    import logging

    engine.logger = logging.getLogger("test")
    return engine


def test_profile_allows_registry_binaries(tmp_path: Path) -> None:
    profile = LLMCodeDispatchProfile(allowed_commands=["git"])
    out = _bare_engine()._profile_with_runner_binaries(profile, str(tmp_path))
    assert {"git", "pytest", "pnpm", "cargo"} <= set(out.allowed_commands)
    assert out.allowed_commands.count("git") == 1


async def test_capability_runs_task_tier_and_returns_json() -> None:
    calls: dict = {}

    class _Engine:
        roster = SimpleNamespace(runners=SimpleNamespace(gate_overall_timeout_s=30))

        async def run_validation(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(handle="h1")

        _validation_supervisor = SimpleNamespace()

    async def _wait(execution_id, handle, timeout_s):
        calls["wait"] = (execution_id, handle)
        return ValidationVerdict(schema=1, status="passed", tier="task", runners=(), failures=())

    _Engine._validation_supervisor.wait_verdict = _wait
    ctx = SimpleNamespace(feature="demo", worktree="/feature")
    cap = _EngineValidationCapability(_Engine(), ctx, "TASK-1", path="/attempt", attempt_uid="uid", execution_id="e1")
    result = await cap.run()
    assert cap.task_id == "TASK-1"
    assert calls["tier"] == "task" and calls["task_ids"] == ["TASK-1"] and calls["attempt_uid"] == "uid"
    assert calls["wait"] == ("e1", "h1")
    assert result["status"] == "passed" and result["tier"] == "task"


async def test_attempt_binds_capability_then_clears(git_sandbox_feature) -> None:
    worktree, _fb, base_path, _ix = git_sandbox_feature
    bound: list = []
    inner = fake_builder_factory({})

    def _builder(spec, **kwargs):
        dispatcher, profile = inner(spec, **kwargs)
        dispatcher.set_validation_runner = lambda cap: bound.append(cap)
        return dispatcher, profile

    engine = _engine(base_path, _builder, FakeSupervisor(["passed"]), roster=_roster(("a", "nova")))
    task = await _run_one(engine, worktree)
    assert task.outcome == "merged", task.diagnostics
    assert isinstance(bound[0], _EngineValidationCapability) and bound[0].task_id == "TASK-0001"
    assert bound[-1] is None
    assert EXECUTION_ID  # imported fixture constant keeps the shared execution id explicit

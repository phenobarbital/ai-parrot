"""Task-tier and language-agnostic validation supervisor tests for FEAT-709."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

from parrot.flows.dev_loop.sdd_coder import background as background_module
from parrot.flows.dev_loop.sdd_coder.background import BackgroundRegistry, ValidationSupervisor
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.test_scope.datatypes import Invocation, ScopePlan


def _supervisor(tmp_path: Path) -> tuple[ValidationSupervisor, BackgroundRegistry, Path]:
    """Build a supervisor with isolated durable and worktree roots."""
    store = ExecutionEvidenceStore(tmp_path / "evidence")
    registry = BackgroundRegistry(store=store, owner_instance_id="task-tier-owner")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    return ValidationSupervisor(registry=registry, store=store), registry, worktree


def _plan(*invocations: Invocation, tier: str = "task") -> ScopePlan:
    """Return a deterministic plan containing the supplied invocations."""
    return ScopePlan(
        tier=tier,
        invocations=invocations,
        escalated=(),
        core_hits=(),
        skipped_escalations=(),
        notes=(),
    )


async def test_supervisor_task_tier_admission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Task validation requires one task id, a fork SHA and an attempt uid before spawn."""
    supervisor, _registry, worktree = _supervisor(tmp_path)
    spawned = False

    async def fake_spawn(*_args: object, **_kwargs: object) -> None:
        nonlocal spawned
        spawned = True

    monkeypatch.setattr(background_module.asyncio, "create_subprocess_exec", fake_spawn)
    common = {
        "feature": "FEAT-709",
        "worktree": worktree,
        "execution_id": str(uuid.uuid4()),
        "tier": "task",
        "timeout_seconds": 5,
        "request_id": "task-admission",
    }
    with pytest.raises(ValueError, match="exactly one"):
        await supervisor.start(task_ids=["TASK-1", "TASK-2"], base_ref="abc123", attempt_uid="a1", **common)
    with pytest.raises(ValueError, match="explicit base_ref"):
        await supervisor.start(task_ids=["TASK-1"], base_ref=None, attempt_uid="a1", **common)
    with pytest.raises(ValueError, match="attempt_uid"):
        await supervisor.start(task_ids=["TASK-1"], base_ref="abc123", attempt_uid=None, **common)
    assert spawned is False


async def test_supervisor_verdict_persisted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A runner timeout keeps later evidence and persists the verdict before settlement."""
    supervisor, registry, worktree = _supervisor(tmp_path)
    config = worktree / ".parrot" / "test_runners.toml"
    config.parent.mkdir()
    config.write_text("[runners.pytest]\ntimeout_s = 1\n", encoding="utf-8")

    passing_child = (
        "import sys;"
        "p=[a for a in sys.argv if a.startswith('--junitxml=')][0].split('=',1)[1];"
        "open(p,'w').write(\"<testsuites><testsuite tests='1'><testcase file='tests/test_ok.py' "
        "classname='tests.test_ok' name='test_ok'/></testsuite></testsuites>\")"
    )
    invocations = (
        Invocation("root", (sys.executable, "-c", "import time; time.sleep(5)"), ()),
        Invocation("root", (sys.executable, "-c", passing_child), ()),
    )
    monkeypatch.setattr(background_module, "plan_tests", lambda **_kwargs: _plan(*invocations))
    monkeypatch.setattr(background_module, "protected_argv", lambda _cwd, argv: list(argv))

    def unexpected_green(*_args: object, **_kwargs: object) -> None:
        pytest.fail("a partial validation run must not write the green cache")

    monkeypatch.setattr(background_module.green_cache, "record_green", unexpected_green)
    transition = registry._record_transition

    async def checked_transition(*args: object, **kwargs: object) -> None:
        if kwargs.get("state") == "finished":
            assert supervisor._verdict_refs
        await transition(*args, **kwargs)

    monkeypatch.setattr(registry, "_record_transition", checked_transition)
    execution_id = str(uuid.uuid4())
    registration = await supervisor.start(
        feature="FEAT-709",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-4530"],
        tier="task",
        timeout_seconds=5,
        request_id="task-verdict",
        base_ref="abc123",
        attempt_uid="attempt-1",
    )
    assert registration.backend == "validation-subprocess"

    verdict = await supervisor.wait_verdict(execution_id, registration.handle, 10)
    assert verdict.status == "timed_out"
    assert [runner.status for runner in verdict.runners] == ["timed_out", "ok"]
    assert len(verdict.evidence) == 1
    assert (await registry.status(execution_id, registration.handle)).outcome == "timed_out"


async def test_merge_tier_includes_vitest_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A merge plan executes a Vitest invocation and reports its runner-qualified suite."""
    supervisor, _registry, worktree = _supervisor(tmp_path)
    passing_child = (
        "import sys;"
        "p=[a for a in sys.argv if a.startswith('--outputFile=')][0].split('=',1)[1];"
        "open(p,'w').write(\"<testsuites><testsuite tests='1'><testcase file='src/a.test.ts' "
        "classname='src.a' name='renders'/></testsuite></testsuites>\")"
    )
    invocation = Invocation(
        distribution="admin-ui",
        argv=(sys.executable, "-c", passing_child, "--outputFile="),
        targets=(),
        runner="vitest",
        report_format="junit",
    )
    monkeypatch.setattr(background_module, "plan_tests", lambda **_kwargs: _plan(invocation, tier="merge"))
    monkeypatch.setattr(background_module, "protected_argv", lambda _cwd, argv: list(argv))
    execution_id = str(uuid.uuid4())
    registration = await supervisor.start(
        feature="FEAT-709",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-4530"],
        tier="merge",
        timeout_seconds=5,
        request_id="merge-vitest",
    )
    verdict = await supervisor.wait_verdict(execution_id, registration.handle, 10)
    assert verdict.status == "passed"
    assert [(runner.runner, runner.suite) for runner in verdict.runners] == [("vitest", "vitest:admin-ui")]

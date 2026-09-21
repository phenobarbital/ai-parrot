"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers.

`ValidationSupervisor.start()` is spec-mandatory in its use of
`worktree_environment.protected_argv` (bwrap sandboxing) -- never an
unsandboxed fallback. This module's dev/CI shell already runs nested inside
its own Bubblewrap sandbox, where a SECOND, nested `bwrap` cannot create the
namespaces it needs (`No permissions to create new namespace`), independent
of anything under test here. Every scenario below therefore monkeypatches
`background_module.protected_argv` to an identity pass-through so the
*synthetic* child processes (real `python -c ...` subprocesses with
precisely controlled exit codes/signals/timing) run directly -- while
`test_idempotent_launch_and_scope` still asserts `protected_argv` is
actually CALLED with the selector's own argv, proving production code never
bypasses it. The sandbox's own namespace behavior is `worktree_environment.py`'s
existing test responsibility, not this task's.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import uuid
from pathlib import Path
from typing import Tuple

import pytest

from parrot.flows.dev_loop.sdd_coder import background as background_module
from parrot.flows.dev_loop.sdd_coder.background import (
    BackgroundConflictError,
    BackgroundRegistry,
    ValidationSupervisor,
)
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import BackgroundRegistration, BackgroundStatus
from parrot.flows.dev_loop.test_scope.datatypes import PytestInvocation, ScopePlan


def _make_supervisor(
    tmp_path: Path, *, owner_instance_id: str = "owner-A"
) -> Tuple[ValidationSupervisor, BackgroundRegistry, ExecutionEvidenceStore, Path]:
    """Build one supervisor over its own isolated evidence root and worktree."""
    store = ExecutionEvidenceStore(root=tmp_path / "evidence")
    worktree = tmp_path / "worktree"
    worktree.mkdir(exist_ok=True)
    registry = BackgroundRegistry(store=store, owner_instance_id=owner_instance_id)
    supervisor = ValidationSupervisor(registry=registry, store=store)
    return supervisor, registry, store, worktree


def _single_invocation_plan(argv: tuple[str, ...], *, tier: str = "merge") -> ScopePlan:
    """A `ScopePlan` carrying exactly one controlled, synthetic pytest-shaped invocation."""
    invocation = PytestInvocation(distribution="root", argv=argv, targets=())
    return ScopePlan(tier=tier, invocations=(invocation,), escalated=(), core_hits=(), skipped_escalations=(), notes=())


async def _settle(supervisor: ValidationSupervisor, execution_id: str, handle: str) -> None:
    """Await the background settlement task this supervisor keeps for *handle*.

    Test-only seam (`_background_tasks` is a private attribute): lets a test
    observe the terminal receipt deterministically instead of polling
    `coder_bg_status` in a loop.
    """
    task = supervisor._background_tasks[(execution_id, handle)]
    await asyncio.wait_for(task, timeout=15)


async def test_idempotent_launch_and_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same request and payload launch once; conflict and foreign task ids fail."""
    supervisor, registry, _store, worktree = _make_supervisor(tmp_path)
    execution_id = str(uuid.uuid4())

    plan_calls: list[str] = []

    def _fake_plan_tests(*, worktree: Path, changed_files: list[str], tier: str, declared=(), policy=None) -> ScopePlan:
        plan_calls.append(tier)
        return _single_invocation_plan((sys.executable, "-c", "import sys; sys.exit(0)"), tier=tier)

    protected_calls: list[tuple[Path, tuple[str, ...]]] = []

    def _fake_protected_argv(cwd: Path, argv: list[str]) -> list[str]:
        protected_calls.append((cwd, tuple(argv)))
        return list(argv)

    monkeypatch.setattr(background_module, "plan_tests", _fake_plan_tests)
    monkeypatch.setattr(background_module, "protected_argv", _fake_protected_argv)

    kwargs = dict(
        feature="demo-feature",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-1"],
        tier="merge",
        timeout_seconds=5,
    )
    first = await supervisor.start(request_id="req-1", **kwargs)
    second = await supervisor.start(request_id="req-1", **kwargs)

    assert first.handle == "req-1"
    assert second.handle == "req-1"
    assert first.launch_id == second.launch_id
    # The idempotent replay never re-built a plan or spawned a second process.
    assert plan_calls == ["merge"]
    assert len(protected_calls) == 1
    assert protected_calls[0][1] == (sys.executable, "-c", "import sys; sys.exit(0)")

    await _settle(supervisor, execution_id, "req-1")
    settled: BackgroundStatus = await registry.status(execution_id, "req-1")
    assert settled.state == "finished"
    assert settled.outcome == "completed"
    assert settled.exit_code == 0

    # Same request_id, a DIFFERENT payload (task_ids changed) -- rejected,
    # never a silent second process.
    with pytest.raises(BackgroundConflictError):
        await supervisor.start(request_id="req-1", **{**kwargs, "task_ids": ["TASK-2"]})

    # A malformed ("foreign") task id is rejected before anything is admitted.
    with pytest.raises(ValueError):
        await supervisor.start(request_id="req-2", **{**kwargs, "task_ids": ["not-a-task-id"]})

    # An invalid tier/timeout is rejected the same way (AC21).
    with pytest.raises(ValueError):
        await supervisor.start(request_id="req-3", **{**kwargs, "tier": "task"})
    with pytest.raises(ValueError):
        await supervisor.start(request_id="req-4", **{**kwargs, "timeout_seconds": 0})
    with pytest.raises(ValueError):
        await supervisor.start(request_id="req-5", **{**kwargs, "timeout_seconds": 7201})
    with pytest.raises(ValueError):
        await supervisor.start(request_id="req-6", **{**kwargs, "task_ids": []})
    with pytest.raises(ValueError):
        await supervisor.start(request_id="", **{**kwargs, "task_ids": ["TASK-1"]})

    # Real (unmocked) selector integration: an empty, non-git worktree yields
    # no applicable invocations, and the request settles immediately as
    # completed -- exercising the actual `plan_tests`/`changed_files` wiring
    # (spec R8: "construye argv desde índice/contrato"), not the monkeypatch
    # used above, and covering the `tier="feature"` path.
    monkeypatch.undo()
    empty_registration = await supervisor.start(
        feature="demo-feature",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-9"],
        tier="feature",
        timeout_seconds=5,
        request_id="req-empty",
    )
    assert (execution_id, empty_registration.handle) not in supervisor._background_tasks
    empty_status = await registry.status(execution_id, empty_registration.handle)
    assert empty_status.state == "finished"
    assert empty_status.outcome == "completed"
    assert empty_status.exit_code == 0


async def test_exit_signal_and_deadline_receipts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real process exits, signals and an imposed deadline remain distinct after reap."""
    supervisor, registry, store, worktree = _make_supervisor(tmp_path)
    monkeypatch.setattr(background_module, "protected_argv", lambda cwd, argv: list(argv))

    async def _run(
        request_id: str, argv: tuple[str, ...], *, timeout_seconds: int = 5
    ) -> tuple[BackgroundStatus, BackgroundRegistration, str]:
        monkeypatch.setattr(background_module, "plan_tests", lambda **_: _single_invocation_plan(argv, tier="feature"))
        execution_id = str(uuid.uuid4())
        registration = await supervisor.start(
            feature="demo-feature",
            worktree=worktree,
            execution_id=execution_id,
            task_ids=["TASK-1"],
            tier="feature",
            timeout_seconds=timeout_seconds,
            request_id=request_id,
        )
        await _settle(supervisor, execution_id, registration.handle)
        status = await registry.status(execution_id, registration.handle)
        return status, registration, execution_id

    # Exit 0 -> a clean, accepted-shape completion.
    status, _reg, _exec_id = await _run("exit-0", (sys.executable, "-c", "import sys; sys.exit(0)"))
    assert status.outcome == "completed"
    assert status.exit_code == 0

    # Exit 1 -> failed, verbatim.
    status, _reg, _exec_id = await _run("exit-1", (sys.executable, "-c", "import sys; sys.exit(1)"))
    assert status.outcome == "failed"
    assert status.exit_code == 1

    # Exit 124 chosen by the CHILD itself (not our own deadline) must never
    # be reinterpreted as `timed_out` (spec R8: "un código 124 aislado no
    # demuestra que el supervisor impuso timeout").
    status, _reg, _exec_id = await _run("exit-124", (sys.executable, "-c", "import sys; sys.exit(124)"))
    assert status.outcome == "failed"
    assert status.exit_code == 124

    # A real signal: the child kills itself. The negative returncode (the
    # signal) is preserved verbatim, never converted into success.
    status, _reg, _exec_id = await _run(
        "exit-signal", (sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)")
    )
    assert status.outcome == "failed"
    assert status.exit_code == -signal.SIGTERM

    # "log grande": on-disk growth stays bounded and the child is never
    # stalled -- the drain keeps consuming the pipe past the cap.
    large_log_script = "import sys\nsys.stdout.write('x' * (3 * 1024 * 1024))\nsys.stdout.flush()\nsys.exit(0)\n"
    status, registration, execution_id = await _run("large-log", (sys.executable, "-c", large_log_script))
    assert status.outcome == "completed"
    log_path = supervisor._log_path(execution_id, registration.handle)
    assert log_path.stat().st_size <= background_module._MAX_SUPERVISED_LOG_BYTES + 4096
    assert status.log_ref is not None

    # Deadline + "own child": the child spawns its own grandchild and sleeps
    # well past the imposed timeout; the supervisor must terminate the WHOLE
    # owned process tree (never just the immediate child) and still produce
    # a reaped, terminal receipt.
    marker = tmp_path / "grandchild.pid"
    child_script = (
        "import subprocess, sys\n"
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(marker)!r}, 'w').write(str(p.pid))\n"
        "import time\n"
        "time.sleep(60)\n"
    )
    status, _registration, _execution_id = await _run(
        "deadline", (sys.executable, "-c", child_script), timeout_seconds=1
    )
    assert status.outcome == "timed_out"

    grandchild_pid = int(marker.read_text())
    for _ in range(50):
        try:
            os.kill(grandchild_pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("grandchild process was not terminated by the supervisor's deadline")

    # `store` stays referenced only to keep the fixture's evidence root alive
    # for the whole test; nothing further is asserted on it directly here.
    assert store.root.exists()


async def test_lost_owner_blocks_settlement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spawn/persistence failure and unknown ownership never report settled validation."""
    supervisor, registry, store, worktree = _make_supervisor(tmp_path, owner_instance_id="owner-A")
    execution_id = str(uuid.uuid4())

    monkeypatch.setattr(
        background_module,
        "plan_tests",
        lambda **_: _single_invocation_plan((sys.executable, "-c", "import sys; sys.exit(0)"), tier="feature"),
    )

    def _raising_protected_argv(cwd: Path, argv: list[str]) -> list[str]:
        raise RuntimeError("Bubblewrap (bwrap) is required for SDD commands; refusing unsandboxed execution.")

    monkeypatch.setattr(background_module, "protected_argv", _raising_protected_argv)

    # A spawn failure (here: bwrap refusing, exactly as `protected_argv`
    # itself raises when unavailable) must never be swallowed into a
    # fabricated "finished" receipt: it propagates to the caller, and the
    # registry's own durable record stays `pending` -- never settled.
    with pytest.raises(RuntimeError):
        await supervisor.start(
            feature="demo-feature",
            worktree=worktree,
            execution_id=execution_id,
            task_ids=["TASK-1"],
            tier="feature",
            timeout_seconds=5,
            request_id="req-spawn-fail",
        )
    stuck_status = await registry.status(execution_id, "req-spawn-fail")
    assert stuck_status.state == "pending"
    assert stuck_status.outcome is None
    assert stuck_status.exit_code is None
    assert (execution_id, "req-spawn-fail") not in supervisor._background_tasks

    # The in-process claim was released on failure -- a retry under the SAME
    # request_id (same payload) is not permanently locked out once the
    # underlying failure is fixed; it is still the SAME idempotent admission.
    monkeypatch.setattr(background_module, "protected_argv", lambda cwd, argv: list(argv))
    recovered = await supervisor.start(
        feature="demo-feature",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-1"],
        tier="feature",
        timeout_seconds=5,
        request_id="req-spawn-fail",
    )
    await _settle(supervisor, execution_id, recovered.handle)
    recovered_status = await registry.status(execution_id, recovered.handle)
    assert recovered_status.state == "finished"
    assert recovered_status.outcome == "completed"

    # A still-running validation, observed through a FRESH `BackgroundRegistry`
    # instance with a DIFFERENT `owner_instance_id` (e.g. the supervising
    # process restarted), is never reported as settled: ownership was lost
    # before any terminal receipt was durably recorded, so it degrades to
    # `unknown`, never a resurrected `running`/`finished`.
    monkeypatch.setattr(
        background_module,
        "plan_tests",
        lambda **_: _single_invocation_plan((sys.executable, "-c", "import time; time.sleep(1)"), tier="feature"),
    )
    running_registration = await supervisor.start(
        feature="demo-feature",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-2"],
        tier="feature",
        timeout_seconds=5,
        request_id="req-still-running",
    )
    live_status = await registry.status(execution_id, running_registration.handle)
    assert live_status.state == "running"

    fresh_registry = BackgroundRegistry(store=store, owner_instance_id="owner-B")
    unknown_status = await fresh_registry.status(execution_id, running_registration.handle)
    assert unknown_status.state == "unknown"
    assert unknown_status.exit_code is None
    assert unknown_status.outcome is None
    assert unknown_status.stale is True

    # Let the real (still-owned) process settle so no dangling subprocess
    # leaks out of this test session.
    await _settle(supervisor, execution_id, running_registration.handle)

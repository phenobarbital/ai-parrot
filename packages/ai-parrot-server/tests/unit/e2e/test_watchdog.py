"""Unit and process-boundary tests for ``parrot.e2e.watchdog`` (TASK-3528, M3).

Every "acceptance"-flavored test below exercises a **real** OS process for
whatever this test's own scenario requires a real process for -- the
watchdog subprocess itself (:func:`spawn_watchdog`'s ack handshake), a real
"target" subprocess the watchdog must (or must not) terminate, and a real
"controller" subprocess whose death the watchdog must independently detect
-- per this task's own Test Specification: "any process-boundary acceptance
test must use real subprocesses." Only :func:`run_watchdog` itself is
invoked directly as a plain coroutine (not via a second real ``python -m``
child) for the monitor-loop trigger tests: that keeps the fatal-trigger
timing deterministic and fast, while every process it must (or must not)
signal is still real.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil
import pytest

from parrot.e2e import state as e2e_state
from parrot.e2e import watchdog as watchdog_module
from parrot.e2e.errors import E2EConfigError
from parrot.e2e.models import ProcessIdentity, RunState
from parrot.e2e.watchdog import WatchdogSpawnError

_FEATURE_ID = "FEAT-581"
_OWNER_ID = "owner-1"
_TARGET_ID = "target-a"

_LONG_SLEEP_SCRIPT = "import time; time.sleep(60)"
_IGNORE_SIGTERM_SCRIPT = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def spawned(worktree: Path):
    """Tracks every real subprocess a test spawns; force-kills leftovers on teardown."""
    processes: list["asyncio.subprocess.Process"] = []

    async def _spawn(*, ignore_sigterm: bool = False) -> "asyncio.subprocess.Process":
        script = _IGNORE_SIGTERM_SCRIPT if ignore_sigterm else _LONG_SLEEP_SCRIPT
        process = await asyncio.create_subprocess_exec(sys.executable, "-u", "-c", script, start_new_session=True)
        processes.append(process)
        return process

    yield _spawn

    for process in processes:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)


def _make_run_state(
    *,
    worktree: Path,
    run_id: str,
    process_identity: ProcessIdentity,
    controller_identity: ProcessIdentity,
    deadline: datetime,
    status: str = "starting",
    cleanup_complete: bool = False,
) -> RunState:
    now = datetime.now(timezone.utc)
    started_at = deadline - timedelta(seconds=1) if deadline < now else now
    run_directory = e2e_state.run_dir(run_id, worktree=worktree)
    return RunState(
        feature_id=_FEATURE_ID,
        run_id=run_id,
        worktree=str(worktree),
        owner_id=_OWNER_ID,
        controller_identity=controller_identity,
        supervisor_identity=controller_identity,
        process_identity=process_identity,
        target_id=_TARGET_ID,
        status=status,
        endpoint=None,
        control_socket=str(run_directory / "control.sock"),
        started_at=started_at,
        deadline=deadline,
        log_path=str(worktree / f"{run_id}.log"),
        cleanup_complete=cleanup_complete,
    )


async def _wait_exited(process: "asyncio.subprocess.Process", *, timeout_s: float = 5.0) -> None:
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(process.wait(), timeout=timeout_s)


# ----------------------------------------------------------------------
# record_heartbeat / _heartbeat_age_s -- pure unit tests
# ----------------------------------------------------------------------


def test_record_heartbeat_creates_fresh_marker(worktree: Path) -> None:
    run_id = "hb-run-0001"
    e2e_state.run_dir(run_id, worktree=worktree)

    assert watchdog_module._heartbeat_age_s(run_id, worktree=worktree) is None

    watchdog_module.record_heartbeat(run_id, worktree=worktree)
    age = watchdog_module._heartbeat_age_s(run_id, worktree=worktree)
    assert age is not None
    assert age < 1.0


# ----------------------------------------------------------------------
# spawn_watchdog() -- real subprocess ack handshake
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_watchdog_real_subprocess_acknowledges_and_stops(worktree: Path) -> None:
    run_id = "spawn-run-0001"

    handle = await watchdog_module.spawn_watchdog(run_id, worktree=worktree, bootstrap_timeout_s=2.0)
    try:
        assert psutil.pid_exists(handle.pid)
        ack_path = e2e_state.run_dir(run_id, worktree=worktree) / watchdog_module.ACK_FILENAME
        assert ack_path.is_file()
        assert ack_path.read_text(encoding="utf-8").strip() == str(handle.pid)

        # Heartbeat handshake: spawn_watchdog() already sent one.
        assert watchdog_module._heartbeat_age_s(run_id, worktree=worktree) is not None
        await handle.send_heartbeat()
    finally:
        await handle.stop()

    assert not psutil.pid_exists(handle.pid)
    # Idempotent: stopping an already-stopped handle never raises.
    await handle.stop()


@pytest.mark.asyncio
async def test_spawn_watchdog_raises_when_process_cannot_start(worktree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fail_exec(*args, **kwargs):
        raise OSError("no such executable")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fail_exec)

    with pytest.raises(WatchdogSpawnError) as excinfo:
        await watchdog_module.spawn_watchdog("spawn-run-broken", worktree=worktree)
    assert excinfo.value.reason_code == "watchdog_spawn_failed"


# ----------------------------------------------------------------------
# run_watchdog() -- bootstrap: registration never happens
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_watchdog_exits_cleanly_when_registration_never_happens(worktree: Path) -> None:
    run_id = "never-registered-0001"

    # Bounded and fast: no RunState is ever written for this run_id.
    await watchdog_module.run_watchdog(run_id, worktree=worktree, bootstrap_timeout_s=0.2, poll_interval_s=0.05)

    # Nothing was persisted to reconcile; this is not an error condition.
    with pytest.raises(E2EConfigError):
        e2e_state.read_state(run_id, worktree=worktree)


# ----------------------------------------------------------------------
# run_watchdog() -- fatal triggers tear down the owned target
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_watchdog_tears_down_owned_target_on_heartbeat_expiry(worktree: Path, spawned) -> None:
    run_id = "heartbeat-expiry-0001"
    target_process = await spawned()
    controller_identity = e2e_state.capture_process_identity(os.getpid(), owned=False)
    target_identity = e2e_state.capture_process_identity(target_process.pid, owned=True)
    state = _make_run_state(
        worktree=worktree,
        run_id=run_id,
        process_identity=target_identity,
        controller_identity=controller_identity,
        deadline=datetime.now(timezone.utc) + timedelta(seconds=600),
    )
    e2e_state.write_state(state, worktree=worktree)
    watchdog_module.record_heartbeat(run_id, worktree=worktree)  # one fresh heartbeat, then silence

    await watchdog_module.run_watchdog(
        run_id, worktree=worktree, heartbeat_expiry_s=0.2, poll_interval_s=0.05, bootstrap_timeout_s=2.0
    )

    await _wait_exited(target_process)
    assert target_process.returncode is not None
    final = e2e_state.read_state(run_id, worktree=worktree)
    assert final.status == "stopped"
    assert final.cleanup_complete is True


@pytest.mark.asyncio
async def test_run_watchdog_tears_down_owned_target_on_deadline_expiry(worktree: Path, spawned) -> None:
    run_id = "deadline-expiry-0001"
    target_process = await spawned()
    controller_identity = e2e_state.capture_process_identity(os.getpid(), owned=False)
    target_identity = e2e_state.capture_process_identity(target_process.pid, owned=True)
    state = _make_run_state(
        worktree=worktree,
        run_id=run_id,
        process_identity=target_identity,
        controller_identity=controller_identity,
        deadline=datetime.now(timezone.utc) - timedelta(seconds=1),  # already expired
    )
    e2e_state.write_state(state, worktree=worktree)
    watchdog_module.record_heartbeat(run_id, worktree=worktree)  # heartbeats stay fresh; irrelevant here

    await watchdog_module.run_watchdog(
        run_id, worktree=worktree, heartbeat_expiry_s=30.0, poll_interval_s=0.05, bootstrap_timeout_s=2.0
    )

    await _wait_exited(target_process)
    assert target_process.returncode is not None
    final = e2e_state.read_state(run_id, worktree=worktree)
    assert final.status == "stopped"
    assert final.cleanup_complete is True


@pytest.mark.asyncio
async def test_run_watchdog_tears_down_owned_target_on_controller_death(worktree: Path, spawned) -> None:
    run_id = "controller-death-0001"
    target_process = await spawned()
    controller_process = await spawned()
    controller_identity = e2e_state.capture_process_identity(controller_process.pid, owned=False)
    target_identity = e2e_state.capture_process_identity(target_process.pid, owned=True)
    state = _make_run_state(
        worktree=worktree,
        run_id=run_id,
        process_identity=target_identity,
        controller_identity=controller_identity,
        deadline=datetime.now(timezone.utc) + timedelta(seconds=600),
    )
    e2e_state.write_state(state, worktree=worktree)
    watchdog_module.record_heartbeat(run_id, worktree=worktree)

    controller_process.kill()
    await _wait_exited(controller_process)

    await watchdog_module.run_watchdog(
        run_id, worktree=worktree, heartbeat_expiry_s=30.0, poll_interval_s=0.05, bootstrap_timeout_s=2.0
    )

    await _wait_exited(target_process)
    assert target_process.returncode is not None
    final = e2e_state.read_state(run_id, worktree=worktree)
    assert final.status == "stopped"
    assert final.cleanup_complete is True


# ----------------------------------------------------------------------
# run_watchdog() -- must never signal what it should not
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_watchdog_exits_without_touching_already_cleanup_complete_run(worktree: Path, spawned) -> None:
    run_id = "already-done-0001"
    target_process = await spawned()
    controller_identity = e2e_state.capture_process_identity(os.getpid(), owned=False)
    target_identity = e2e_state.capture_process_identity(target_process.pid, owned=True)
    state = _make_run_state(
        worktree=worktree,
        run_id=run_id,
        process_identity=target_identity,
        controller_identity=controller_identity,
        deadline=datetime.now(timezone.utc) - timedelta(seconds=1),  # would trigger, if ever inspected
        status="stopped",
        cleanup_complete=True,
    )
    e2e_state.write_state(state, worktree=worktree)

    await watchdog_module.run_watchdog(
        run_id, worktree=worktree, heartbeat_expiry_s=30.0, poll_interval_s=0.05, bootstrap_timeout_s=2.0
    )

    # A supervisor-completed run is left entirely untouched.
    assert target_process.returncode is None
    assert psutil.pid_exists(target_process.pid)
    final = e2e_state.read_state(run_id, worktree=worktree)
    assert final.status == "stopped"
    assert final.cleanup_complete is True


@pytest.mark.asyncio
async def test_run_watchdog_never_signals_unowned_adopted_target(worktree: Path, spawned) -> None:
    run_id = "adopted-0001"
    target_process = await spawned()
    controller_identity = e2e_state.capture_process_identity(os.getpid(), owned=False)
    # owned=False: this run's target was adopted, never spawned by "this" supervisor.
    target_identity = e2e_state.capture_process_identity(target_process.pid, owned=False)
    state = _make_run_state(
        worktree=worktree,
        run_id=run_id,
        process_identity=target_identity,
        controller_identity=controller_identity,
        deadline=datetime.now(timezone.utc) - timedelta(seconds=1),  # expired -- would trigger teardown
    )
    e2e_state.write_state(state, worktree=worktree)
    watchdog_module.record_heartbeat(run_id, worktree=worktree)

    await watchdog_module.run_watchdog(
        run_id, worktree=worktree, heartbeat_expiry_s=30.0, poll_interval_s=0.05, bootstrap_timeout_s=2.0
    )

    # Never signaled: still alive.
    assert target_process.returncode is None
    assert psutil.pid_exists(target_process.pid)
    final = e2e_state.read_state(run_id, worktree=worktree)
    assert final.status == "failed"
    assert final.cleanup_complete is False
    assert final.shutdown_forced is False


# ----------------------------------------------------------------------
# reconcile_stale_run() -- the documented next-invocation recovery path
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_stale_run_marks_dead_target_cleaned_without_signaling(worktree: Path, spawned) -> None:
    run_id = "reconcile-dead-0001"
    target_process = await spawned()
    controller_identity = e2e_state.capture_process_identity(os.getpid(), owned=False)
    target_identity = e2e_state.capture_process_identity(target_process.pid, owned=True)

    # The target already exited on its own before this (later) invocation.
    target_process.kill()
    await _wait_exited(target_process)

    state = _make_run_state(
        worktree=worktree,
        run_id=run_id,
        process_identity=target_identity,
        controller_identity=controller_identity,
        deadline=datetime.now(timezone.utc) + timedelta(seconds=600),
    )
    e2e_state.write_state(state, worktree=worktree)

    final = await watchdog_module.reconcile_stale_run(run_id, worktree=worktree)

    assert final.status == "stopped"
    assert final.cleanup_complete is True
    assert final.shutdown_forced is False  # already gone -- no signal was ever needed


@pytest.mark.asyncio
async def test_reconcile_stale_run_noop_when_not_stale(worktree: Path, spawned) -> None:
    run_id = "reconcile-live-0001"
    target_process = await spawned()
    controller_identity = e2e_state.capture_process_identity(os.getpid(), owned=False)
    target_identity = e2e_state.capture_process_identity(target_process.pid, owned=True)
    state = _make_run_state(
        worktree=worktree,
        run_id=run_id,
        process_identity=target_identity,
        controller_identity=controller_identity,
        deadline=datetime.now(timezone.utc) + timedelta(seconds=600),
    )
    e2e_state.write_state(state, worktree=worktree)

    final = await watchdog_module.reconcile_stale_run(run_id, worktree=worktree)

    assert final.status == "starting"
    assert final.cleanup_complete is False
    # A live, non-stale run is never signaled.
    assert target_process.returncode is None
    assert psutil.pid_exists(target_process.pid)

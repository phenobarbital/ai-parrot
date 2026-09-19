"""Unit and process-boundary tests for ``parrot.e2e.state`` (TASK-3524, M3).

Every filesystem test uses a synthetic worktree under ``tmp_path`` — never
the real repository — passed explicitly as the ``worktree`` argument to every
function under test, so nothing here ever touches ``$HOME``/XDG or the real
``sdd/`` tree (this module takes no implicit convention path; ``worktree``
is always caller-supplied). PID-reuse, stale-state and concurrent-lock
coverage uses real, disposable subprocesses (never mocked) per this task's
own Test Specification: "any process-boundary acceptance test must use real
subprocesses."
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest

from parrot.e2e.errors import E2EConfigError
from parrot.e2e.models import ProcessIdentity, RunState
from parrot.e2e import state

_FEATURE_ID = "FEAT-581"
_OWNER_ID = "owner-1"
_TARGET_ID = "target-1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _self_identity(*, owned: bool = True) -> ProcessIdentity:
    """A ProcessIdentity for the current test process itself (always alive)."""
    return state.capture_process_identity(os.getpid(), owned=owned)


def _make_state(
    *,
    worktree: Path,
    run_id: str = "run-1",
    process_identity: Optional[ProcessIdentity] = None,
    owner_id: str = _OWNER_ID,
    status: str = "starting",
    deadline: Optional[datetime] = None,
) -> RunState:
    """Build a schema-valid RunState anchored at ``worktree`` for one test."""
    now = datetime.now(timezone.utc)
    # Always well before any deadline used in these tests (600s in the
    # future by default, or a few seconds in the past for staleness cases).
    started_at = now - timedelta(seconds=700)
    identity = process_identity if process_identity is not None else _self_identity()
    return RunState(
        feature_id=_FEATURE_ID,
        run_id=run_id,
        worktree=str(worktree),
        owner_id=owner_id,
        controller_identity=_self_identity(),
        supervisor_identity=_self_identity(),
        process_identity=identity,
        target_id=_TARGET_ID,
        status=status,
        endpoint=None,
        control_socket=str(worktree / "sdd" / "state" / "e2e" / run_id / "control.sock"),
        started_at=started_at,
        deadline=deadline if deadline is not None else now + timedelta(seconds=600),
        log_path=str(worktree / "artifacts" / "logs" / "e2e" / run_id / "run.log"),
    )


def _spawn_sleeper(seconds: float = 30.0) -> subprocess.Popen:
    """Spawn a real, disposable child process that sleeps, for identity tests."""
    return subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"])


def _terminate(proc: subprocess.Popen) -> None:
    with contextlib.suppress(ProcessLookupError):
        proc.terminate()
    proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# state_dir / run_dir — modes and symlink/path-attack rejection
# ---------------------------------------------------------------------------


def test_state_dir_creates_worktree_local_tree(tmp_path: Path) -> None:
    directory = state.state_dir(tmp_path)
    assert directory == (tmp_path / "sdd" / "state" / "e2e").resolve()
    assert directory.is_dir()


def test_run_dir_is_mode_0700(tmp_path: Path) -> None:
    directory = state.run_dir("run-1", worktree=tmp_path)
    assert directory.is_dir()
    assert (directory.stat().st_mode & 0o777) == 0o700


def test_run_dir_is_idempotent(tmp_path: Path) -> None:
    first = state.run_dir("run-1", worktree=tmp_path)
    second = state.run_dir("run-1", worktree=tmp_path)
    assert first == second
    assert (second.stat().st_mode & 0o777) == 0o700


def test_run_dir_rejects_symlink_at_leaf(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-target"
    outside.mkdir(exist_ok=True)
    e2e_dir = state.state_dir(tmp_path)
    (e2e_dir / "run-1").symlink_to(outside, target_is_directory=True)

    with pytest.raises(E2EConfigError) as excinfo:
        state.run_dir("run-1", worktree=tmp_path)
    assert excinfo.value.reason_code == "path_symlink_escape"
    # Nothing was written through the attacker's symlink target.
    assert list(outside.iterdir()) == []


def test_state_dir_rejects_symlink_at_e2e_level(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-e2e"
    outside.mkdir(exist_ok=True)
    (tmp_path / "sdd").mkdir()
    (tmp_path / "sdd" / "state").mkdir()
    (tmp_path / "sdd" / "state" / "e2e").symlink_to(outside, target_is_directory=True)

    with pytest.raises(E2EConfigError) as excinfo:
        state.state_dir(tmp_path)
    assert excinfo.value.reason_code == "path_symlink_escape"
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("bad_run_id", ["", "../escape", "/abs", "a/b", "a\\b", "*wild", ".leading-dot"])
def test_run_id_validation_rejects_unsafe_ids(tmp_path: Path, bad_run_id: str) -> None:
    with pytest.raises(E2EConfigError) as excinfo:
        state.state_path(bad_run_id, worktree=tmp_path)
    assert excinfo.value.reason_code == "run_id_unsafe"


# ---------------------------------------------------------------------------
# write_state / read_state — atomic, mode 0600, worktree cross-check
# ---------------------------------------------------------------------------


def test_write_then_read_state_roundtrip(tmp_path: Path) -> None:
    run_state = _make_state(worktree=tmp_path)
    state.write_state(run_state, worktree=tmp_path)

    loaded = state.read_state(run_state.run_id, worktree=tmp_path)
    assert loaded == run_state

    target = state.state_path(run_state.run_id, worktree=tmp_path)
    assert (target.stat().st_mode & 0o777) == 0o600


def test_write_state_rejects_worktree_mismatch(tmp_path: Path) -> None:
    other = tmp_path / "not-the-real-worktree"
    run_state = _make_state(worktree=other)
    # `other` need not exist; the mismatch is caught before any filesystem
    # containment check against the *target* worktree's own path.
    with pytest.raises(E2EConfigError) as excinfo:
        state.write_state(run_state, worktree=tmp_path)
    assert excinfo.value.reason_code == "worktree_mismatch"


def test_read_state_missing_run_raises(tmp_path: Path) -> None:
    with pytest.raises(E2EConfigError) as excinfo:
        state.read_state("nonexistent-run", worktree=tmp_path)
    assert excinfo.value.reason_code == "state_missing"


def test_read_state_rejects_malformed_json(tmp_path: Path) -> None:
    directory = state.state_dir(tmp_path)
    (directory / "run-1.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(E2EConfigError) as excinfo:
        state.read_state("run-1", worktree=tmp_path)
    assert excinfo.value.reason_code == "state_invalid"


def test_read_state_rejects_symlinked_state_file(tmp_path: Path) -> None:
    secret = tmp_path.parent / "secret.json"
    secret.write_text(json.dumps({"leaked": True}), encoding="utf-8")
    directory = state.state_dir(tmp_path)
    (directory / "run-1.json").symlink_to(secret)

    with pytest.raises(E2EConfigError) as excinfo:
        state.read_state("run-1", worktree=tmp_path)
    assert excinfo.value.reason_code == "state_symlink_escape"


def test_write_state_rejects_symlinked_destination(tmp_path: Path) -> None:
    secret = tmp_path.parent / "secret2.json"
    secret.write_text("{}", encoding="utf-8")
    directory = state.state_dir(tmp_path)
    run_state = _make_state(worktree=tmp_path)
    (directory / f"{run_state.run_id}.json").symlink_to(secret)

    with pytest.raises(E2EConfigError) as excinfo:
        state.write_state(run_state, worktree=tmp_path)
    assert excinfo.value.reason_code == "state_symlink_escape"
    # The attacker's target was never overwritten.
    assert secret.read_text(encoding="utf-8") == "{}"


def test_read_state_rejects_run_id_field_mismatch(tmp_path: Path) -> None:
    run_state = _make_state(worktree=tmp_path, run_id="run-a")
    state.write_state(run_state, worktree=tmp_path)
    directory = state.state_dir(tmp_path)
    (directory / "run-b.json").write_bytes((directory / "run-a.json").read_bytes())

    with pytest.raises(E2EConfigError) as excinfo:
        state.read_state("run-b", worktree=tmp_path)
    assert excinfo.value.reason_code == "state_run_id_mismatch"


def test_write_state_retains_failed_status_not_deleted(tmp_path: Path) -> None:
    """Failed/unreaped runs are persisted as-is; write_state never auto-cleans them."""
    run_state = _make_state(worktree=tmp_path, status="failed")
    state.write_state(run_state, worktree=tmp_path)
    loaded = state.read_state(run_state.run_id, worktree=tmp_path)
    assert loaded.status == "failed"
    assert loaded.cleanup_complete is False


def test_delete_state_is_idempotent(tmp_path: Path) -> None:
    run_state = _make_state(worktree=tmp_path)
    state.write_state(run_state, worktree=tmp_path)
    state.delete_state(run_state.run_id, worktree=tmp_path)
    assert not state.state_path(run_state.run_id, worktree=tmp_path).exists()
    # Second delete of an already-missing file must not raise.
    state.delete_state(run_state.run_id, worktree=tmp_path)


def test_delete_state_rejects_symlink(tmp_path: Path) -> None:
    secret = tmp_path.parent / "secret3.json"
    secret.write_text("{}", encoding="utf-8")
    directory = state.state_dir(tmp_path)
    (directory / "run-1.json").symlink_to(secret)
    with pytest.raises(E2EConfigError) as excinfo:
        state.delete_state("run-1", worktree=tmp_path)
    assert excinfo.value.reason_code == "state_symlink_escape"
    assert secret.exists()


def test_list_run_ids_skips_symlinks(tmp_path: Path) -> None:
    run_a = _make_state(worktree=tmp_path, run_id="run-a")
    run_b = _make_state(worktree=tmp_path, run_id="run-b")
    state.write_state(run_a, worktree=tmp_path)
    state.write_state(run_b, worktree=tmp_path)

    directory = state.state_dir(tmp_path)
    outside = tmp_path.parent / "outside-run-c.json"
    outside.write_text("{}", encoding="utf-8")
    (directory / "run-c.json").symlink_to(outside)

    assert state.list_run_ids(worktree=tmp_path) == ["run-a", "run-b"]


# ---------------------------------------------------------------------------
# Process identity — real subprocesses, PID reuse, stale, boot ID
# ---------------------------------------------------------------------------


def test_capture_process_identity_of_live_process() -> None:
    proc = _spawn_sleeper()
    try:
        identity = state.capture_process_identity(proc.pid, owned=True)
        assert identity.pid == proc.pid
        assert identity.pgid == os.getpgid(proc.pid)
        assert identity.owned is True
        assert identity.create_time.tzinfo is not None
        assert identity.boot_id == state.get_boot_id()
    finally:
        _terminate(proc)


def test_capture_process_identity_missing_process_raises() -> None:
    proc = _spawn_sleeper(seconds=0.1)
    proc.wait(timeout=5)
    with pytest.raises(E2EConfigError) as excinfo:
        state.capture_process_identity(proc.pid, owned=True)
    assert excinfo.value.reason_code == "process_unavailable"


def test_process_identity_matches_live_process() -> None:
    proc = _spawn_sleeper()
    try:
        identity = state.capture_process_identity(proc.pid, owned=True)
        assert state.process_identity_matches(proc.pid, identity) is True
    finally:
        _terminate(proc)


def test_process_identity_matches_false_after_exit() -> None:
    proc = _spawn_sleeper(seconds=0.1)
    identity = state.capture_process_identity(proc.pid, owned=True)
    proc.wait(timeout=5)
    # Give the OS a moment to fully reap/deregister the process table entry.
    time.sleep(0.2)
    assert state.process_identity_matches(proc.pid, identity) is False


def test_process_identity_matches_false_on_simulated_pid_reuse() -> None:
    """A real live process, but recorded with an unrelated creation time.

    Simulates PID reuse without depending on the OS actually reusing a PID:
    the *live* PGID/boot ID both agree, but the recorded `create_time` does
    not match this real, running process — exactly the signal that
    distinguishes "the process I started" from "something else now sitting
    on that PID".
    """
    proc = _spawn_sleeper()
    try:
        real_identity = state.capture_process_identity(proc.pid, owned=True)
        reused_identity = real_identity.model_copy(
            update={"create_time": real_identity.create_time - timedelta(hours=1)}
        )
        assert state.process_identity_matches(proc.pid, reused_identity) is False
    finally:
        _terminate(proc)


def test_process_identity_matches_false_on_wrong_boot_id() -> None:
    proc = _spawn_sleeper()
    try:
        real_identity = state.capture_process_identity(proc.pid, owned=True)
        wrong_boot = real_identity.model_copy(update={"boot_id": "not-the-real-boot-id"})
        assert state.process_identity_matches(proc.pid, wrong_boot) is False
    finally:
        _terminate(proc)


def test_process_identity_matches_false_on_wrong_pgid() -> None:
    proc = _spawn_sleeper()
    try:
        real_identity = state.capture_process_identity(proc.pid, owned=True)
        wrong_pgid = real_identity.model_copy(update={"pgid": real_identity.pgid + 1 if real_identity.pgid > 1 else real_identity.pgid + 2})
        assert state.process_identity_matches(proc.pid, wrong_pgid) is False
    finally:
        _terminate(proc)


# ---------------------------------------------------------------------------
# is_authorized_to_signal — owner/worktree/identity gating, never on adopted
# ---------------------------------------------------------------------------


def test_is_authorized_to_signal_true_when_everything_matches(tmp_path: Path) -> None:
    proc = _spawn_sleeper()
    try:
        identity = state.capture_process_identity(proc.pid, owned=True)
        run_state = _make_state(worktree=tmp_path, process_identity=identity)
        assert state.is_authorized_to_signal(run_state, worktree=tmp_path, owner_id=_OWNER_ID) is True
    finally:
        _terminate(proc)


def test_is_authorized_to_signal_false_for_adopted_process(tmp_path: Path) -> None:
    """Adopted (non-owned) identity refuses signaling even if everything else matches."""
    proc = _spawn_sleeper()
    try:
        identity = state.capture_process_identity(proc.pid, owned=False)
        run_state = _make_state(worktree=tmp_path, process_identity=identity)
        assert state.is_authorized_to_signal(run_state, worktree=tmp_path, owner_id=_OWNER_ID) is False
    finally:
        _terminate(proc)


def test_is_authorized_to_signal_false_for_wrong_owner(tmp_path: Path) -> None:
    proc = _spawn_sleeper()
    try:
        identity = state.capture_process_identity(proc.pid, owned=True)
        run_state = _make_state(worktree=tmp_path, process_identity=identity, owner_id="owner-1")
        assert state.is_authorized_to_signal(run_state, worktree=tmp_path, owner_id="owner-2") is False
    finally:
        _terminate(proc)


def test_is_authorized_to_signal_false_for_wrong_worktree(tmp_path: Path) -> None:
    proc = _spawn_sleeper()
    other = tmp_path / "other"
    other.mkdir()
    try:
        identity = state.capture_process_identity(proc.pid, owned=True)
        run_state = _make_state(worktree=tmp_path, process_identity=identity)
        assert state.is_authorized_to_signal(run_state, worktree=other, owner_id=_OWNER_ID) is False
    finally:
        _terminate(proc)


def test_is_authorized_to_signal_false_for_exited_process(tmp_path: Path) -> None:
    proc = _spawn_sleeper(seconds=0.1)
    identity = state.capture_process_identity(proc.pid, owned=True)
    run_state = _make_state(worktree=tmp_path, process_identity=identity)
    proc.wait(timeout=5)
    time.sleep(0.2)
    assert state.is_authorized_to_signal(run_state, worktree=tmp_path, owner_id=_OWNER_ID) is False


def test_is_authorized_to_signal_false_for_pid_reuse_simulation(tmp_path: Path) -> None:
    proc = _spawn_sleeper()
    try:
        real_identity = state.capture_process_identity(proc.pid, owned=True)
        reused_identity = real_identity.model_copy(
            update={"create_time": real_identity.create_time - timedelta(hours=2)}
        )
        run_state = _make_state(worktree=tmp_path, process_identity=reused_identity)
        assert state.is_authorized_to_signal(run_state, worktree=tmp_path, owner_id=_OWNER_ID) is False
    finally:
        _terminate(proc)


# ---------------------------------------------------------------------------
# is_stale
# ---------------------------------------------------------------------------


def test_is_stale_true_when_deadline_passed(tmp_path: Path) -> None:
    proc = _spawn_sleeper()
    try:
        identity = state.capture_process_identity(proc.pid, owned=True)
        past_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
        run_state = _make_state(worktree=tmp_path, process_identity=identity, deadline=past_deadline)
        assert state.is_stale(run_state) is True
    finally:
        _terminate(proc)


def test_is_stale_true_when_process_exited(tmp_path: Path) -> None:
    proc = _spawn_sleeper(seconds=0.1)
    identity = state.capture_process_identity(proc.pid, owned=True)
    run_state = _make_state(worktree=tmp_path, process_identity=identity)
    proc.wait(timeout=5)
    time.sleep(0.2)
    assert state.is_stale(run_state) is True


def test_is_stale_false_when_alive_and_deadline_future(tmp_path: Path) -> None:
    proc = _spawn_sleeper()
    try:
        identity = state.capture_process_identity(proc.pid, owned=True)
        run_state = _make_state(worktree=tmp_path, process_identity=identity)
        assert state.is_stale(run_state) is False
    finally:
        _terminate(proc)


# ---------------------------------------------------------------------------
# locked_run — advisory locking, timeout, and real concurrent-process safety
# ---------------------------------------------------------------------------


def test_locked_run_serializes_within_process(tmp_path: Path) -> None:
    order: list[str] = []
    barrier_entered = threading.Event()

    def _worker(label: str) -> None:
        with state.locked_run("run-1", worktree=tmp_path, timeout_s=5.0):
            order.append(f"{label}-enter")
            barrier_entered.set()
            time.sleep(0.1)
            order.append(f"{label}-exit")

    t1 = threading.Thread(target=_worker, args=("a",))
    t2 = threading.Thread(target=_worker, args=("b",))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    # Whichever thread went first, it must fully exit before the other enters.
    assert order[0].endswith("-enter")
    assert order[1].endswith("-exit")
    assert order[1].split("-")[0] == order[0].split("-")[0]


def test_locked_run_times_out_when_held(tmp_path: Path) -> None:
    directory = state.state_dir(tmp_path)
    lock_path = directory / "run-1.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        with pytest.raises(TimeoutError):
            with state.locked_run("run-1", worktree=tmp_path, timeout_s=0.3):
                pass
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_locked_run_serializes_across_real_subprocesses(tmp_path: Path) -> None:
    """Real cross-process mutual exclusion — the exact primitive 'concurrent
    down' commands must serialize on (spec §2: "advisory file locks serialize
    state changes and concurrent down/stale commands.").
    """
    counter_path = tmp_path / "counter.txt"
    counter_path.write_text("0", encoding="utf-8")

    worker_script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from parrot.e2e import state\n"
        "worktree = Path(sys.argv[1])\n"
        "counter_path = Path(sys.argv[2])\n"
        "iterations = int(sys.argv[3])\n"
        "for _ in range(iterations):\n"
        "    with state.locked_run('run-1', worktree=worktree, timeout_s=20.0):\n"
        "        current = int(counter_path.read_text())\n"
        "        counter_path.write_text(str(current + 1))\n"
    )

    iterations_per_worker = 25
    num_workers = 6
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", worker_script, str(tmp_path), str(counter_path), str(iterations_per_worker)],
            env=os.environ.copy(),
        )
        for _ in range(num_workers)
    ]
    for proc in procs:
        return_code = proc.wait(timeout=60)
        assert return_code == 0

    final_count = int(counter_path.read_text())
    assert final_count == num_workers * iterations_per_worker


def test_locked_run_makes_concurrent_down_idempotent(tmp_path: Path) -> None:
    """Concurrent 'down' invocations racing to mark cleanup complete never
    lose or corrupt the state file (spec §2 test table:
    `test_state_atomic_and_down_idempotent`)."""
    run_state = _make_state(worktree=tmp_path)
    state.write_state(run_state, worktree=tmp_path)

    worker_script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from parrot.e2e import state\n"
        "worktree = Path(sys.argv[1])\n"
        "run_id = sys.argv[2]\n"
        "with state.locked_run(run_id, worktree=worktree, timeout_s=20.0):\n"
        "    current = state.read_state(run_id, worktree=worktree)\n"
        "    if not current.cleanup_complete:\n"
        "        updated = current.model_copy(update={'cleanup_complete': True, 'status': 'stopped'})\n"
        "        state.write_state(updated, worktree=worktree)\n"
    )

    num_workers = 8
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", worker_script, str(tmp_path), run_state.run_id],
            env=os.environ.copy(),
        )
        for _ in range(num_workers)
    ]
    for proc in procs:
        return_code = proc.wait(timeout=60)
        assert return_code == 0

    final = state.read_state(run_state.run_id, worktree=tmp_path)
    assert final.cleanup_complete is True
    assert final.status == "stopped"

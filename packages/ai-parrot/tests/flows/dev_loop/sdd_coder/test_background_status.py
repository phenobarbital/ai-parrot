"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from parrot.flows.dev_loop.sdd_coder import background as background_module
from parrot.flows.dev_loop.sdd_coder.background import (
    BackgroundBudgetExceededError,
    BackgroundConflictError,
    BackgroundNotFoundError,
    BackgroundRegistry,
)
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import BackgroundRegistration

_EXECUTION_ID = str(uuid.uuid4())


def _registration(
    *,
    handle: str,
    worktree: Path,
    owner_instance_id: str = "owner-A",
    launch_id: str = "launch-1",
    kind: str = "validation",
    authority: str = "supervisor",
    execution_id: str = _EXECUTION_ID,
) -> BackgroundRegistration:
    return BackgroundRegistration(
        handle=handle,
        execution_id=execution_id,
        task_id="TASK-3563",
        attempt_uid="attempt-1",
        launch_id=launch_id,
        owner_instance_id=owner_instance_id,
        kind=kind,
        authority=authority,
        worktree=str(worktree),
        backend="pytest-subprocess",
        started_at=datetime.now(timezone.utc),
    )


async def test_restart_without_receipt_is_unknown(tmp_path: Path) -> None:
    """Losing owner authority never becomes finished by PID absence or empty logs."""
    store = ExecutionEvidenceStore(root=tmp_path / "evidence")
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    owner_a = BackgroundRegistry(store=store, owner_instance_id="owner-A")
    registration = _registration(handle="handle-restart", worktree=worktree, owner_instance_id="owner-A")
    handle = await owner_a.register(registration)

    # While the SAME owning instance is still alive, an explicit transition
    # to "running" is authoritative -- never inferred from PID probing.
    await owner_a._record_transition(_EXECUTION_ID, handle, state="running")
    live_status = await owner_a.status(_EXECUTION_ID, handle)
    assert live_status.state == "running"
    assert live_status.stale is False

    # Simulate a process restart: a brand-new BackgroundRegistry instance
    # (fresh in-memory state, new owner_instance_id) reads the SAME durable
    # root. No terminal receipt was ever recorded -- even though the
    # registration itself still exists on disk -- so the state must degrade
    # to "unknown", never resurrect "finished"/"running" from an absent PID
    # or an empty log.
    owner_b = BackgroundRegistry(store=store, owner_instance_id="owner-B")
    restarted_status = await owner_b.status(_EXECUTION_ID, handle)
    assert restarted_status.state == "unknown"
    assert restarted_status.exit_code is None
    assert restarted_status.outcome is None
    assert restarted_status.stale is True

    # Now the (still-alive) original owner durably records a terminal
    # receipt. A THIRD fresh instance (another restart) must read that
    # receipt back deterministically as "finished" -- durable across restart.
    await owner_a._record_transition(_EXECUTION_ID, handle, state="finished", outcome="completed", exit_code=0)
    owner_c = BackgroundRegistry(store=store, owner_instance_id="owner-C")
    finished_status = await owner_c.status(_EXECUTION_ID, handle)
    assert finished_status.state == "finished"
    assert finished_status.outcome == "completed"
    assert finished_status.exit_code == 0
    assert finished_status.stale is False


async def test_revision_and_incremental_tail(tmp_path: Path) -> None:
    """Only new state/log bytes advance revision; unchanged reads omit repeated tail."""
    store = ExecutionEvidenceStore(root=tmp_path / "evidence")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    log_dir = store.root / "executions" / _EXECUTION_ID / "background_logs"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "job.log"
    log_path.write_text("first line\n", encoding="utf-8")

    registry = BackgroundRegistry(store=store, owner_instance_id="owner-A")
    registration = _registration(
        handle="handle-revision", worktree=worktree, kind="native_agent", authority="host_observation"
    )
    handle = await registry.register(registration)

    first = await registry.status(_EXECUTION_ID, handle)
    assert first.revision == 0
    assert first.changed is True  # since_revision omitted => always "changed"

    # Reading again with the SAME revision (no transition happened in
    # between) must report changed=false and omit the tail payload.
    unchanged = await registry.status(_EXECUTION_ID, handle, since_revision=first.revision)
    assert unchanged.changed is False
    assert unchanged.log_tail is None
    assert unchanged.revision == first.revision
    # Backoff grows toward the max while nothing changes (fake clock below
    # makes this deterministic instead of depending on wall-clock timing).
    assert unchanged.next_poll_after_ms >= background_module._MIN_POLL_INTERVAL_MS

    # An authoritative transition that only appends log bytes (no state
    # change) still advances the revision -- new bytes count, elapsed time
    # alone never does.
    log_path.write_text("first line\nsecond line\n", encoding="utf-8")
    await registry._record_transition(_EXECUTION_ID, handle, state="running", log_path=log_path)
    after_log_growth = await registry.status(_EXECUTION_ID, handle, since_revision=first.revision, tail_bytes=64)
    assert after_log_growth.revision == first.revision + 1
    assert after_log_growth.changed is True
    assert after_log_growth.log_tail is not None
    assert "second line" in after_log_growth.log_tail

    # Re-reading at the NEW revision reports unchanged again.
    stable = await registry.status(_EXECUTION_ID, handle, since_revision=after_log_growth.revision, tail_bytes=64)
    assert stable.changed is False
    assert stable.log_tail is None

    # A fake, advancing clock makes the backoff grow deterministically
    # instead of flaking on real wall-clock timing.
    fixed_start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def _fake_clock_factory(offset_seconds: list[float]):
        def _fake_now() -> datetime:
            return fixed_start + timedelta(seconds=offset_seconds[0])

        return _fake_now

    offset = [0.0]
    original_utcnow = background_module._utcnow
    background_module._utcnow = _fake_clock_factory(offset)
    try:
        # Freeze the revision_changed_at instant, then advance the fake
        # clock far past the minimum interval: next_poll_after_ms must grow.
        await registry._record_transition(_EXECUTION_ID, handle, state="finished", outcome="completed")
        current_revision = (await registry.status(_EXECUTION_ID, handle)).revision
        offset[0] = 45.0
        backed_off_unchanged = await registry.status(_EXECUTION_ID, handle, since_revision=current_revision)
        assert backed_off_unchanged.next_poll_after_ms >= 45_000
        assert backed_off_unchanged.next_poll_after_ms <= background_module._MAX_POLL_INTERVAL_MS
    finally:
        background_module._utcnow = original_utcnow


async def test_utf8_tail_truncation_and_large_log_bounded_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A tail cut mid-codepoint still decodes, and a huge log is never read whole."""
    store = ExecutionEvidenceStore(root=tmp_path / "evidence")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    log_dir = store.root / "executions" / _EXECUTION_ID / "background_logs"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "utf8.log"

    # Pad with ASCII, then end on a multi-byte UTF-8 character (3-byte "e2 9c 93",
    # U+2713 CHECK MARK) so a naive byte-count tail would slice through it.
    padding = "x" * 4000
    log_path.write_text(padding + "done ✓\n", encoding="utf-8")

    registry = BackgroundRegistry(store=store, owner_instance_id="owner-A")
    registration = _registration(handle="handle-utf8", worktree=worktree)
    handle = await registry.register(registration)
    await registry._record_transition(_EXECUTION_ID, handle, state="running", log_path=log_path)

    # tail_bytes=3 lands the naive cut point one byte INTO the 3-byte
    # checkmark sequence (0xE2 0x9C 0x93): a byte-blind slice would produce
    # an invalid/half codepoint. The boundary-safe trim must back off past
    # the whole broken character instead of papering over it with U+FFFD.
    status = await registry.status(_EXECUTION_ID, handle, tail_bytes=3)
    assert status.log_tail == "\n"
    assert status.log_truncated is True
    assert "�" not in status.log_tail

    # A log file far larger than the requested tail must never be read in
    # full: patch the whole-file reader out (scoped to THIS file only, so the
    # registry's own small JSON record reads are unaffected) and prove it is
    # never invoked while serving its tail.
    huge_log = log_dir / "huge.log"
    huge_log.write_bytes(b"y" * (2 * 1024 * 1024) + b"tail-marker\n")

    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text

    def _forbid_full_read_bytes(self: Path, *args: object, **kwargs: object) -> bytes:
        if self == huge_log:
            raise AssertionError(f"whole-file read attempted on {self}; tail reads must be bounded")
        return original_read_bytes(self, *args, **kwargs)

    def _forbid_full_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == huge_log:
            raise AssertionError(f"whole-file read attempted on {self}; tail reads must be bounded")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", _forbid_full_read_bytes)
    monkeypatch.setattr(Path, "read_text", _forbid_full_read_text)

    huge_registration = _registration(handle="handle-huge", worktree=worktree)
    huge_handle = await registry.register(huge_registration)
    await registry._record_transition(_EXECUTION_ID, huge_handle, state="running", log_path=huge_log)
    huge_status = await registry.status(_EXECUTION_ID, huge_handle, tail_bytes=32)
    assert huge_status.log_tail is not None
    assert "tail-marker" in huge_status.log_tail
    assert huge_status.log_truncated is True


async def test_native_observation_authority_never_yields_exit_code(tmp_path: Path) -> None:
    """A native-agent handback (host_observation) settles as finished with no exit_code."""
    store = ExecutionEvidenceStore(root=tmp_path / "evidence")
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    registry = BackgroundRegistry(store=store, owner_instance_id="owner-A")
    registration = _registration(
        handle="handle-native", worktree=worktree, kind="native_agent", authority="host_observation"
    )
    handle = await registry.register(registration)

    pending = await registry.status(_EXECUTION_ID, handle)
    assert pending.state == "pending"
    assert pending.authority == "host_observation"
    assert pending.exit_code is None

    await registry._record_transition(_EXECUTION_ID, handle, state="finished", outcome="completed")
    observed = await registry.status(_EXECUTION_ID, handle)
    assert observed.state == "finished"
    assert observed.authority == "host_observation"
    assert observed.exit_code is None
    assert observed.outcome == "completed"


async def test_scope_budget_and_deadline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Foreign handles, unsafe logs and I/O budget overruns are explicit bounded errors."""
    store = ExecutionEvidenceStore(root=tmp_path / "evidence")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    registry = BackgroundRegistry(store=store, owner_instance_id="owner-A")

    registration = _registration(handle="handle-scope", worktree=worktree)
    handle = await registry.register(registration)

    # A handle that was never registered under this execution_id is
    # rejected explicitly -- never silently treated as "unknown" success.
    with pytest.raises(BackgroundNotFoundError):
        await registry.status(str(uuid.uuid4()), handle)
    with pytest.raises(BackgroundNotFoundError):
        await registry.status(_EXECUTION_ID, "handle-that-was-never-registered")

    # Re-registering the SAME handle with a different launch identity (e.g. a
    # reused handle string bound to a new process) is rejected, never
    # silently adopted.
    reused = _registration(handle="handle-scope", worktree=worktree, launch_id="launch-2")
    with pytest.raises(BackgroundConflictError):
        await registry.register(reused)

    # A log_path escaping the durable evidence root is an unsafe log and is
    # rejected with an explicit, bounded error -- never served partially.
    outside_log = tmp_path / "outside.log"
    outside_log.write_text("should never be read", encoding="utf-8")
    with pytest.raises(ValueError):
        await registry._record_transition(_EXECUTION_ID, handle, state="running", log_path=outside_log)

    # A logical MCP job never carries a POSIX exit_code, even when finished.
    mcp_registration = _registration(handle="handle-mcp", worktree=worktree, kind="mcp_job", authority="engine")
    mcp_handle = await registry.register(mcp_registration)
    with pytest.raises(ValueError):
        await registry._record_transition(_EXECUTION_ID, mcp_handle, state="finished", outcome="completed", exit_code=0)
    # Without a POSIX exit_code it settles cleanly as finished.
    await registry._record_transition(_EXECUTION_ID, mcp_handle, state="finished", outcome="completed")
    mcp_status = await registry.status(_EXECUTION_ID, mcp_handle)
    assert mcp_status.exit_code is None
    assert mcp_status.state == "finished"

    # An I/O budget overrun is an explicit bounded error, never a silently
    # returned terminal state.
    monkeypatch.setattr(background_module, "_IO_BUDGET_SECONDS", 0.0)
    with pytest.raises(BackgroundBudgetExceededError):
        await registry.status(_EXECUTION_ID, handle)

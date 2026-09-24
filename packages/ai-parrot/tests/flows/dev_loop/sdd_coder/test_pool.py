"""Tests for the ExecutionPool runtime (FEAT-559 M2)."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from parrot.flows.dev_loop.sdd_coder.models import (
    RosterConfig,
    RosterSeat,
)
from parrot.flows.dev_loop.sdd_coder.pool import ExecutionPool, SeatBusyError
from parrot.knowledge.wiki.ledger.coder_suspensions import (
    CoderSuspensionStore,
    ModelKey,
    SuspensionReceipt,
    SuspensionRecord,
)

EXEC_A = "11111111-1111-4111-8111-111111111111"
EXEC_B = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def mock_suspension_store() -> Mock:
    """A durable suspension store double -- auto-specced, so `.record` is already an AsyncMock."""
    return Mock(spec=CoderSuspensionStore)


@pytest.fixture
def sample_roster() -> RosterConfig:
    """One mcp seat + one native seat -- enough to exercise both identity branches."""
    return RosterConfig(
        seats=[
            RosterSeat(label="qwen", kind="mcp", backend="nova", model="qwen3"),
            RosterSeat(label="haiku", kind="native", model="haiku"),
        ]
    )


@pytest.fixture
def sample_seats(sample_roster: RosterConfig) -> list:
    return list(sample_roster.seats)


def make_pool(
    execution_id: str, roster: RosterConfig, seats: list, store: Mock, initial_exclusions=None
) -> ExecutionPool:
    """Build one pool with sane defaults for these tests."""
    return ExecutionPool(
        execution_id=execution_id,
        feature_id="FEAT-559",
        worktree_path="/test/path",
        roster=roster,
        seats=seats,
        suspension_store=store,
        initial_exclusions=initial_exclusions or [],
    )


def suspension_for(execution_id: str, key: ModelKey, *, attempt_uid: str = "attempt-1") -> SuspensionRecord:
    """One valid timeout incident blocking `key`."""
    occurred_at = datetime.now(timezone.utc)
    return SuspensionRecord(
        execution_id=execution_id,
        feature_id="FEAT-559",
        task_id="TASK-1",
        attempt_uid=attempt_uid,
        source="engine",
        seat_label="qwen",
        backend=key.backend,
        configured_model=key.model,
        blocked_keys=[key],
        reason="timeout",
        occurred_at=occurred_at,
        expires_at=occurred_at + timedelta(seconds=1800),
        duration_s=30.0,
        explanation="Test timeout",
    )


async def test_pool_private_state(mock_suspension_store: Mock, sample_roster: RosterConfig, sample_seats: list) -> None:
    """Different pools share no mutable rotations, caches or exclusions."""
    pool_a = make_pool(EXEC_A, sample_roster, sample_seats, mock_suspension_store)
    pool_b = make_pool(EXEC_B, sample_roster, sample_seats, mock_suspension_store)

    key = ModelKey(backend="nova", model="qwen3")
    record = suspension_for(EXEC_A, key)
    mock_suspension_store.record.return_value = SuspensionReceipt(
        suspension_id="test-suspension",
        execution_id=EXEC_A,
        blocked_keys=[key],
        persisted=True,
        expires_at=record.expires_at,
    )

    await pool_a.suspend(record)

    suspended_a = [s for s in pool_a.view().seats if s.suspended]
    suspended_b = [s for s in pool_b.view().seats if s.suspended]
    assert len(suspended_a) == 1
    assert len(suspended_b) == 0
    # Generation and cached assigner are per-pool, not shared.
    assert pool_a.generation == 1
    assert pool_b.generation == 0


async def test_suspend_first_failure(
    mock_suspension_store: Mock, sample_roster: RosterConfig, sample_seats: list
) -> None:
    """One qualifying incident excludes the model and every label alias immediately."""
    pool = make_pool(EXEC_A, sample_roster, sample_seats, mock_suspension_store)
    key = ModelKey(backend="nova", model="qwen3")
    record = suspension_for(EXEC_A, key)
    mock_suspension_store.record.return_value = SuspensionReceipt(
        suspension_id="test-suspension",
        execution_id=EXEC_A,
        blocked_keys=[key],
        persisted=True,
        expires_at=record.expires_at,
    )

    receipt = await pool.suspend(record)

    assert receipt.suspension_id == "test-suspension"
    assert receipt.persisted is True
    assert receipt.pool_generation == 1

    qwen_seat = next(s for s in pool.view().seats if s.label == "qwen")
    assert qwen_seat.suspended is True
    assert qwen_seat.available is False
    assert qwen_seat.reason == "timeout"

    with pytest.raises(ValueError, match="excluded"):
        await pool.admit("TASK-1", key)


async def test_expiry_is_new_execution_only(
    mock_suspension_store: Mock, sample_roster: RosterConfig, sample_seats: list
) -> None:
    """A pool's inherited exclusions are fixed at construction; expiry is a NEW execution's concern.

    Computing which models are still within cooldown is the durable store's
    job (`CoderSuspensionStore.recent()`, covered in test_suspensions.py);
    here we assert the pool faithfully -- and independently, per instance --
    reflects whatever `initial_exclusions` its caller resolved at begin time.
    """
    key = ModelKey(backend="nova", model="qwen3")
    still_excluded = make_pool(EXEC_A, sample_roster, sample_seats, mock_suspension_store, initial_exclusions=[key])
    no_longer_excluded = make_pool(EXEC_B, sample_roster, sample_seats, mock_suspension_store, initial_exclusions=[])

    old_view = next(s for s in still_excluded.view().seats if s.label == "qwen")
    new_view = next(s for s in no_longer_excluded.view().seats if s.label == "qwen")
    assert old_view.suspended is True
    assert new_view.suspended is False

    with pytest.raises(ValueError, match="excluded"):
        await still_excluded.admit("TASK-1", key)
    attempt_uid = await no_longer_excluded.admit("TASK-1", key)
    assert attempt_uid


async def test_suspension_wakes_retry_waiter(
    mock_suspension_store: Mock, sample_roster: RosterConfig, sample_seats: list
) -> None:
    """A waiter blocked on a busy seat is woken -- and fails fast -- once that seat is suspended."""
    pool = make_pool(EXEC_A, sample_roster, sample_seats, mock_suspension_store)
    key = ModelKey(backend="nova", model="qwen3")

    await pool.admit("TASK-1", key)
    waiter_task = asyncio.create_task(pool.admit("TASK-2", key))
    await asyncio.sleep(0.01)
    assert not waiter_task.done()

    record = suspension_for(EXEC_A, key, attempt_uid="attempt-1")
    mock_suspension_store.record.return_value = SuspensionReceipt(
        suspension_id="test-suspension",
        execution_id=EXEC_A,
        blocked_keys=[key],
        persisted=True,
        expires_at=record.expires_at,
    )
    await pool.suspend(record)

    with pytest.raises(ValueError, match="excluded"):
        await waiter_task


async def test_persistence_failure_is_explicit(
    mock_suspension_store: Mock, sample_roster: RosterConfig, sample_seats: list
) -> None:
    """Local exclusion holds even when the durable append fails; the receipt says so, not silently OK."""
    pool = make_pool(EXEC_A, sample_roster, sample_seats, mock_suspension_store)
    mock_suspension_store.record.side_effect = RuntimeError("Disk full")

    key = ModelKey(backend="nova", model="qwen3")
    record = suspension_for(EXEC_A, key)

    receipt = await pool.suspend(record)

    assert receipt.persisted is False
    assert pool.view().persistence_degraded is True

    with pytest.raises(ValueError, match="excluded"):
        await pool.admit("TASK-1", key)


async def test_suspension_does_not_release_reservation(
    mock_suspension_store: Mock, sample_roster: RosterConfig, sample_seats: list
) -> None:
    """Suspending a busy model does not release its live reservation -- it settles normally."""
    pool = make_pool(EXEC_A, sample_roster, sample_seats, mock_suspension_store)
    key = ModelKey(backend="nova", model="qwen3")

    attempt_uid = await pool.admit("TASK-1", key)
    qwen_seat = next(s for s in pool.view().seats if s.label == "qwen")
    assert qwen_seat.busy is True

    record = suspension_for(EXEC_A, key, attempt_uid="different-attempt")
    mock_suspension_store.record.return_value = SuspensionReceipt(
        suspension_id="test-suspension",
        execution_id=EXEC_A,
        blocked_keys=[key],
        persisted=True,
        expires_at=record.expires_at,
    )
    await pool.suspend(record)

    qwen_seat = next(s for s in pool.view().seats if s.label == "qwen")
    assert qwen_seat.busy is True
    assert qwen_seat.suspended is True

    # The live reservation still settles normally afterwards.
    await pool.release(attempt_uid)
    qwen_seat = next(s for s in pool.view().seats if s.label == "qwen")
    assert qwen_seat.busy is False


async def test_admit_without_wait_fails_fast_on_a_busy_seat(
    mock_suspension_store: Mock, sample_roster: RosterConfig, sample_seats: list
) -> None:
    """`wait=False` reports the busy seat (and who holds it) instead of parking forever.

    Regression for the 2026-09-24 sdd-worker wedge: `coder_prepare_native` for a
    second task on the same native model waited on the condition indefinitely
    because the first task's reservation is only released by `coder_merge`.
    """
    pool = make_pool(EXEC_A, sample_roster, sample_seats, mock_suspension_store)
    key = ModelKey(backend="native", model="haiku")
    holder_uid = await pool.admit("TASK-1", key)

    with pytest.raises(SeatBusyError) as excinfo:
        await pool.admit("TASK-2", key, wait=False)
    assert excinfo.value.key == key
    assert excinfo.value.held_by_task_id == "TASK-1"

    # The default (`wait=True`) contract is unchanged: a waiter parks, then wakes on release.
    waiter = asyncio.create_task(pool.admit("TASK-2", key))
    await asyncio.sleep(0.01)
    assert not waiter.done()
    await pool.release(holder_uid)
    assert await asyncio.wait_for(waiter, timeout=1)
    # Once free, the non-waiting form admits normally too.
    await pool.release(await waiter)
    assert await pool.admit("TASK-3", key, wait=False)


# --- FEAT-599 / issue:bd1c792a5afc: suspension attribution (FEAT-559 AC-12) --------------------


async def test_suspend_sets_seat_attribution(
    mock_suspension_store: Mock, sample_roster: RosterConfig, sample_seats: list
) -> None:
    """After `suspend()`, the blocked seat view names the incident's source, task and execution (AC3)."""
    pool = make_pool(EXEC_A, sample_roster, sample_seats, mock_suspension_store)
    key = ModelKey(backend="nova", model="qwen3")
    record = suspension_for(EXEC_A, key, attempt_uid="att-1")
    mock_suspension_store.record.return_value = SuspensionReceipt(
        suspension_id=record.suspension_id,
        execution_id=EXEC_A,
        blocked_keys=[key],
        persisted=True,
        expires_at=record.expires_at,
    )

    await pool.suspend(record)

    seat = next(view for view in pool.view().seats if view.label == "qwen")
    assert seat.suspended is True
    assert seat.suspension_source == "engine"
    assert seat.source_task_id == "TASK-1"
    assert seat.source_execution_id == EXEC_A
    assert seat.suspension_id == record.suspension_id
    untouched = next(view for view in pool.view().seats if view.label == "haiku")
    assert untouched.source_task_id == "" and untouched.suspension_source == ""


def test_inherited_records_attribute_seats_and_summary(
    mock_suspension_store: Mock, sample_roster: RosterConfig, sample_seats: list
) -> None:
    """Durable-history records passed at construction attribute the inherited seat and render the summary (AC2, AC3)."""
    key = ModelKey(backend="nova", model="qwen3")
    record = suspension_for(EXEC_A, key, attempt_uid="att-0")  # recorded by an EARLIER execution
    pool = ExecutionPool(
        execution_id=EXEC_B,
        feature_id="FEAT-559",
        worktree_path="/test/path",
        roster=sample_roster,
        seats=sample_seats,
        suspension_store=mock_suspension_store,
        initial_exclusions=[key],
        inherited_records=[record],
    )

    view = pool.view()
    seat = next(s for s in view.seats if s.label == "qwen")
    assert seat.suspended is True
    assert seat.reason == "inherited_suspension"  # existing contract preserved
    assert seat.suspension_id == record.suspension_id
    assert seat.suspended_until == record.expires_at.isoformat()
    assert seat.suspension_source == "engine"
    assert seat.source_task_id == "TASK-1"
    assert seat.source_execution_id == EXEC_A
    # AC-12 fields: model, incident id, source task/execution, reason, remaining cooldown
    for needle in (record.suspension_id, "qwen3", "TASK-1", EXEC_A, "timeout", "remaining_cooldown_s="):
        assert needle in view.suspension_summary, needle


def test_view_without_suspensions_has_empty_summary(
    mock_suspension_store: Mock, sample_roster: RosterConfig, sample_seats: list
) -> None:
    """No records → no summary text (never a header-only string)."""
    pool = make_pool(EXEC_A, sample_roster, sample_seats, mock_suspension_store)
    assert pool.view().suspension_summary == ""


# --- FEAT-599 / issue:700660c7f663: public API used by the engine ------------------------------


def test_public_state_accessors(mock_suspension_store: Mock, sample_roster: RosterConfig, sample_seats: list) -> None:
    """The accessors the engine uses instead of reaching into `_status`/`_seats`/`_fallback_*`/`_persistence_degraded`."""
    key = ModelKey(backend="nova", model="qwen3")
    pool = make_pool(EXEC_A, sample_roster, sample_seats, mock_suspension_store)

    assert pool.status == "active"
    seats = pool.seats
    assert [s.label for s in seats] == ["qwen", "haiku"]
    seats.clear()  # a copy: mutating it never touches the pool
    assert [s.label for s in pool.seats] == ["qwen", "haiku"]

    assert pool.resolve_admission("nope") is None
    pool.require_fallback("all_seats_exhausted")
    view = pool.view()
    assert view.fallback_required is True and view.fallback_reason == "all_seats_exhausted"

    assert pool.persistence_degraded is False
    pool.set_persistence_degraded(True)
    assert pool.persistence_degraded is True and pool.view().persistence_degraded is True
    pool.set_persistence_degraded(False)
    assert pool.view().persisted is True

    pool.restore_local_exclusions([key])
    assert key in pool.snapshot().local_exclusions


async def test_resolve_admission_and_mark_exhausted(
    mock_suspension_store: Mock, sample_roster: RosterConfig, sample_seats: list
) -> None:
    """`resolve_admission` mirrors `admit()`/`release()`; `mark_exhausted` flips status and wakes waiters."""
    key = ModelKey(backend="nova", model="qwen3")
    pool = make_pool(EXEC_A, sample_roster, sample_seats, mock_suspension_store)
    uid = await pool.admit("TASK-1", key)
    assert pool.resolve_admission(uid) == ("TASK-1", key)
    await pool.release(uid)
    assert pool.resolve_admission(uid) is None

    await pool.mark_exhausted()
    assert pool.status == "exhausted" and pool.view().status == "exhausted"


async def test_select_free_seat_native_never_waits(
    mock_suspension_store: Mock, sample_roster: RosterConfig, sample_seats: list
) -> None:
    """Native selection returns the free seat, skips tried/ineligible labels, and returns None when only busy."""
    pool = make_pool(EXEC_A, sample_roster, sample_seats, mock_suspension_store)
    native_key = ModelKey(backend="native", model="haiku")

    seat = await pool.select_free_seat(kind="native", tried_seats=set())
    assert seat is not None and seat.label == "haiku"
    assert await pool.select_free_seat(kind="native", tried_seats={"haiku"}) is None
    assert await pool.select_free_seat(kind="native", tried_seats=set(), eligible_labels={"qwen"}) is None

    uid = await pool.admit("TASK-1", native_key)
    assert await pool.select_free_seat(kind="native", tried_seats=set(), wait=False) is None
    await pool.release(uid)
    assert (await pool.select_free_seat(kind="native", tried_seats=set())).label == "haiku"


async def test_select_free_seat_mcp_waits_for_release(
    mock_suspension_store: Mock, sample_roster: RosterConfig, sample_seats: list
) -> None:
    """With wait=True a busy-but-healthy MCP seat is waited for; it is handed out once released."""
    pool = make_pool(EXEC_A, sample_roster, sample_seats, mock_suspension_store)
    key = ModelKey(backend="nova", model="qwen3")
    uid = await pool.admit("TASK-1", key)

    waiter = asyncio.create_task(pool.select_free_seat(kind="mcp", tried_seats=set(), wait=True))
    await asyncio.sleep(0.05)
    assert not waiter.done()

    await pool.release(uid)
    seat = await asyncio.wait_for(waiter, timeout=2)
    assert seat is not None and seat.label == "qwen"


async def test_select_free_seat_returns_none_when_nothing_to_wait_for(
    mock_suspension_store: Mock, sample_roster: RosterConfig, sample_seats: list
) -> None:
    """Suspended/excluded seats are never waited for; a closed pool yields None immediately."""
    pool = make_pool(EXEC_A, sample_roster, sample_seats, mock_suspension_store)
    key = ModelKey(backend="nova", model="qwen3")
    record = suspension_for(EXEC_A, key, attempt_uid="att-9")
    mock_suspension_store.record.return_value = SuspensionReceipt(
        suspension_id=record.suspension_id,
        execution_id=EXEC_A,
        blocked_keys=[key],
        persisted=True,
        expires_at=record.expires_at,
    )
    await pool.suspend(record)
    assert await pool.select_free_seat(kind="mcp", tried_seats=set(), wait=True) is None

    fresh = make_pool(EXEC_B, sample_roster, sample_seats, mock_suspension_store)
    await fresh.close()
    assert await fresh.select_free_seat(kind="mcp", tried_seats=set(), wait=True) is None

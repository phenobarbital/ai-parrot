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

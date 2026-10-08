"""Tests for scheduler run-state stores."""
import uuid
from typing import Any

import pytest

pytest.importorskip("asyncdb")

from parrot.scheduler.models import FireContext, utcnow
from parrot.scheduler.runstate import (
    LAST_RESULT_MAX_CHARS,
    STATUS_LOCK_UNAVAILABLE,
    MemoryRunState,
    PostgresRunState,
    aggregate_delivery_status,
    truncate,
)


class FakeConn:
    """Record statements and return canned rows through asyncdb's fetch API."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch_one(self, sql: str, *args: Any) -> dict[str, Any] | None:
        """Record a call and return its queued row."""
        self.calls.append((sql, args))
        return self.rows.pop(0) if self.rows else None


class FakeAcquire:
    """Implement ``async with await acquire()`` for a fake connection."""

    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    async def __call__(self) -> "FakeAcquire":
        """Return the asynchronous context manager expected by the store."""
        return self

    async def __aenter__(self) -> FakeConn:
        """Yield the fake connection."""
        return self.conn

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Close the fake context without suppressing errors."""
        return None


@pytest.fixture
def fire() -> FireContext:
    """Provide an aware scheduler fire context."""
    return FireContext.for_fire("job-1", utcnow())


def _row(schedule_id: str, **overrides: Any) -> dict[str, Any]:
    """Build a complete service-scheduler row for the fake database."""
    row: dict[str, Any] = {
        "schedule_id": uuid.UUID(schedule_id),
        "enabled": True,
        "last_run": None,
        "next_run": None,
        "run_count": 0,
        "last_status": None,
        "last_error": None,
        "last_error_at": None,
        "last_result": None,
        "last_result_at": None,
        "consecutive_failures": 0,
        "last_delivery_status": None,
        "last_delivery_at": None,
        "last_callbacks": [],
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_memory_threshold_crossed_once(fire: FireContext) -> None:
    """Only the failure that reaches the threshold reports the crossing."""
    store = MemoryRunState()

    results = [await store.stamp_failure("job-1", status="error", error="bad", fire=fire, threshold=3) for _ in range(3)]

    assert [crossed for _, crossed in results] == [False, False, True]
    assert results[-1][0].consecutive_failures == 3
    assert results[-1][0].enabled is False


@pytest.mark.asyncio
async def test_memory_success_resets_counter_and_clears_error(fire: FireContext) -> None:
    """A success clears error data and resets the consecutive failure count."""
    store = MemoryRunState()
    await store.stamp_failure("job-1", status="error", error="bad", fire=fire, threshold=3)

    state = await store.stamp_success("job-1", result_text="done", fire=fire, next_run=None)

    assert state.consecutive_failures == 0
    assert state.last_error is None
    assert state.last_error_at is None
    assert state.last_run is not None and state.last_run.tzinfo is not None


@pytest.mark.asyncio
async def test_lock_unavailable_does_not_count_memory(fire: FireContext) -> None:
    """A coordination failure records status but not an execution attempt."""
    store = MemoryRunState()
    await store.stamp_failure("job-1", status="error", error="bad", fire=fire, threshold=3)

    state, crossed = await store.stamp_failure(
        "job-1", status=STATUS_LOCK_UNAVAILABLE, error="lock", fire=fire, threshold=3
    )

    assert crossed is False
    assert state.consecutive_failures == 1
    assert state.run_count == 1


@pytest.mark.asyncio
async def test_pg_stamp_failure_single_statement_threshold(fire: FireContext) -> None:
    """Postgres derives a threshold crossing from its atomic returning row."""
    schedule_id = str(uuid.uuid4())
    conn = FakeConn([_row(schedule_id, consecutive_failures=3, enabled=False, run_count=3)])
    store = PostgresRunState(FakeAcquire(conn))

    state, crossed = await store.stamp_failure(schedule_id, status="error", error="bad", fire=fire, threshold=3)

    assert crossed is True
    assert state.consecutive_failures == 3
    assert len(conn.calls) == 1
    assert "consecutive_failures = consecutive_failures + 1" in conn.calls[0][0]
    assert conn.calls[0][1][0].tzinfo is not None


@pytest.mark.asyncio
async def test_pg_stamp_success_resets_counter_and_clears_error(fire: FireContext) -> None:
    """A Postgres success transition maps the returned reset state."""
    schedule_id = str(uuid.uuid4())
    conn = FakeConn([_row(schedule_id, consecutive_failures=0, last_error=None, last_error_at=None, run_count=2)])
    store = PostgresRunState(FakeAcquire(conn))

    state = await store.stamp_success(schedule_id, result_text="done", fire=fire, next_run=None)

    assert state.consecutive_failures == 0
    assert state.last_error is None
    assert len(conn.calls) == 1
    assert "last_error = NULL" in conn.calls[0][0]


@pytest.mark.asyncio
async def test_pg_lock_unavailable_uses_lock_sql(fire: FireContext) -> None:
    """Lock-unavailable writes only its status fields in one statement."""
    schedule_id = str(uuid.uuid4())
    conn = FakeConn([_row(schedule_id, consecutive_failures=2, run_count=5, last_status=STATUS_LOCK_UNAVAILABLE)])
    store = PostgresRunState(FakeAcquire(conn))

    state, crossed = await store.stamp_failure(
        schedule_id, status=STATUS_LOCK_UNAVAILABLE, error="lock", fire=fire, threshold=3
    )

    assert crossed is False
    assert state.consecutive_failures == 2
    assert state.run_count == 5
    assert len(conn.calls) == 1
    assert "run_count" not in conn.calls[0][0]


def test_truncate_caps_long_results() -> None:
    """Result and delivery-error text use the scheduler's shared cap."""
    text = "x" * (LAST_RESULT_MAX_CHARS + 1)

    assert truncate(text) == "x" * LAST_RESULT_MAX_CHARS + "…(truncated)"
    assert aggregate_delivery_status([{"status": "sent"}, {"status": "saved"}]) == "ok"

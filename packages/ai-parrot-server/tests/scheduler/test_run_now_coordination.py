"""Cross-worker run-now guard + fail-closed stamp (FEAT-631 TASK-4065)."""

from __future__ import annotations

import inspect
import re
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.scheduler import jobs
from parrot.scheduler import manager as manager_module
from parrot.scheduler.coordination import FireCoordinationError, RedisFireCoordinator
from parrot.scheduler.manager import AgentSchedulerManager, SchedulerRunNowConflictError


class FakeRedis:
    """Dict-backed async double for SET NX EX and DELETE."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool | None:
        """Set ``key`` unless an NX request finds an existing key."""
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key: str) -> None:
        """Remove a stored key."""
        self.store.pop(key, None)


class _FakePoolAcquireCtx:
    """Async context manager for a fake database connection."""

    def __init__(self) -> None:
        self.conn = MagicMock()

    async def __aenter__(self) -> MagicMock:
        """Return the fake connection."""
        return self.conn

    async def __aexit__(self, *_args: object) -> bool:
        """Do not suppress errors."""
        return False


class _FakePool:
    """Pool double matching the manager's acquire contract."""

    async def acquire(self) -> _FakePoolAcquireCtx:
        """Return a fake connection context."""
        return _FakePoolAcquireCtx()


def _manager() -> AgentSchedulerManager:
    """Create a manager with a unique process-local trampoline name."""
    return AgentSchedulerManager(registered_name=f"run-now-test-{uuid.uuid4()}")


def _schedule(*, enabled: bool = True) -> SimpleNamespace:
    """Build the minimum AgentSchedule-shaped object used by run-now."""
    return SimpleNamespace(agent_name="agent", scheduler_type="default", enabled=enabled)


@pytest.mark.asyncio
async def test_run_now_conflict_across_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Redis run-now guard rejects the same schedule on another manager."""
    redis = FakeRedis()
    first = _manager()
    second = _manager()
    first._fire_coordinator = RedisFireCoordinator(redis, worker_id="first")
    second._fire_coordinator = RedisFireCoordinator(redis, worker_id="second")
    schedule = _schedule()
    monkeypatch.setattr(first, "get_schedule", AsyncMock(return_value=schedule))
    monkeypatch.setattr(second, "get_schedule", AsyncMock(return_value=schedule))

    await first.run_schedule_now("shared")
    with pytest.raises(SchedulerRunNowConflictError):
        await second.run_schedule_now("shared")


@pytest.mark.asyncio
async def test_run_now_guard_released_after_completion_and_failure() -> None:
    """The trampoline releases the guard after both success and failure."""
    manager = _manager()
    manager._run_db_schedule = AsyncMock(return_value="done")
    assert await manager._fire_coordinator.try_acquire_running("success")
    assert await jobs.run_db_schedule_now(manager.registered_name, "success") == "done"
    assert await manager._fire_coordinator.try_acquire_running("success")

    manager._run_db_schedule = AsyncMock(side_effect=RuntimeError("boom"))
    assert await manager._fire_coordinator.try_acquire_running("failure")
    with pytest.raises(RuntimeError, match="boom"):
        await jobs.run_db_schedule_now(manager.registered_name, "failure")
    assert await manager._fire_coordinator.try_acquire_running("failure")


@pytest.mark.asyncio
async def test_run_now_paused_schedule_still_runs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A paused schedule is submitted as a one-shot without enabling it."""
    manager = _manager()
    schedule = _schedule(enabled=False)
    monkeypatch.setattr(manager, "get_schedule", AsyncMock(return_value=schedule))

    assert await manager.run_schedule_now("paused") is schedule
    assert schedule.enabled is False
    job = manager.scheduler.get_job("run_now:paused")
    assert job is not None
    assert job.func is jobs.run_db_schedule_now


@pytest.mark.asyncio
async def test_unavailable_stamps_lock_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unavailable coordination leaves run counters untouched while stamping metadata."""
    manager = _manager()
    manager._pool = _FakePool()
    schedule = SimpleNamespace(metadata={}, run_count=7, last_run=None, update=AsyncMock())
    monkeypatch.setattr(manager_module.AgentSchedule, "get", AsyncMock(return_value=schedule))

    await manager._on_coordination_unavailable("schedule-id", ConnectionError("redis down"))

    assert schedule.metadata["last_status"] == "lock_unavailable"
    assert schedule.metadata["last_error"] == "coordination unavailable: redis down"
    assert schedule.run_count == 7
    assert schedule.last_run is None
    schedule.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_unavailable_ignores_auto_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decorator jobs have no AgentSchedule row to stamp."""
    manager = _manager()
    manager._pool = _FakePool()
    get = AsyncMock()
    monkeypatch.setattr(manager_module.AgentSchedule, "get", get)

    await manager._on_coordination_unavailable("auto_bot_method", FireCoordinationError("redis down"))

    get.assert_not_awaited()


def test_no_bound_method_add_job() -> None:
    """Manager add_job calls never serialize a bound manager coroutine."""
    source = inspect.getsource(manager_module)
    assert not re.search(r"add_job\(\s*\n\s*self\._", source)

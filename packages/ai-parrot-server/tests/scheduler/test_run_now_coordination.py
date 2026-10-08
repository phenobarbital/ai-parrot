"""Cross-worker run-now coordination tests for the scheduler base API."""

from __future__ import annotations

import inspect
import re
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.scheduler import jobs
from parrot.scheduler import manager as manager_module
from parrot.scheduler.coordination import RedisFireCoordinator
from parrot.scheduler.manager import AgentSchedulerManager
from parrot.scheduler.models import JobDefinition
from parrot.scheduler.runstate import MemoryRunState


class FakeRedis:
    """Dict-backed asynchronous Redis double."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


def _manager() -> AgentSchedulerManager:
    return AgentSchedulerManager(registered_name=f"run-now-test-{uuid.uuid4()}")


def _definition() -> JobDefinition:
    return JobDefinition(schedule_id=str(uuid.uuid4()), backend="db", target_kind="agent", target_name="agent", prompt="run", schedule_type="interval", schedule_config={"minutes": 5})


@pytest.mark.asyncio
async def test_run_now_conflict_across_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    first, second = _manager(), _manager()
    first._fire_coordinator = RedisFireCoordinator(redis, worker_id="first")
    second._fire_coordinator = RedisFireCoordinator(redis, worker_id="second")
    definition = _definition()
    stored = SimpleNamespace(_jobstore_alias="default", enabled=True)
    monkeypatch.setattr(first, "_locate", AsyncMock(return_value=("db", definition, stored)))
    monkeypatch.setattr(second, "_locate", AsyncMock(return_value=("db", definition, stored)))
    await first.run_schedule_now(definition.schedule_id)
    with pytest.raises(manager_module.SchedulerRunNowConflictError):
        await second.run_schedule_now(definition.schedule_id)


@pytest.mark.asyncio
async def test_run_now_guard_released_after_completion_and_failure() -> None:
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
async def test_unavailable_stamps_run_state(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager()
    state = MemoryRunState("db")
    monkeypatch.setattr(manager, "_run_state_for", lambda _backend: state)
    schedule_id = str(uuid.uuid4())
    await manager._on_coordination_unavailable(schedule_id, ConnectionError("redis down"))
    result = await state.read(schedule_id)
    assert result is not None
    assert result.last_status == "lock_unavailable"
    assert result.last_error == "coordination unavailable: redis down"
    assert result.run_count == 0


@pytest.mark.asyncio
async def test_unavailable_ignores_non_schedule_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager()
    state = MemoryRunState("db")
    monkeypatch.setattr(manager, "_run_state_for", lambda _backend: state)
    await manager._on_coordination_unavailable("auto_bot_method", ConnectionError("redis down"))
    assert await state.read("auto_bot_method") is None


def test_no_bound_method_add_job() -> None:
    source = inspect.getsource(manager_module)
    assert not re.search(r"add_job\(\s*\n\s*self\._", source)

"""FEAT-644 Redis backend integration tests (real Redis, db 15)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from parrot.scheduler import SchedulerManager
from parrot.scheduler.coordination import manager_prefix
from parrot.scheduler.models import FireContext, utcnow


class Service:
    """Target that records fires and optionally fails."""

    def __init__(self, *, fails: bool = False) -> None:
        self.calls: list[object] = []
        self.fails = fails

    async def run(self, scheduled_at: object | None = None) -> str:
        """Record a fire, or raise the configured deterministic failure."""
        self.calls.append(scheduled_at)
        if self.fails:
            raise RuntimeError("boom")
        return "ok"


@pytest.fixture
def redis_db_15(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point SCHEDULER_REDIS_DB at 15 for the manager under test."""
    original_get = __import__("navconfig").config.get

    def get_setting(key: str, *args: object, **kwargs: object) -> object:
        """Return the scheduler test database while preserving other settings."""
        if key == "SCHEDULER_REDIS_DB":
            return "15"
        return original_get(key, *args, **kwargs)

    monkeypatch.setattr("navconfig.config.get", get_setting)


async def _manager(name: str, target: Service) -> SchedulerManager:
    """Start one isolated real-Redis scheduler manager with its target registered."""
    manager = SchedulerManager(registered_name=name)
    manager.register_target("service", target, methods=["run"])
    await manager.start_headless(use_redis=True, register_listeners=True)
    return manager


async def test_redis_job_survives_restart(scheduler_namespace, scheduler_redis, redis_db_15) -> None:
    """A Redis-only job is listed and remains executable after manager replacement."""
    first = await _manager(scheduler_namespace, Service())
    definition = await first.add_schedule(
        "service", "service", "interval", {"minutes": 5}, backend="redis", method_name="run"
    )
    await first.stop_headless(wait=False)

    target = Service()
    second = await _manager(scheduler_namespace, target)
    try:
        assert [item.schedule_id for item in await second.list_schedules()] == [definition.schedule_id]
        result = await second._run_redis_job(definition.schedule_id)
        await second._process_job_success(
            definition,
            FireContext.for_fire(definition.schedule_id, utcnow()),
            result,
            None,
        )
        state = await second.get_last_result(definition.schedule_id)
        assert target.calls and state.run_count == 1
    finally:
        await second.stop_headless(wait=False)


async def test_redis_job_catchup_once_after_outage(scheduler_namespace, scheduler_redis, redis_db_15) -> None:
    """A no-grace job catches up once, while a stale grace-limited job is not fired."""
    first = await _manager(scheduler_namespace, Service())
    catchup = await first.add_schedule(
        "service", "service", "interval", {"seconds": 1}, backend="redis", method_name="run", misfire_grace_time=None
    )
    skipped = await first.add_schedule(
        "service", "service", "interval", {"seconds": 1}, backend="redis", method_name="run", misfire_grace_time=600
    )
    first.scheduler.modify_job(catchup.schedule_id, jobstore="redis", next_run_time=utcnow() - timedelta(seconds=2))
    first.scheduler.modify_job(skipped.schedule_id, jobstore="redis", next_run_time=utcnow() - timedelta(hours=2))
    await first.stop_headless(wait=False)

    target = Service()
    second = await _manager(scheduler_namespace, target)
    try:
        await asyncio.sleep(0.2)
        assert len(target.calls) == 1
        state = await second.get_last_result(catchup.schedule_id)
        assert state.run_count == 1
        assert (await second.get_last_result(skipped.schedule_id)).run_count == 0
    finally:
        await second.stop_headless(wait=False)


async def test_jobstore_and_coordinator_keys_namespaced(scheduler_namespace, scheduler_redis, redis_db_15) -> None:
    """Jobstore, coordination, and run-state keys share the manager-specific prefix."""
    manager = await _manager(scheduler_namespace, Service())
    try:
        prefix = manager_prefix(scheduler_namespace)
        store = manager.scheduler._jobstores["redis"]
        assert store.jobs_key == f"{prefix}jobs"
        assert store.run_times_key == f"{prefix}run_times"
        assert manager._fire_coordinator._prefix == prefix
        assert manager._run_state_for("redis")._prefix == f"{prefix}runstate:"
    finally:
        await manager.stop_headless(wait=False)


async def test_multiworker_threshold_race(scheduler_namespace, scheduler_redis, redis_db_15) -> None:
    """Two managers crossing a Redis failure threshold emit one disable alert."""
    first = await _manager(scheduler_namespace, Service(fails=True))
    definition = await first.add_schedule(
        "service", "service", "interval", {"minutes": 5}, backend="redis", method_name="run"
    )
    second = await _manager(scheduler_namespace, Service(fails=True))
    alert = AsyncMock()
    first._alert_disabled = alert  # type: ignore[method-assign]
    second._alert_disabled = alert  # type: ignore[method-assign]
    try:
        for manager in (first, second, first):
            with pytest.raises(RuntimeError, match="boom"):
                await manager._run_redis_job(definition.schedule_id)
        assert alert.await_count == 1
        assert (await first.get_last_result(definition.schedule_id)).enabled is False
    finally:
        await second.stop_headless(wait=False)
        await first.stop_headless(wait=False)


async def test_headless_startup_order(scheduler_namespace, scheduler_redis, redis_db_15) -> None:
    """Headless Redis startup attaches storage before exposing a running scheduler."""
    manager = SchedulerManager(registered_name=scheduler_namespace)
    try:
        await manager.start_headless(use_redis=True, register_listeners=False)
        assert manager.scheduler.running
        assert manager.redis_available
        assert manager._redis_client is not None
        assert manager._fire_coordinator._prefix == manager_prefix(scheduler_namespace)
    finally:
        await manager.stop_headless(wait=False)

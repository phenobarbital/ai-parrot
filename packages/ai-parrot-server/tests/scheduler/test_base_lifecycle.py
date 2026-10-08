"""Lifecycle coverage for the target-agnostic ``SchedulerManager``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from aiohttp import web

from parrot.scheduler import jobs
from parrot.scheduler.base import SchedulerManager, SchedulerUnavailableError
from parrot.scheduler.coordination import RedisFireCoordinator, manager_prefix
from parrot.scheduler.runstate import MemoryRunState, PostgresRunState, RedisRunState

pytestmark = pytest.mark.requires_apscheduler


@pytest.fixture
async def manager(scheduler_namespace: str):
    """Build and reliably unregister one isolated manager."""
    instance = SchedulerManager(registered_name=scheduler_namespace)
    yield instance
    await instance.stop_headless(wait=False)


async def test_init_registers_manager_and_service_resolver(manager: SchedulerManager, scheduler_namespace: str) -> None:
    """Construction registers the manager and the default service resolver."""
    assert jobs.get_manager(scheduler_namespace) is manager
    assert manager._resolvers["service"].kind == "service"
    assert manager.targets.get("missing") is None


async def test_redis_jobstore_keys_namespaced(
    manager: SchedulerManager,
    scheduler_namespace: str,
    scheduler_redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Redis jobstore uses only the manager's isolated prefix and configured DB."""
    monkeypatch.setattr("navconfig.config.get", lambda key: 15 if key == "SCHEDULER_REDIS_DB" else None)
    await manager.start_headless(use_redis=True, register_listeners=False)

    store = manager.scheduler._jobstores["redis"]
    prefix = manager_prefix(scheduler_namespace)
    assert store.jobs_key == f"{prefix}jobs"
    assert store.run_times_key == f"{prefix}run_times"
    assert store.redis.connection_pool.connection_kwargs["db"] == 15


async def test_coordinator_forced_redis_with_jobstore(
    manager: SchedulerManager,
    scheduler_namespace: str,
    scheduler_redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Redis jobstore forces a namespaced Redis fire coordinator."""
    monkeypatch.setattr("navconfig.config.get", lambda key: 15 if key == "SCHEDULER_REDIS_DB" else "none")
    await manager.start_headless(use_redis=True, register_listeners=False, coordination="none")

    assert isinstance(manager._fire_coordinator, RedisFireCoordinator)
    assert manager._fire_coordinator._prefix == manager_prefix(scheduler_namespace)


async def test_run_state_for_backends(
    manager: SchedulerManager,
    scheduler_redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run-state routing requires live backing resources and preserves code memory."""
    with pytest.raises(SchedulerUnavailableError):
        manager._run_state_for("redis")
    with pytest.raises(SchedulerUnavailableError):
        manager._run_state_for("db")

    manager._pool = MagicMock()
    assert isinstance(manager._run_state_for("db"), PostgresRunState)
    assert isinstance(manager._run_state_for("code"), MemoryRunState)

    monkeypatch.setattr("navconfig.config.get", lambda key: 15 if key == "SCHEDULER_REDIS_DB" else None)
    await manager.start_headless(use_redis=True, register_listeners=False)
    assert isinstance(manager._run_state_for("redis"), RedisRunState)


async def test_stop_headless_tolerates_no_start(manager: SchedulerManager, scheduler_namespace: str) -> None:
    """Stopping an unstarted manager is safe and removes its jobs registry entry."""
    await manager.stop_headless()
    with pytest.raises(LookupError):
        jobs.get_manager(scheduler_namespace)


def test_setup_registers_routes(manager: SchedulerManager, scheduler_namespace: str) -> None:
    """The base setup preserves all five legacy scheduler route registrations."""
    app = web.Application()
    manager.setup(app)

    routes = {route.resource.canonical for route in app.router.routes()}
    assert app[scheduler_namespace] is manager
    assert {
        "/api/v1/parrot/scheduler/schedules",
        "/api/v1/parrot/scheduler/schedules/{schedule_id}",
        "/api/v1/parrot/scheduler/schedules/{schedule_id}/last-result",
        "/api/v1/parrot/scheduler/callbacks",
        "/api/v1/parrot/scheduler/restart",
    } <= routes

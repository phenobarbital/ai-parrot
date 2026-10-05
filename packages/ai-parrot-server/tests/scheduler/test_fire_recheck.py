"""Fire-time re-check and trampoline wiring tests (FEAT-631 TASK-4064)."""

import pickle
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from asyncdb.exceptions import NoDataFound
from parrot.scheduler import jobs
from parrot.scheduler.coordination import NullFireCoordinator
from parrot.scheduler.manager import AgentSchedulerManager, ScheduleType, schedule, schedule_fingerprint
from parrot.scheduler.sanitize import SchedulerConfigError

pytestmark = pytest.mark.requires_apscheduler


def _schedule(**overrides):
    """Build a schedule-shaped row without a database dependency."""
    values = {
        "schedule_id": "schedule-1",
        "agent_name": "agent",
        "prompt": "old",
        "method_name": None,
        "metadata": {},
        "is_crew": False,
        "send_result": {},
        "callbacks": [],
        "scheduler_type": "default",
        "schedule_type": "interval",
        "schedule_config": {"seconds": 60},
        "enabled": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
async def manager():
    """Return a started in-memory manager with an explicit stable registry name."""
    value = AgentSchedulerManager(registered_name="recheck_mgr")
    await value.start_headless(coordination="none")
    yield value
    await value.stop_headless(wait=False)


def test_schedule_fingerprint_is_deterministic():
    """Equivalent trigger rows produce the same placement fingerprint."""
    assert schedule_fingerprint(_schedule()) == schedule_fingerprint(_schedule())


def test_trampoline_job_is_picklable(manager):
    """Persisted DB jobs refer to the module trampoline, never the manager."""
    row = _schedule()
    job = manager.scheduler.add_job(
        jobs.run_db_schedule,
        "interval",
        seconds=60,
        id=row.schedule_id,
        kwargs=manager._job_kwargs_from_schedule(row),
    )

    assert job.func_ref == "parrot.scheduler.jobs:run_db_schedule"
    pickle.dumps(job.__getstate__())


async def test_fire_skips_deleted_row(manager, monkeypatch):
    """A deleted DB row removes its local job without executing it."""
    row = _schedule()
    manager.scheduler.add_job(
        jobs.run_db_schedule,
        "interval",
        seconds=60,
        id=row.schedule_id,
        kwargs=manager._job_kwargs_from_schedule(row),
    )
    monkeypatch.setattr(manager, "get_schedule", AsyncMock(side_effect=NoDataFound()))
    execute = AsyncMock()
    monkeypatch.setattr(manager, "_execute_agent_job", execute)

    assert await manager._run_db_schedule(row.schedule_id, "fingerprint") is jobs.SKIPPED
    assert manager.scheduler.get_job(row.schedule_id) is None
    execute.assert_not_awaited()


async def test_fire_skips_disabled_row(manager, monkeypatch):
    """A disabled row removes its local job without executing it."""
    row = _schedule(enabled=False)
    manager.scheduler.add_job(
        jobs.run_db_schedule,
        "interval",
        seconds=60,
        id=row.schedule_id,
        kwargs=manager._job_kwargs_from_schedule(row),
    )
    monkeypatch.setattr(manager, "get_schedule", AsyncMock(return_value=row))

    assert await manager._run_db_schedule(row.schedule_id, "fingerprint") is jobs.SKIPPED
    assert manager.scheduler.get_job(row.schedule_id) is None


async def test_fire_reschedules_on_fingerprint_change(manager, monkeypatch):
    """A stale placement is rescheduled and does not execute on that fire."""
    row = _schedule()
    manager.scheduler.add_job(
        jobs.run_db_schedule,
        "interval",
        seconds=60,
        id=row.schedule_id,
        kwargs=manager._job_kwargs_from_schedule(row),
    )
    reschedule = MagicMock()
    monkeypatch.setattr(manager.scheduler, "reschedule_job", reschedule)
    monkeypatch.setattr(manager, "get_schedule", AsyncMock(return_value=row))

    assert await manager._run_db_schedule(row.schedule_id, "stale") is jobs.SKIPPED
    reschedule.assert_called_once()


async def test_fire_uses_row_fields_and_local_callback(manager, monkeypatch):
    """Execution receives fresh row values and its process-local callback."""
    row = _schedule(prompt="new")
    callback = object()
    manager._local_callbacks[row.schedule_id] = callback
    monkeypatch.setattr(manager, "get_schedule", AsyncMock(return_value=row))
    execute = AsyncMock(return_value="done")
    monkeypatch.setattr(manager, "_execute_agent_job", execute)

    assert await manager._run_db_schedule(row.schedule_id, schedule_fingerprint(row)) == "done"
    execute.assert_awaited_once_with(**manager._execution_fields(row), success_callback=callback)


async def test_auto_task_routes_through_trampoline(manager):
    """Decorator schedules use the module-level auto-task trampoline."""

    class Bot:
        name = "bot"

        @schedule(ScheduleType.INTERVAL, seconds=60)
        async def tick(self):
            return None

    assert manager.register_bot_schedules(Bot()) == 1
    job = manager.scheduler.get_job("auto_bot_tick")
    assert job.func is jobs.run_auto_schedule


async def test_no_bound_method_jobs(manager):
    """All persisted jobs point to scheduler.jobs functions."""
    row = _schedule()
    manager.scheduler.add_job(
        jobs.run_db_schedule,
        "interval",
        seconds=60,
        id=row.schedule_id,
        kwargs=manager._job_kwargs_from_schedule(row),
    )

    class Bot:
        name = "bot"

        @schedule(ScheduleType.INTERVAL, seconds=60)
        async def tick(self):
            return None

    manager.register_bot_schedules(Bot())
    assert all(job.func.__module__ == "parrot.scheduler.jobs" for job in manager.scheduler.get_jobs())


async def test_start_headless_installs_coordinator_and_rejects_unknown_mode(manager):
    """Headless startup replaces the executor coordinator and validates modes."""
    executor = manager.scheduler._lookup_executor("default")
    assert isinstance(executor._coordinator, NullFireCoordinator)

    other = AgentSchedulerManager(registered_name="invalid_recheck_mgr")
    with pytest.raises(SchedulerConfigError):
        await other.start_headless(coordination="bogus")
    await other.stop_headless(wait=False)

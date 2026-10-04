"""Tests for parrot.scheduler.jobs (FEAT-631 TASK-4061)."""

import pickle
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from apscheduler.util import obj_to_ref

from parrot.scheduler import jobs


@pytest.fixture
def stub_manager():
    """Register an isolated async manager stub for trampoline tests."""
    manager = SimpleNamespace(
        registered_name="test_jobs_mgr",
        _run_db_schedule=AsyncMock(return_value="ok"),
        _run_auto_task=AsyncMock(return_value="auto"),
        _fire_coordinator=SimpleNamespace(release_running=AsyncMock()),
    )
    jobs.register_manager(manager)
    yield manager
    jobs.unregister_manager("test_jobs_mgr")


def test_textual_refs():
    """Each trampoline has the stable persisted APScheduler reference."""
    assert obj_to_ref(jobs.run_db_schedule) == "parrot.scheduler.jobs:run_db_schedule"
    assert obj_to_ref(jobs.run_db_schedule_now) == "parrot.scheduler.jobs:run_db_schedule_now"
    assert obj_to_ref(jobs.run_auto_schedule) == "parrot.scheduler.jobs:run_auto_schedule"


def test_skipped_is_singleton_and_picklable_kwargs():
    """The sentinel is stable and persisted trampoline kwargs are picklable."""
    assert jobs.SKIPPED is jobs.SKIPPED
    assert pickle.dumps({"manager_name": "m", "schedule_id": "s", "fingerprint": "f"})


def test_get_manager_unknown_raises():
    """Unknown process-local manager names fail with a descriptive error."""
    with pytest.raises(LookupError, match="missing-manager"):
        jobs.get_manager("missing-manager")


async def test_run_db_schedule_delegates(stub_manager):
    """The DB trampoline delegates schedule id and fingerprint unchanged."""
    result = await jobs.run_db_schedule("test_jobs_mgr", "sid", "fp")

    assert result == "ok"
    stub_manager._run_db_schedule.assert_awaited_once_with("sid", "fp")


async def test_run_db_schedule_now_releases_on_success_and_failure(stub_manager):
    """The run-now guard is released regardless of delegate outcome."""
    result = await jobs.run_db_schedule_now("test_jobs_mgr", "sid")

    assert result == "ok"
    stub_manager._run_db_schedule.assert_awaited_once_with("sid", None, run_now=True)
    stub_manager._fire_coordinator.release_running.assert_awaited_once_with("sid")

    stub_manager._run_db_schedule.reset_mock()
    stub_manager._fire_coordinator.release_running.reset_mock()
    stub_manager._run_db_schedule.side_effect = RuntimeError("delegate failed")

    with pytest.raises(RuntimeError, match="delegate failed"):
        await jobs.run_db_schedule_now("test_jobs_mgr", "sid")

    stub_manager._run_db_schedule.assert_awaited_once_with("sid", None, run_now=True)
    stub_manager._fire_coordinator.release_running.assert_awaited_once_with("sid")


async def test_run_auto_schedule_delegates(stub_manager):
    """The auto-job trampoline delegates its stable job id unchanged."""
    result = await jobs.run_auto_schedule("test_jobs_mgr", "auto_bot_method")

    assert result == "auto"
    stub_manager._run_auto_task.assert_awaited_once_with("auto_bot_method")

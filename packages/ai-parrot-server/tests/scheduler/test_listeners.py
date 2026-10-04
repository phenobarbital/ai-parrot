"""Listener behaviour on the aiohttp path (FEAT-631 TASK-4063)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from parrot.scheduler import jobs
from parrot.scheduler.manager import AgentSchedulerManager


@pytest.fixture
def manager():
    """Provide a scheduler manager without starting external infrastructure."""
    return AgentSchedulerManager()


def test_job_status_tolerates_missing_job(manager):
    """A job error event may arrive after APScheduler removed its job."""
    manager.scheduler.get_job = MagicMock(return_value=None)
    event = SimpleNamespace(
        job_id="gone",
        code=EVENT_JOB_ERROR,
        scheduled_run_time=None,
        traceback=None,
        exception=RuntimeError("x"),
    )

    manager.job_status(event)


def test_job_success_ignores_skipped(manager):
    """An intentionally skipped execution does not schedule success processing."""
    manager.scheduler.get_job = MagicMock(return_value=SimpleNamespace(name="n", kwargs={"schedule_id": "s1"}))
    manager._job_context["s1"] = {"agent_name": "agent"}
    event = SimpleNamespace(
        job_id="job-1",
        code=EVENT_JOB_EXECUTED,
        scheduled_run_time=None,
        retval=jobs.SKIPPED,
    )

    with patch.object(manager, "_process_job_success", new=AsyncMock()) as process_success:
        assert manager.job_success(event) is True

    process_success.assert_not_called()
    assert "s1" not in manager._job_context


class _FakePoolAcquireContext:
    """Minimal async acquire context compatible with AsyncDB pools."""

    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return False


class _FakePool:
    """Minimal pool accepted by ``_update_schedule_run``."""

    def __init__(self):
        self.connection = MagicMock()

    async def acquire(self):
        return _FakePoolAcquireContext(self.connection)


async def test_success_stamps_next_run(manager):
    """A completed execution persists the local scheduler's next run time."""
    next_run = object()
    schedule = SimpleNamespace(
        last_run=None,
        run_count=0,
        next_run=None,
        metadata={},
        update=AsyncMock(),
    )
    manager._pool = _FakePool()
    manager.scheduler.get_job = MagicMock(return_value=SimpleNamespace(next_run_time=next_run))

    with patch("parrot.scheduler.manager.AgentSchedule.get", new=AsyncMock(return_value=schedule)):
        await manager._update_schedule_run("schedule-1", success=True)

    assert schedule.next_run is next_run
    schedule.update.assert_awaited_once()


def test_scheduler_status_does_not_print(manager, capsys):
    """Scheduler status events are logged rather than written to stdout."""
    manager.scheduler_status(SimpleNamespace())

    assert capsys.readouterr().out == ""

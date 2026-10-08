"""Listener behaviour on the aiohttp path (FEAT-631 TASK-4063)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from parrot.scheduler import jobs
from parrot.scheduler.manager import AgentSchedulerManager
from parrot.scheduler.models import FireContext, JobDefinition
from parrot.scheduler.runstate import MemoryRunState


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
    manager._job_context["s1"] = {
        "definition": JobDefinition(
            schedule_id="s1",
            backend="db",
            target_kind="agent",
            target_name="agent",
            method_name="chat",
            schedule_type="interval",
            schedule_config={"seconds": 60},
        ),
        "fire": FireContext.for_fire("s1", datetime.now(UTC)),
    }
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


async def test_success_stamps_next_run(manager):
    """A completed execution stamps the dedicated run-state store."""
    next_run = object()
    definition = JobDefinition(
        schedule_id="schedule-1",
        backend="db",
        target_kind="agent",
        target_name="agent",
        method_name="chat",
        schedule_type="interval",
        schedule_config={"seconds": 60},
    )
    store = MemoryRunState(backend="db")
    manager._run_state_for = lambda _backend: store  # type: ignore[method-assign]
    manager.scheduler.get_job = MagicMock(return_value=SimpleNamespace(next_run_time=next_run))

    await manager._process_job_success(
        definition,
        FireContext.for_fire("schedule-1", datetime.now(UTC)),
        "done",
        None,
    )

    state = await store.read("schedule-1")
    assert state is not None
    assert state.next_run is next_run


def test_scheduler_status_does_not_print(manager, capsys):
    """Scheduler status events are logged rather than written to stdout."""
    manager.scheduler_status(SimpleNamespace())

    assert capsys.readouterr().out == ""

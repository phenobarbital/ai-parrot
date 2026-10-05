"""FEAT-635 M2 — the manager isolates callbacks and persists delivery outcomes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.scheduler.manager import AgentSchedulerManager


@pytest.fixture
def manager():
    """Scheduler manager without external infrastructure."""
    return AgentSchedulerManager()


class _FakePoolAcquireContext:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return False


class _FakePool:
    def __init__(self):
        self.connection = MagicMock()

    async def acquire(self):
        return _FakePoolAcquireContext(self.connection)


def _cb(response=None, exc=None):
    """Return a fake callback instance."""
    return AsyncMock(return_value=response, side_effect=exc)


async def test_handle_job_success_isolates_callbacks(manager):
    builds = [_cb(exc=RuntimeError("boom")), _cb(response={"status": "sent"})]
    with (
        patch("parrot.scheduler.manager.build_scheduler_callback", side_effect=builds),
        patch.object(manager, "_send_result_email", new=AsyncMock(return_value={"status": "success"})) as send_result,
    ):
        outcomes = await manager._handle_job_success(
            "s1",
            "agent",
            "res",
            None,
            {"recipients": ["a@x"]},
            [{"type": "send_email_report"}, {"type": "send_notify_report"}],
        )
    assert [outcome["status"] for outcome in outcomes] == ["failed", "sent", "sent"]
    assert outcomes[2]["callback"] == "send_result"
    send_result.assert_awaited_once()


async def test_handle_job_success_unknown_callback_type(manager):
    outcomes = await manager._handle_job_success("s1", "agent", "res", None, None, [{"type": "nope"}])
    assert outcomes == [{"callback": "nope", "status": "failed", "error": "Unsupported scheduler callback: nope"}]


async def test_send_result_failure_recorded(manager):
    with patch.object(manager, "_send_result_email", new=AsyncMock(return_value={"status": "error", "error": "x"})):
        outcomes = await manager._handle_job_success("s1", "agent", "res", None, {"recipients": ["a@x"]})
    assert outcomes == [{"callback": "send_result", "status": "failed", "error": "x"}]


@pytest.mark.parametrize(
    "statuses,expected",
    [
        (["sent", "saved"], "ok"),
        (["sent", "failed"], "partial"),
        (["partial"], "partial"),
        (["failed", "failed"], "failed"),
        ([], None),
    ],
)
def test_aggregate_delivery_status(statuses, expected):
    outcomes = [{"callback": "c", "status": status, "error": None} for status in statuses]
    assert AgentSchedulerManager._aggregate_delivery_status(outcomes) == expected


async def test_process_job_success_stamps_delivery(manager):
    manager._pool = _FakePool()
    schedule = SimpleNamespace(metadata={"last_status": "success"}, update=AsyncMock())
    outcomes = [{"callback": "c", "status": "failed", "error": "x"}]
    with (
        patch("parrot.scheduler.manager.AgentSchedule.get", new=AsyncMock(return_value=schedule)),
        patch.object(manager, "_update_schedule_run", new=AsyncMock()),
        patch.object(manager, "_handle_job_success", new=AsyncMock(return_value=outcomes)),
    ):
        await manager._process_job_success("s1", "agent", "res", None, None, [], persist=True)
    assert schedule.metadata["last_callbacks"] == outcomes
    assert schedule.metadata["last_delivery_status"] == "failed"
    assert schedule.metadata["last_delivery_time"]
    assert schedule.metadata["last_status"] == "success"
    schedule.update.assert_awaited_once()


async def test_process_job_success_persist_false_skips_stamp(manager):
    stamp = AsyncMock()
    outcomes = [{"callback": "c", "status": "sent", "error": None}]
    with (
        patch.object(manager, "_handle_job_success", new=AsyncMock(return_value=outcomes)),
        patch.object(manager, "_stamp_delivery_outcome", new=stamp),
    ):
        await manager._process_job_success("s1", "agent", "res", None, None, [], persist=False)
    stamp.assert_not_awaited()


async def test_stamp_delivery_never_raises(manager):
    manager._pool = _FakePool()
    with patch("parrot.scheduler.manager.AgentSchedule.get", new=AsyncMock(side_effect=RuntimeError("boom"))):
        await manager._stamp_delivery_outcome("s1", [{"callback": "c", "status": "failed", "error": "x"}])

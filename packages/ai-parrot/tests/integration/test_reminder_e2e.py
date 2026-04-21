"""End-to-end integration tests for the reminder toolkit — FEAT-115 / TASK-820.

Uses a real ``AsyncIOScheduler`` backed by ``MemoryJobStore`` (keyed as
``"redis"`` to mirror production).  No live Redis instance is required.

Three scenarios are exercised:
1. A reminder fires at the scheduled time and the job is auto-cleaned from the
   jobstore by APScheduler's ``DateTrigger`` semantics.
2. A cancelled reminder never invokes the notifier.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from parrot.auth.permission import PermissionContext, UserSession
from parrot.tools.reminder import ReminderToolkit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pctx(user: str = "user-123") -> PermissionContext:
    return PermissionContext(
        session=UserSession(user_id=user, tenant_id="acme", roles=frozenset()),
        channel="telegram",
        extra={"telegram_id": 987654321},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def scheduler():
    """Real AsyncIOScheduler with MemoryJobStore aliased as 'redis'.

    The toolkit calls ``scheduler.add_job(..., jobstore='redis')``, so we
    bind the name ``"redis"`` to ``MemoryJobStore`` so the toolkit operates
    normally without a live Redis daemon.
    """
    s = AsyncIOScheduler(
        jobstores={
            "default": MemoryJobStore(),
            "redis": MemoryJobStore(),
        },
        timezone="UTC",
    )
    s.start()
    yield s
    s.shutdown(wait=False)


@pytest.fixture
def sm(scheduler):
    """Minimal scheduler manager wrapper — real scheduler, mocked outer shell."""
    manager = MagicMock()
    manager.scheduler = scheduler
    return manager


@pytest.fixture
def toolkit(sm):
    """ReminderToolkit wired to the real (in-process) scheduler."""
    return ReminderToolkit(scheduler_manager=sm)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_end_to_end_reminder_fires_and_cleans_up(toolkit, scheduler):
    """Schedule a reminder at T+1s; assert it fires and is removed from jobstore.

    Verifies two critical properties that unit tests cannot prove:
    - APScheduler invokes ``deliver_reminder`` with the correct kwargs.
    - After the ``DateTrigger`` fires, the job is automatically removed
      from the jobstore (no manual cleanup needed).
    """
    with patch("parrot.tools.reminder._notifier") as mock_notifier:
        mock_notifier.send_notification = AsyncMock(return_value={})

        pctx = _pctx()
        await toolkit._pre_execute("schedule_reminder", _permission_context=pctx)
        out = await toolkit.schedule_reminder(
            message="integration test reminder",
            delay_seconds=1,
            channel="telegram",
        )
        rid = out["reminder_id"]

        # Job should be in the jobstore immediately after scheduling
        assert scheduler.get_job(rid, jobstore="redis") is not None

        # Wait long enough for the DateTrigger to fire and the executor to complete
        await asyncio.sleep(3.0)

        # Notifier must have been called exactly once with the correct payload
        mock_notifier.send_notification.assert_awaited_once()
        call_kwargs = mock_notifier.send_notification.call_args.kwargs
        assert call_kwargs["recipients"] == [987654321]
        assert call_kwargs["provider"] == "telegram"
        assert "integration test reminder" in call_kwargs["message"]
        assert "⏰" in call_kwargs["message"]

        # Job must be gone from the jobstore (DateTrigger self-cleans)
        assert scheduler.get_job(rid, jobstore="redis") is None


async def test_cancel_removes_from_jobstore(toolkit, scheduler):
    """Cancel a pending reminder; assert it never fires and is removed.

    Schedules a reminder 60 seconds in the future, immediately cancels it,
    then waits briefly to confirm the notifier is never invoked.
    """
    with patch("parrot.tools.reminder._notifier") as mock_notifier:
        mock_notifier.send_notification = AsyncMock(return_value={})

        pctx = _pctx()
        await toolkit._pre_execute("schedule_reminder", _permission_context=pctx)
        out = await toolkit.schedule_reminder(
            message="should never fire",
            delay_seconds=60,
            channel="telegram",
        )
        rid = out["reminder_id"]

        # Confirm job is present before cancellation
        assert scheduler.get_job(rid, jobstore="redis") is not None

        # Cancel via the toolkit
        await toolkit._pre_execute("cancel_reminder", _permission_context=pctx)
        result = await toolkit.cancel_reminder(rid)
        assert result == {"status": "cancelled", "reminder_id": rid}

        # Job must be absent from the jobstore immediately after cancellation
        assert scheduler.get_job(rid, jobstore="redis") is None

        # Give the event loop a tick to confirm nothing fires
        await asyncio.sleep(0.2)
        mock_notifier.send_notification.assert_not_awaited()


async def test_list_reminders_reflects_live_jobstore(toolkit, scheduler):
    """list_my_reminders returns only pending reminders owned by the caller."""
    with patch("parrot.tools.reminder._notifier"):
        pctx_alice = _pctx(user="alice")
        pctx_bob = _pctx(user="bob")

        # Schedule one for Alice and one for Bob
        await toolkit._pre_execute("schedule_reminder", _permission_context=pctx_alice)
        await toolkit.schedule_reminder(message="Alice's reminder", delay_seconds=60)

        await toolkit._pre_execute("schedule_reminder", _permission_context=pctx_bob)
        await toolkit.schedule_reminder(message="Bob's reminder", delay_seconds=60)

        # Alice should see only her own reminder
        await toolkit._pre_execute("list_my_reminders", _permission_context=pctx_alice)
        alice_reminders = await toolkit.list_my_reminders()
        assert len(alice_reminders) == 1
        assert alice_reminders[0]["message"] == "Alice's reminder"

        # Bob should see only his own reminder
        await toolkit._pre_execute("list_my_reminders", _permission_context=pctx_bob)
        bob_reminders = await toolkit.list_my_reminders()
        assert len(bob_reminders) == 1
        assert bob_reminders[0]["message"] == "Bob's reminder"

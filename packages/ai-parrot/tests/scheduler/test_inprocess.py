"""Tests for InProcessScheduler (FEAT-453, Module 8, Decision D1).

FEAT-453 TASK-2394.
"""
import asyncio
import stat
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from parrot.scheduler.inprocess import (
    InProcessScheduler,
    TaxDeadline,
    notify_tax_deadline,
    schedule_tax_reminder,
    sweep_checkpoint_retention,
)


class TestNoShadowing:
    def test_satellite_symbols_still_delegate(self):
        """Regression for Decision D1 — core must not shadow the satellite."""
        import parrot.scheduler as s

        for name in (
            "AgentSchedulerManager", "ScheduleType", "schedule",
            "schedule_daily_report", "schedule_weekly_report",
        ):
            assert name in s.__all__

    def test_inprocess_is_distinctly_named(self):
        assert InProcessScheduler.__name__ != "AgentSchedulerManager"

    def test_inprocess_module_does_not_export_server_names(self):
        import parrot.scheduler.inprocess as mod

        server_names = {
            "AgentSchedulerManager", "ScheduleType", "schedule",
            "schedule_daily_report", "schedule_weekly_report",
        }
        exported = {name for name in dir(mod) if not name.startswith("_")}
        assert exported.isdisjoint(server_names)


@pytest.fixture
async def scheduler():
    sched = InProcessScheduler()
    yield sched
    await sched.stop()


class TestInProcessScheduler:
    def test_add_cron_registers_job(self, scheduler):
        job_id = scheduler.add_cron("t", "0 9 1 1 *", lambda: None)
        assert job_id == "t"
        assert scheduler._scheduler.get_job("t") is not None

    def test_add_cron_rejects_malformed_expression(self, scheduler):
        with pytest.raises(ValueError, match="5-field"):
            scheduler.add_cron("bad", "* * *", lambda: None)

    def test_replacing_job_name_replaces_not_duplicates(self, scheduler):
        scheduler.add_cron("t", "0 9 1 1 *", lambda: None)
        scheduler.add_cron("t", "0 10 1 1 *", lambda: None)
        assert len(scheduler._scheduler.get_jobs()) == 1

    async def test_add_cron_fires(self, scheduler):
        fired = []

        async def _callback():
            fired.append(1)

        job_id = scheduler.add_cron("t", "0 9 1 1 *", _callback)
        # Force an immediate fire rather than waiting for the next real
        # Jan-1-09:00 occurrence — this is a real APScheduler job actually
        # executing, not a call to the callback made directly by the test.
        scheduler._scheduler.modify_job(job_id, next_run_time=datetime.now(timezone.utc))
        await scheduler.start()

        for _ in range(50):
            if fired:
                break
            await asyncio.sleep(0.05)

        assert fired == [1]

    async def test_start_is_idempotent(self, scheduler):
        await scheduler.start()
        await scheduler.start()  # must not raise
        assert scheduler._running

    async def test_stop_is_idempotent(self, scheduler):
        await scheduler.start()
        await scheduler.stop()
        await scheduler.stop()  # must not raise
        assert not scheduler._running


class TestTaxReminder:
    def test_schedule_tax_reminder_registers_job(self, scheduler):
        deadline = TaxDeadline(name="Modelo 303 Q1", due_date=date(2026, 4, 20))
        on_reminder = AsyncMock()
        job_id = schedule_tax_reminder(scheduler, deadline, on_reminder=on_reminder)
        assert scheduler._scheduler.get_job(job_id) is not None
        assert "Modelo 303 Q1" in job_id

    def test_reminder_fires_lead_days_before_due_date(self, scheduler):
        # due_date=2026-04-20, lead=7 -> reminder on 2026-04-13
        deadline = TaxDeadline(name="Modelo 303 Q1", due_date=date(2026, 4, 20), reminder_lead_days=7)
        job_id = schedule_tax_reminder(scheduler, deadline, on_reminder=AsyncMock())
        job = scheduler._scheduler.get_job(job_id)
        trigger = job.trigger
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields["day"] == "13"
        assert fields["month"] == "4"

    async def test_reminder_callback_invoked_with_deadline(self, scheduler):
        deadline = TaxDeadline(name="Modelo 303 Q1", due_date=date(2026, 4, 20))
        on_reminder = AsyncMock()
        job_id = schedule_tax_reminder(scheduler, deadline, on_reminder=on_reminder)
        scheduler._scheduler.modify_job(job_id, next_run_time=datetime.now(timezone.utc))
        await scheduler.start()

        for _ in range(50):
            if on_reminder.await_count:
                break
            await asyncio.sleep(0.05)

        on_reminder.assert_awaited_once_with(deadline)

    async def test_notify_tax_deadline_sends_notification(self):
        channel = AsyncMock()
        deadline = TaxDeadline(name="Modelo 303 Q1", due_date=date(2026, 4, 20))
        await notify_tax_deadline(deadline, channel=channel, recipient="operator")
        channel.send_notification.assert_awaited_once()
        recipient, message = channel.send_notification.call_args.args
        assert recipient == "operator"
        assert "Modelo 303 Q1" in message

    async def test_notify_tax_deadline_without_channel_does_not_raise(self):
        deadline = TaxDeadline(name="Modelo 303 Q1", due_date=date(2026, 4, 20))
        await notify_tax_deadline(deadline, channel=None)  # must not raise


class TestCheckpointRetentionSweep:
    async def test_archives_old_files_never_deletes(self, tmp_path):
        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()
        old_file = checkpoint_dir / "old.import.json"
        old_file.write_text("{}")

        # Backdate the file's mtime by 100 days.
        old_time = (datetime.now(timezone.utc) - timedelta(days=100)).timestamp()
        import os

        os.utime(old_file, (old_time, old_time))

        archived = await sweep_checkpoint_retention(checkpoint_dir, retention_days=90)

        assert not old_file.exists()  # moved, not left in place
        assert len(archived) == 1
        assert archived[0].exists()  # still exists — archived, not deleted
        assert archived[0].parent.name == "archive"

    async def test_recent_files_are_not_archived(self, tmp_path):
        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()
        recent_file = checkpoint_dir / "recent.import.json"
        recent_file.write_text("{}")

        archived = await sweep_checkpoint_retention(checkpoint_dir, retention_days=90)

        assert archived == []
        assert recent_file.exists()

    async def test_archive_dir_permissions(self, tmp_path):
        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()
        await sweep_checkpoint_retention(checkpoint_dir, retention_days=90)
        archive_dir = checkpoint_dir / "archive"
        assert stat.S_IMODE(archive_dir.stat().st_mode) == 0o700

    async def test_sweep_alerts_channel_when_archiving(self, tmp_path):
        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()
        old_file = checkpoint_dir / "old.import.json"
        old_file.write_text("{}")
        old_time = (datetime.now(timezone.utc) - timedelta(days=100)).timestamp()
        import os

        os.utime(old_file, (old_time, old_time))

        channel = AsyncMock()
        await sweep_checkpoint_retention(checkpoint_dir, retention_days=90, channel=channel)
        channel.send_notification.assert_awaited_once()

    async def test_sweep_does_not_alert_when_nothing_archived(self, tmp_path):
        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()
        channel = AsyncMock()
        await sweep_checkpoint_retention(checkpoint_dir, retention_days=90, channel=channel)
        channel.send_notification.assert_not_awaited()

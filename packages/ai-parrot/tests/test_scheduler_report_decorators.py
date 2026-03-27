"""Unit tests for @schedule_daily_report and @schedule_weekly_report (FEAT-028).

Covers:
    - Decorator metadata (Module 1)
    - Env var parsers _parse_daily_schedule / _parse_weekly_schedule (Module 2)
    - register_bot_schedules() env var integration (Module 3)
"""
import asyncio
import os
from unittest.mock import MagicMock, patch, call

import pytest
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

# ---------------------------------------------------------------------------
# RedisJobStore must return a real BaseJobStore so APScheduler's type check
# passes. All other infrastructure stubs are installed by conftest.py.
# ---------------------------------------------------------------------------
_redis_patch = patch(
    "apscheduler.jobstores.redis.RedisJobStore",
    side_effect=lambda **_kw: MemoryJobStore(),
)
_redis_patch.start()

from parrot.scheduler import (  # noqa: E402
    AgentSchedulerManager,
    ScheduleType,
    schedule,
    schedule_daily_report,
    schedule_weekly_report,
    _parse_daily_schedule,
    _parse_weekly_schedule,
    _resolve_report_schedule,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager() -> AgentSchedulerManager:
    """Return a fresh AgentSchedulerManager with no bot_manager."""
    return AgentSchedulerManager(bot_manager=None)


def _cron_field(trigger: CronTrigger, name: str) -> str:
    """Return the string value of a named CronTrigger field."""
    return next(str(f) for f in trigger.fields if f.name == name)


def _cron_hour(trigger: CronTrigger) -> int:
    return int(_cron_field(trigger, "hour"))


def _cron_minute(trigger: CronTrigger) -> int:
    return int(_cron_field(trigger, "minute"))


def _cron_dow(trigger: CronTrigger) -> str:
    return _cron_field(trigger, "day_of_week")


# ---------------------------------------------------------------------------
# Section 1 – Decorator metadata
# ---------------------------------------------------------------------------

class TestDecoratorMetadata:
    """@schedule_daily_report and @schedule_weekly_report attach correct attributes."""

    def setup_method(self):
        class SampleBot:
            @schedule_daily_report
            async def daily_report(self):
                """Daily report."""

            @schedule_weekly_report
            async def weekly_report(self):
                """Weekly digest."""

        self.bot = SampleBot()

    def test_daily_attaches_report_type(self):
        assert self.bot.daily_report._schedule_report_type == "daily"

    def test_weekly_attaches_report_type(self):
        assert self.bot.weekly_report._schedule_report_type == "weekly"

    def test_daily_schedule_config_schedule_type(self):
        assert self.bot.daily_report._schedule_config["schedule_type"] == ScheduleType.DAILY.value

    def test_weekly_schedule_config_schedule_type(self):
        assert self.bot.weekly_report._schedule_config["schedule_type"] == ScheduleType.WEEKLY.value

    def test_daily_schedule_config_is_empty_dict(self):
        assert self.bot.daily_report._schedule_config["schedule_config"] == {}

    def test_weekly_schedule_config_is_empty_dict(self):
        assert self.bot.weekly_report._schedule_config["schedule_config"] == {}

    def test_daily_method_name_preserved_in_config(self):
        assert self.bot.daily_report._schedule_config["method_name"] == "daily_report"

    def test_weekly_method_name_preserved_in_config(self):
        assert self.bot.weekly_report._schedule_config["method_name"] == "weekly_report"

    def test_daily_wraps_preserves_dunder_name(self):
        assert self.bot.daily_report.__name__ == "daily_report"

    def test_weekly_wraps_preserves_dunder_name(self):
        assert self.bot.weekly_report.__name__ == "weekly_report"

    def test_daily_is_awaitable(self):
        asyncio.run(self.bot.daily_report())  # must not raise

    def test_weekly_is_awaitable(self):
        asyncio.run(self.bot.weekly_report())  # must not raise

    def test_plain_method_has_no_report_type(self):
        class Plain:
            async def plain(self):
                pass
        assert not hasattr(Plain().plain, "_schedule_report_type")

    def test_both_exported_in_all(self):
        import parrot.scheduler as sched
        assert "schedule_daily_report" in sched.__all__
        assert "schedule_weekly_report" in sched.__all__


# ---------------------------------------------------------------------------
# Section 2 – Env var parsers
# ---------------------------------------------------------------------------

class TestParseDailySchedule:
    """_parse_daily_schedule() — valid, default, and malformed inputs."""

    def test_valid_zero_padded(self):
        assert _parse_daily_schedule("08:30") == {"hour": 8, "minute": 30}

    def test_valid_no_pad(self):
        assert _parse_daily_schedule("9:05") == {"hour": 9, "minute": 5}

    def test_valid_noon(self):
        assert _parse_daily_schedule("12:00") == {"hour": 12, "minute": 0}

    def test_valid_midnight(self):
        assert _parse_daily_schedule("00:00") == {"hour": 0, "minute": 0}

    def test_default_on_none(self):
        assert _parse_daily_schedule(None) == {"hour": 8, "minute": 0}

    def test_default_on_empty_string(self):
        assert _parse_daily_schedule("") == {"hour": 8, "minute": 0}

    def test_default_on_malformed_word(self):
        assert _parse_daily_schedule("bad") == {"hour": 8, "minute": 0}

    def test_default_on_missing_minutes(self):
        assert _parse_daily_schedule("10") == {"hour": 8, "minute": 0}

    def test_default_on_non_numeric(self):
        assert _parse_daily_schedule("HH:MM") == {"hour": 8, "minute": 0}


class TestParseWeeklySchedule:
    """_parse_weekly_schedule() — valid, default, and malformed inputs."""

    def test_valid_abbrev_uppercase(self):
        assert _parse_weekly_schedule("FRI 17:00") == {
            "day_of_week": "fri", "hour": 17, "minute": 0
        }

    def test_valid_abbrev_lowercase(self):
        assert _parse_weekly_schedule("tue 06:45") == {
            "day_of_week": "tue", "hour": 6, "minute": 45
        }

    def test_valid_full_name_lowercase(self):
        result = _parse_weekly_schedule("monday 09:30")
        assert result == {"day_of_week": "mon", "hour": 9, "minute": 30}

    def test_valid_full_name_uppercase(self):
        result = _parse_weekly_schedule("WEDNESDAY 12:00")
        assert result["day_of_week"] == "wed"
        assert result["hour"] == 12

    def test_valid_full_name_mixed_case(self):
        result = _parse_weekly_schedule("Thursday 08:15")
        assert result["day_of_week"] == "thu"

    def test_default_on_none(self):
        assert _parse_weekly_schedule(None) == {
            "day_of_week": "mon", "hour": 9, "minute": 0
        }

    def test_default_on_empty_string(self):
        assert _parse_weekly_schedule("") == {
            "day_of_week": "mon", "hour": 9, "minute": 0
        }

    def test_default_on_malformed_word(self):
        assert _parse_weekly_schedule("bad") == {
            "day_of_week": "mon", "hour": 9, "minute": 0
        }

    def test_default_on_missing_time(self):
        assert _parse_weekly_schedule("monday") == {
            "day_of_week": "mon", "hour": 9, "minute": 0
        }

    def test_default_on_non_numeric_time(self):
        assert _parse_weekly_schedule("mon HH:MM") == {
            "day_of_week": "mon", "hour": 9, "minute": 0
        }


# ---------------------------------------------------------------------------
# Section 3 – register_bot_schedules() integration
# ---------------------------------------------------------------------------

class TestRegisterBotSchedules:
    """register_bot_schedules() resolves env vars for report decorators."""

    def _make_daily_bot(self, name="mybot", chatbot_id=None):
        class DailyBot:
            @schedule_daily_report
            async def daily(self): pass

        bot = DailyBot()
        bot.name = name
        if chatbot_id:
            bot.chatbot_id = chatbot_id
        return bot

    def _make_weekly_bot(self, name="mybot", chatbot_id=None):
        class WeeklyBot:
            @schedule_weekly_report
            async def weekly(self): pass

        bot = WeeklyBot()
        bot.name = name
        if chatbot_id:
            bot.chatbot_id = chatbot_id
        return bot

    def test_daily_reads_env_var(self, monkeypatch):
        monkeypatch.setenv("MYBOT_DAILY_REPORT", "10:15")
        bot = self._make_daily_bot()
        mgr = _make_manager()
        mgr.register_bot_schedules(bot)
        jobs = {j.id: j for j in mgr.scheduler.get_jobs()}
        trigger = jobs["auto_mybot_daily"].trigger
        assert isinstance(trigger, CronTrigger)
        assert _cron_hour(trigger) == 10
        assert _cron_minute(trigger) == 15

    def test_daily_default_when_no_env_var(self, monkeypatch):
        monkeypatch.delenv("MYBOT_DAILY_REPORT", raising=False)
        bot = self._make_daily_bot()
        mgr = _make_manager()
        mgr.register_bot_schedules(bot)
        jobs = {j.id: j for j in mgr.scheduler.get_jobs()}
        trigger = jobs["auto_mybot_daily"].trigger
        assert _cron_hour(trigger) == 8
        assert _cron_minute(trigger) == 0

    def test_weekly_reads_env_var(self, monkeypatch):
        monkeypatch.setenv("MYBOT_WEEKLY_REPORT", "FRI 17:00")
        bot = self._make_weekly_bot()
        mgr = _make_manager()
        mgr.register_bot_schedules(bot)
        jobs = {j.id: j for j in mgr.scheduler.get_jobs()}
        trigger = jobs["auto_mybot_weekly"].trigger
        assert isinstance(trigger, CronTrigger)
        assert _cron_dow(trigger) == "fri"
        assert _cron_hour(trigger) == 17

    def test_weekly_default_when_no_env_var(self, monkeypatch):
        monkeypatch.delenv("MYBOT_WEEKLY_REPORT", raising=False)
        bot = self._make_weekly_bot()
        mgr = _make_manager()
        mgr.register_bot_schedules(bot)
        jobs = {j.id: j for j in mgr.scheduler.get_jobs()}
        trigger = jobs["auto_mybot_weekly"].trigger
        assert _cron_dow(trigger) == "mon"
        assert _cron_hour(trigger) == 9

    def test_uses_chatbot_id_for_env_key(self):
        """chatbot_id takes priority over name when building the env var key."""
        with patch("parrot.scheduler._resolve_report_schedule") as mock_resolve:
            mock_resolve.return_value = {"hour": 8, "minute": 0}
            bot = self._make_daily_bot(name="ignored", chatbot_id="analytics_bot")
            mgr = _make_manager()
            mgr.register_bot_schedules(bot)
            mock_resolve.assert_called_once_with("analytics_bot", "daily")

    def test_falls_back_to_name_for_env_key(self):
        """name is used when chatbot_id is absent."""
        with patch("parrot.scheduler._resolve_report_schedule") as mock_resolve:
            mock_resolve.return_value = {"hour": 8, "minute": 0}
            bot = self._make_daily_bot(name="ReportBot")
            mgr = _make_manager()
            mgr.register_bot_schedules(bot)
            mock_resolve.assert_called_once_with("ReportBot", "daily")

    def test_general_schedule_decorator_unaffected(self, monkeypatch):
        """@schedule(ScheduleType.INTERVAL, minutes=15) still uses its inline config."""
        class PollBot:
            name = "pollbot"
            @schedule(schedule_type=ScheduleType.INTERVAL, minutes=15)
            async def poll(self): pass

        mgr = _make_manager()
        n = mgr.register_bot_schedules(PollBot())
        assert n == 1
        jobs = {j.id: j for j in mgr.scheduler.get_jobs()}
        trigger = jobs["auto_pollbot_poll"].trigger
        assert isinstance(trigger, IntervalTrigger)
        assert trigger.interval.seconds == 900

    def test_mixed_bot_registers_all_three(self, monkeypatch):
        """Bot with all three decorator types → 3 jobs."""
        monkeypatch.delenv("MIXBOT_DAILY_REPORT", raising=False)
        monkeypatch.delenv("MIXBOT_WEEKLY_REPORT", raising=False)

        class MixBot:
            name = "mixbot"
            @schedule_daily_report
            async def daily(self): pass
            @schedule_weekly_report
            async def weekly(self): pass
            @schedule(schedule_type=ScheduleType.INTERVAL, minutes=30)
            async def poll(self): pass

        mgr = _make_manager()
        n = mgr.register_bot_schedules(MixBot())
        assert n == 3
        jobs = mgr.scheduler.get_jobs()
        assert len(jobs) == 3

    def test_daily_job_id_format(self, monkeypatch):
        monkeypatch.delenv("MYBOT_DAILY_REPORT", raising=False)
        bot = self._make_daily_bot()
        mgr = _make_manager()
        mgr.register_bot_schedules(bot)
        ids = [j.id for j in mgr.scheduler.get_jobs()]
        assert "auto_mybot_daily" in ids

    def test_weekly_job_name_format(self, monkeypatch):
        monkeypatch.delenv("MYBOT_WEEKLY_REPORT", raising=False)
        bot = self._make_weekly_bot()
        mgr = _make_manager()
        mgr.register_bot_schedules(bot)
        names = [j.name for j in mgr.scheduler.get_jobs()]
        assert "mybot.weekly" in names

    def test_return_count_daily_only(self, monkeypatch):
        monkeypatch.delenv("MYBOT_DAILY_REPORT", raising=False)
        bot = self._make_daily_bot()
        mgr = _make_manager()
        assert mgr.register_bot_schedules(bot) == 1

    def test_return_count_weekly_only(self, monkeypatch):
        monkeypatch.delenv("MYBOT_WEEKLY_REPORT", raising=False)
        bot = self._make_weekly_bot()
        mgr = _make_manager()
        assert mgr.register_bot_schedules(bot) == 1

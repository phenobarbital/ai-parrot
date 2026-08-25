"""Integration tests: AgentSchedulerManager hardening against bad inputs.

These exercise the wiring rather than the pure helpers — i.e. that the
sanitizers are actually reached from `_make_redis_jobstore()`,
`_create_trigger()` and the jobstore-alias paths.
"""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from parrot.scheduler import manager as manager_module
from parrot.scheduler.manager import AgentSchedulerManager
from parrot.scheduler.sanitize import SchedulerConfigError


@pytest.fixture
def scheduler_manager():
    """A manager with the default in-memory jobstore, no DB, no Redis."""
    return AgentSchedulerManager()


# ---------------------------------------------------------------------------
# The reported production failure
# ---------------------------------------------------------------------------
class TestRedisJobstoreConstruction:
    def test_empty_cache_port_does_not_reach_redis(self, monkeypatch, scheduler_manager):
        """Regression: CACHE_PORT='' caused a per-tick get_due_jobs failure.

        ``invalid literal for int() with base 10: ''`` was raised lazily by
        redis-py, inside APScheduler's job-processing loop.
        """
        monkeypatch.setattr(manager_module, "CACHE_PORT", "")
        monkeypatch.setattr(manager_module, "CACHE_HOST", "")

        store = scheduler_manager._make_redis_jobstore()

        # Force redis-py to build a connection — this is where int(port) ran.
        conn = store.redis.connection_pool.make_connection()
        assert conn.port == 6379
        assert conn.host == "localhost"

    def test_whitespace_cache_values_are_trimmed(self, monkeypatch, scheduler_manager):
        monkeypatch.setattr(manager_module, "CACHE_PORT", " 6380 ")
        monkeypatch.setattr(manager_module, "CACHE_HOST", "  redis.internal  ")

        conn = scheduler_manager._make_redis_jobstore().redis.connection_pool.make_connection()
        assert (conn.host, conn.port) == ("redis.internal", 6380)

    def test_out_of_range_port_falls_back(self, monkeypatch, scheduler_manager):
        monkeypatch.setattr(manager_module, "CACHE_PORT", "99999")
        conn = scheduler_manager._make_redis_jobstore().redis.connection_pool.make_connection()
        assert conn.port == 6379


# ---------------------------------------------------------------------------
# _create_trigger
# ---------------------------------------------------------------------------
class TestCreateTriggerHardening:
    def test_blank_daily_fields_do_not_become_every_minute(self, scheduler_manager):
        """The dangerous case: CronTrigger(hour=None) fires every minute."""
        trigger = scheduler_manager._create_trigger("daily", {"hour": "", "minute": None})
        assert isinstance(trigger, CronTrigger)
        assert str(trigger) == "cron[hour='0', minute='0']"

    def test_schedule_type_is_trimmed_and_lowercased(self, scheduler_manager):
        trigger = scheduler_manager._create_trigger("  DAILY  ", {"hour": 8, "minute": 0})
        assert str(trigger) == "cron[hour='8', minute='0']"

    @pytest.mark.parametrize("bad", ["", "   ", None, "hourly"])
    def test_bad_schedule_type_raises_config_error(self, scheduler_manager, bad):
        with pytest.raises(SchedulerConfigError):
            scheduler_manager._create_trigger(bad, {})

    def test_numeric_strings_are_coerced_for_interval(self, scheduler_manager):
        trigger = scheduler_manager._create_trigger("interval", {"minutes": "15"})
        assert isinstance(trigger, IntervalTrigger)
        assert trigger.interval.total_seconds() == 900

    def test_zero_interval_is_rejected_not_run_every_second(self, scheduler_manager):
        with pytest.raises(SchedulerConfigError, match="interval"):
            scheduler_manager._create_trigger("interval", {"minutes": "", "hours": None})

    def test_unknown_cron_keys_are_dropped(self, scheduler_manager):
        trigger = scheduler_manager._create_trigger(
            "cron", {"hour": " 8 ", "minute": "0", "injected": "rm -rf"}
        )
        assert str(trigger) == "cron[hour='8', minute='0']"

    def test_crontab_timezone_key_does_not_collide(self, scheduler_manager):
        """`from_crontab(**config, timezone='UTC')` used to raise TypeError."""
        trigger = scheduler_manager._create_trigger(
            "crontab", {"expr": "  0   8 * * *  ", "timezone": "UTC"}
        )
        assert isinstance(trigger, CronTrigger)

    def test_blank_crontab_expr_raises_config_error(self, scheduler_manager):
        with pytest.raises(SchedulerConfigError, match="expr"):
            scheduler_manager._create_trigger("crontab", {"expr": "   "})

    def test_blank_run_date_falls_back_to_now(self, scheduler_manager):
        trigger = scheduler_manager._create_trigger("once", {"run_date": ""})
        assert isinstance(trigger, DateTrigger)

    def test_datetime_run_date_is_preserved(self, scheduler_manager):
        when = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
        trigger = scheduler_manager._create_trigger("once", {"run_date": when})
        assert trigger.run_date == when

    def test_none_config_is_tolerated(self, scheduler_manager):
        trigger = scheduler_manager._create_trigger("daily", None)
        assert str(trigger) == "cron[hour='0', minute='0']"

    def test_weekly_full_day_name_is_normalized(self, scheduler_manager):
        trigger = scheduler_manager._create_trigger(
            "weekly", {"day_of_week": " Friday ", "hour": "17", "minute": ""}
        )
        assert "day_of_week='fri'" in str(trigger)


# ---------------------------------------------------------------------------
# Jobstore alias normalization
# ---------------------------------------------------------------------------
class TestJobstoreAlias:
    def test_default_is_always_registered(self, scheduler_manager):
        assert "default" in scheduler_manager._registered_jobstores()

    @pytest.mark.parametrize("bad", ["", "   ", None, "null"])
    def test_blank_alias_falls_back_to_default(self, scheduler_manager, bad):
        assert scheduler_manager._safe_jobstore(bad) == "default"

    def test_unregistered_redis_alias_falls_back(self, scheduler_manager):
        """A row saying 'redis' must not KeyError when Redis was not enabled."""
        assert "redis" not in scheduler_manager._registered_jobstores()
        assert scheduler_manager._safe_jobstore("redis") == "default"

    def test_registered_alias_is_kept(self, scheduler_manager, monkeypatch):
        monkeypatch.setattr(manager_module, "CACHE_PORT", 6379)
        scheduler_manager._ensure_redis_jobstore()
        assert scheduler_manager._safe_jobstore("  REDIS  ") == "redis"

    def test_strict_mode_rejects_unregistered_alias(self, scheduler_manager):
        """add_schedule() uses strict=True so callers learn Redis is off."""
        with pytest.raises(SchedulerConfigError, match="redis"):
            scheduler_manager._safe_jobstore("redis", strict=True)

    def test_strict_mode_still_defaults_blank_alias(self, scheduler_manager):
        assert scheduler_manager._safe_jobstore("  ", strict=True) == "default"

    def test_add_job_accepts_normalized_alias(self, scheduler_manager):
        """End-to-end: a bad alias must not break add_job()."""
        job = scheduler_manager.scheduler.add_job(
            lambda: None,
            trigger=scheduler_manager._create_trigger("daily", {"hour": "", "minute": ""}),
            id="test-job",
            jobstore=scheduler_manager._safe_jobstore("  "),
            replace_existing=True,
        )
        assert job is not None


# ---------------------------------------------------------------------------
# Validation ordering: nothing invalid may be persisted
# ---------------------------------------------------------------------------
class TestValidateBeforePersist:
    """A rejected config must never reach the database.

    `add_schedule()` wraps every exception from the "add to APScheduler" block
    in a RuntimeError after deleting the row, so validating there would both
    mask SchedulerConfigError (no 400 possible) and write-then-delete a row.
    `update_schedule()` persisted before building the trigger, leaving the row
    holding a config that `load_schedules_from_db()` would keep rejecting.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "schedule_type,schedule_config",
        [
            ("interval", {"minutes": "", "hours": None}),   # zero interval
            ("crontab", {"expr": "   "}),                   # blank expression
            ("crontab", {"expr": "0 8"}),                   # wrong field count
            ("hourly", {}),                                 # unknown type
            ("", {"hour": 8}),                              # blank type
        ],
    )
    async def test_add_schedule_rejects_before_touching_db(
        self, scheduler_manager, schedule_type, schedule_config
    ):
        """`_pool` is None, so reaching the DB would raise AttributeError."""
        assert scheduler_manager._pool is None

        with pytest.raises(SchedulerConfigError):
            await scheduler_manager.add_schedule(
                agent_name="any_agent",
                schedule_type=schedule_type,
                schedule_config=schedule_config,
            )

    @pytest.mark.asyncio
    async def test_add_schedule_rejects_unavailable_jobstore_before_db(
        self, scheduler_manager
    ):
        assert "redis" not in scheduler_manager._registered_jobstores()

        with pytest.raises(SchedulerConfigError, match="redis"):
            await scheduler_manager.add_schedule(
                agent_name="any_agent",
                schedule_type="daily",
                schedule_config={"hour": 8, "minute": 0},
                scheduler_type="redis",
            )

    @pytest.mark.asyncio
    async def test_update_schedule_does_not_persist_rejected_config(
        self, scheduler_manager, monkeypatch
    ):
        """The row must keep its old config when the new one is unusable."""
        schedule = SimpleNamespace(
            schedule_id="s-1",
            agent_name="any_agent",
            schedule_type="daily",
            schedule_config={"hour": 8, "minute": 0},
            scheduler_type="default",
            enabled=True,
            updated_at=None,
            next_run=None,
            update=AsyncMock(),
        )
        monkeypatch.setattr(
            scheduler_manager, "get_schedule", AsyncMock(return_value=schedule)
        )
        pool = MagicMock()
        monkeypatch.setattr(
            scheduler_manager, "_get_connection_pool", AsyncMock(return_value=pool)
        )

        with pytest.raises(SchedulerConfigError):
            await scheduler_manager.update_schedule(
                "s-1", {"schedule_type": "interval", "schedule_config": {"minutes": ""}}
            )

        schedule.update.assert_not_awaited()
        pool.acquire.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_schedule_rejects_unavailable_jobstore(
        self, scheduler_manager, monkeypatch
    ):
        """Persisting scheduler_type='redis' while running in memory is a lie."""
        schedule = SimpleNamespace(
            schedule_id="s-2",
            agent_name="any_agent",
            schedule_type="daily",
            schedule_config={"hour": 8, "minute": 0},
            scheduler_type="default",
            enabled=True,
            updated_at=None,
            next_run=None,
            update=AsyncMock(),
        )
        monkeypatch.setattr(
            scheduler_manager, "get_schedule", AsyncMock(return_value=schedule)
        )
        pool = MagicMock()
        monkeypatch.setattr(
            scheduler_manager, "_get_connection_pool", AsyncMock(return_value=pool)
        )

        with pytest.raises(SchedulerConfigError, match="redis"):
            await scheduler_manager.update_schedule("s-2", {"scheduler_type": "redis"})

        schedule.update.assert_not_awaited()
        assert schedule.scheduler_type == "default"

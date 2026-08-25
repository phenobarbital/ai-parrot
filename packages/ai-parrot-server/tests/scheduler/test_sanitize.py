"""Unit tests for scheduler input sanitization — APScheduler hardening.

Regression coverage for the production failure::

    apscheduler.scheduler(base.py:1162) :: Error getting due jobs from job
    store 'redis': invalid literal for int() with base 10: ''

Root cause: navconfig's ``fallback=`` only applies when a key is *absent*.
A key that is present-but-empty (``CACHE_PORT=`` in ``.env``) yields ``''``,
which flowed unvalidated into ``RedisJobStore(port='')``.  redis-py builds
connections lazily, so ``int(port)`` only ran on the first real command —
inside APScheduler's job-processing loop, once per tick, forever.
"""
from datetime import UTC, datetime

import pytest
from parrot.scheduler.sanitize import (
    SchedulerConfigError,
    clean_bool,
    clean_int,
    clean_str,
    normalize_jobstore_alias,
    normalize_schedule_type,
    sanitize_redis_settings,
    sanitize_schedule_config,
)


# ---------------------------------------------------------------------------
# clean_str
# ---------------------------------------------------------------------------
class TestCleanStr:
    @pytest.mark.parametrize("raw", ["", "   ", "\t\n", None])
    def test_blank_becomes_default(self, raw):
        assert clean_str(raw, default="fallback") == "fallback"

    @pytest.mark.parametrize("raw", ["none", "None", "NULL", "nil", "undefined", "~"])
    def test_null_tokens_become_default(self, raw):
        assert clean_str(raw, default="fallback") == "fallback"

    def test_trims_surrounding_whitespace(self):
        assert clean_str("  redis  ") == "redis"

    def test_lower_option(self):
        assert clean_str("  DAILY ", lower=True) == "daily"

    def test_non_string_is_coerced_and_trimmed(self):
        assert clean_str(6379) == "6379"

    def test_default_may_be_none(self):
        assert clean_str("  ", default=None) is None


# ---------------------------------------------------------------------------
# clean_int
# ---------------------------------------------------------------------------
class TestCleanInt:
    @pytest.mark.parametrize("raw", ["", "   ", None, "none", "null"])
    def test_blank_and_null_tokens_use_default(self, raw):
        assert clean_int(raw, default=6379) == 6379

    def test_numeric_string_is_coerced(self):
        assert clean_int(" 6380 ", default=6379) == 6380

    def test_garbage_uses_default(self):
        assert clean_int("not-a-port", default=6379) == 6379

    def test_float_string_is_coerced(self):
        assert clean_int("6379.0", default=1) == 6379

    def test_bool_is_not_treated_as_int(self):
        assert clean_int(True, default=7) == 7

    def test_out_of_range_uses_default(self):
        assert clean_int("70000", default=6379, minimum=1, maximum=65535) == 6379
        assert clean_int("-1", default=6379, minimum=1, maximum=65535) == 6379

    def test_in_range_is_kept(self):
        assert clean_int("1", default=6379, minimum=1, maximum=65535) == 1

    def test_default_none_is_allowed(self):
        assert clean_int("", default=None) is None

    @pytest.mark.parametrize("raw", ["1e400", "-1e400", "inf", "-inf", "Infinity"])
    def test_overflow_uses_default(self, raw):
        """float('1e400') is inf and int(inf) raises OverflowError."""
        assert clean_int(raw, default=6379) == 6379

    def test_huge_but_finite_is_range_checked(self):
        assert clean_int("1e308", default=6379, minimum=1, maximum=65535) == 6379


# ---------------------------------------------------------------------------
# clean_bool
# ---------------------------------------------------------------------------
class TestCleanBool:
    @pytest.mark.parametrize("raw", ["true", "True", " YES ", "1", "on", True])
    def test_truthy(self, raw):
        assert clean_bool(raw, default=False) is True

    @pytest.mark.parametrize("raw", ["false", "NO", "0", "off", False])
    def test_falsy(self, raw):
        assert clean_bool(raw, default=True) is False

    @pytest.mark.parametrize("raw", ["", "  ", None, "null", "maybe"])
    def test_blank_or_unknown_uses_default(self, raw):
        assert clean_bool(raw, default=True) is True


# ---------------------------------------------------------------------------
# sanitize_redis_settings — the reported production bug
# ---------------------------------------------------------------------------
class TestSanitizeRedisSettings:
    def test_empty_port_falls_back_to_6379(self):
        """The exact reported failure: CACHE_PORT='' must not reach redis-py."""
        settings = sanitize_redis_settings(host="localhost", port="")
        assert settings["port"] == 6379
        assert isinstance(settings["port"], int)

    def test_whitespace_host_falls_back_to_localhost(self):
        assert sanitize_redis_settings(host="   ", port=6379)["host"] == "localhost"

    def test_host_is_trimmed(self):
        assert sanitize_redis_settings(host=" redis.internal \n", port=6379)["host"] == "redis.internal"

    def test_none_values_fall_back(self):
        settings = sanitize_redis_settings(host=None, port=None)
        assert settings == {"host": "localhost", "port": 6379, "db": 6}

    def test_numeric_string_port_is_coerced(self):
        assert sanitize_redis_settings(host="h", port=" 6380 ")["port"] == 6380

    def test_out_of_range_port_falls_back(self):
        assert sanitize_redis_settings(host="h", port="99999")["port"] == 6379

    def test_db_is_sanitized(self):
        assert sanitize_redis_settings(host="h", port=1, db="")["db"] == 6
        assert sanitize_redis_settings(host="h", port=1, db="3")["db"] == 3

    def test_result_survives_redis_jobstore_construction(self):
        """End-to-end: the sanitized mapping must not blow up int(port)."""
        from apscheduler.jobstores.redis import RedisJobStore

        settings = sanitize_redis_settings(host="localhost", port="")
        store = RedisJobStore(
            jobs_key="apscheduler.jobs",
            run_times_key="apscheduler.run_times",
            **settings,
        )
        # redis-py defers int(port) until a connection is built; force it.
        conn = store.redis.connection_pool.make_connection()
        assert conn.port == 6379


# ---------------------------------------------------------------------------
# normalize_schedule_type
# ---------------------------------------------------------------------------
class TestNormalizeScheduleType:
    def test_trims_and_lowercases(self):
        assert normalize_schedule_type("  DAILY  ") == "daily"

    @pytest.mark.parametrize("raw", ["", "   ", None, "null"])
    def test_blank_raises_clear_error(self, raw):
        with pytest.raises(SchedulerConfigError, match="schedule_type"):
            normalize_schedule_type(raw)

    def test_unknown_raises_clear_error(self):
        with pytest.raises(SchedulerConfigError, match="hourly"):
            normalize_schedule_type("hourly")


# ---------------------------------------------------------------------------
# normalize_jobstore_alias
# ---------------------------------------------------------------------------
class TestNormalizeJobstoreAlias:
    def test_blank_becomes_default(self):
        assert normalize_jobstore_alias("", available={"default"}) == "default"
        assert normalize_jobstore_alias(None, available={"default"}) == "default"

    def test_trims_and_lowercases(self):
        assert normalize_jobstore_alias(" REDIS ", available={"default", "redis"}) == "redis"

    def test_unregistered_alias_falls_back_to_default(self):
        assert normalize_jobstore_alias("redis", available={"default"}) == "default"

    def test_registered_alias_is_kept(self):
        assert normalize_jobstore_alias("redis", available={"default", "redis"}) == "redis"

    def test_available_none_skips_registration_check(self):
        assert normalize_jobstore_alias(" redis ", available=None) == "redis"

    def test_strict_raises_for_unregistered_alias(self):
        """An explicit request must not be silently downgraded to memory."""
        with pytest.raises(SchedulerConfigError, match="redis"):
            normalize_jobstore_alias("redis", available={"default"}, strict=True)

    def test_strict_allows_registered_alias(self):
        assert normalize_jobstore_alias(
            "redis", available={"default", "redis"}, strict=True
        ) == "redis"

    def test_strict_blank_still_becomes_default(self):
        assert normalize_jobstore_alias("", available={"default"}, strict=True) == "default"


# ---------------------------------------------------------------------------
# sanitize_schedule_config
# ---------------------------------------------------------------------------
class TestSanitizeDaily:
    def test_empty_strings_fall_back_to_documented_defaults(self):
        """Critical: blank cron fields must NOT become None.

        ``CronTrigger(hour=None, minute=None)`` is silently accepted and
        degrades a daily job into an every-minute job.
        """
        assert sanitize_schedule_config("daily", {"hour": "", "minute": ""}) == {
            "hour": 0,
            "minute": 0,
        }

    def test_none_values_fall_back_to_defaults(self):
        assert sanitize_schedule_config("daily", {"hour": None, "minute": None}) == {
            "hour": 0,
            "minute": 0,
        }

    def test_numeric_strings_are_coerced(self):
        assert sanitize_schedule_config("daily", {"hour": " 8 ", "minute": "30"}) == {
            "hour": 8,
            "minute": 30,
        }

    def test_out_of_range_falls_back(self):
        assert sanitize_schedule_config("daily", {"hour": 99, "minute": -5}) == {
            "hour": 0,
            "minute": 0,
        }

    def test_missing_config_yields_defaults(self):
        assert sanitize_schedule_config("daily", None) == {"hour": 0, "minute": 0}

    def test_unknown_keys_are_dropped(self):
        assert sanitize_schedule_config("daily", {"hour": 8, "minute": 0, "bogus": "x"}) == {
            "hour": 8,
            "minute": 0,
        }


class TestSanitizeWeekly:
    def test_blank_day_of_week_falls_back(self):
        assert sanitize_schedule_config("weekly", {"day_of_week": "  ", "hour": 9, "minute": 0}) == {
            "day_of_week": "mon",
            "hour": 9,
            "minute": 0,
        }

    def test_day_of_week_is_trimmed_and_lowercased(self):
        out = sanitize_schedule_config("weekly", {"day_of_week": " FRI ", "hour": 17, "minute": 0})
        assert out["day_of_week"] == "fri"

    def test_full_day_name_is_abbreviated(self):
        out = sanitize_schedule_config("weekly", {"day_of_week": "Monday", "hour": 9, "minute": 0})
        assert out["day_of_week"] == "mon"

    def test_invalid_day_falls_back(self):
        out = sanitize_schedule_config("weekly", {"day_of_week": "funday", "hour": 9, "minute": 0})
        assert out["day_of_week"] == "mon"

    def test_numeric_day_of_week_is_kept(self):
        out = sanitize_schedule_config("weekly", {"day_of_week": "0", "hour": 9, "minute": 0})
        assert out["day_of_week"] == "0"


class TestSanitizeMonthly:
    def test_blank_day_falls_back_to_one(self):
        assert sanitize_schedule_config("monthly", {"day": "", "hour": "", "minute": ""}) == {
            "day": 1,
            "hour": 0,
            "minute": 0,
        }

    def test_day_out_of_range_falls_back(self):
        assert sanitize_schedule_config("monthly", {"day": 45})["day"] == 1


class TestSanitizeInterval:
    def test_blank_fields_become_zero(self):
        out = sanitize_schedule_config("interval", {"minutes": "15", "hours": "", "seconds": None})
        assert out == {"weeks": 0, "days": 0, "hours": 0, "minutes": 15, "seconds": 0}

    def test_all_zero_interval_is_rejected(self):
        """A zero interval silently becomes a 1-second hot loop in APScheduler."""
        with pytest.raises(SchedulerConfigError, match="interval"):
            sanitize_schedule_config("interval", {"minutes": "", "hours": ""})

    def test_empty_config_is_rejected(self):
        with pytest.raises(SchedulerConfigError, match="interval"):
            sanitize_schedule_config("interval", {})

    def test_negative_values_fall_back_to_zero(self):
        with pytest.raises(SchedulerConfigError, match="interval"):
            sanitize_schedule_config("interval", {"minutes": -5})

    def test_garbage_falls_back_to_zero(self):
        out = sanitize_schedule_config("interval", {"minutes": "abc", "hours": 2})
        assert out["minutes"] == 0
        assert out["hours"] == 2


class TestSanitizeOnce:
    def test_blank_run_date_is_dropped(self):
        assert sanitize_schedule_config("once", {"run_date": "  "}) == {}

    def test_none_run_date_is_dropped(self):
        assert sanitize_schedule_config("once", {"run_date": None}) == {}

    def test_datetime_is_preserved(self):
        when = datetime(2030, 1, 1, tzinfo=UTC)
        assert sanitize_schedule_config("once", {"run_date": when}) == {"run_date": when}

    def test_iso_string_is_trimmed_and_kept(self):
        out = sanitize_schedule_config("once", {"run_date": "  2030-01-01T10:00:00  "})
        assert out["run_date"] == "2030-01-01T10:00:00"

    def test_unparseable_date_raises_clear_error(self):
        with pytest.raises(SchedulerConfigError, match="run_date"):
            sanitize_schedule_config("once", {"run_date": "not-a-date"})


class TestSanitizeCron:
    def test_unknown_keys_are_dropped(self):
        out = sanitize_schedule_config("cron", {"hour": "8", "minute": "0", "bogus": 1})
        assert "bogus" not in out
        assert out["hour"] == "8"

    def test_blank_fields_are_dropped(self):
        out = sanitize_schedule_config("cron", {"hour": "8", "minute": "", "day_of_week": None})
        assert out == {"hour": "8"}

    def test_values_are_trimmed(self):
        out = sanitize_schedule_config("cron", {"hour": "  8 "})
        assert out["hour"] == "8"

    def test_empty_cron_config_is_rejected(self):
        with pytest.raises(SchedulerConfigError, match="cron"):
            sanitize_schedule_config("cron", {"hour": "", "minute": "  "})


class TestSanitizeCrontab:
    def test_only_expr_is_kept(self):
        """``timezone`` in config collides with the explicit timezone kwarg."""
        out = sanitize_schedule_config("crontab", {"expr": "0 8 * * *", "timezone": "UTC"})
        assert out == {"expr": "0 8 * * *"}

    def test_expr_whitespace_is_normalized(self):
        out = sanitize_schedule_config("crontab", {"expr": "  0   8 * * *  "})
        assert out == {"expr": "0 8 * * *"}

    @pytest.mark.parametrize("raw", ["", "   ", None])
    def test_blank_expr_is_rejected(self, raw):
        with pytest.raises(SchedulerConfigError, match="expr"):
            sanitize_schedule_config("crontab", {"expr": raw})

    def test_wrong_field_count_is_rejected(self):
        with pytest.raises(SchedulerConfigError, match="expr"):
            sanitize_schedule_config("crontab", {"expr": "0 8"})


class TestSanitizeUnknownType:
    def test_unknown_type_raises(self):
        with pytest.raises(SchedulerConfigError):
            sanitize_schedule_config("hourly", {})

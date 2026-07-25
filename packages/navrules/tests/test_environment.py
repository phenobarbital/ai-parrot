from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from navrules.environment import Environment

# Saturday 2026-07-25 14:30 UTC
SATURDAY = datetime(2026, 7, 25, 14, 30, tzinfo=timezone.utc)
# Friday 2026-12-18 10:00 UTC (3rd Friday => pay period)
FRIDAY = datetime(2026, 12, 18, 10, 0, tzinfo=timezone.utc)


class TestDerivedFields:
    def test_weekend_fields(self):
        env = Environment(timestamp=SATURDAY)
        assert env.is_weekend is True
        assert env.is_weekday is False
        assert env.dow == 5
        assert env.day_of_week == "Saturday"
        assert env.quarter == "Q3"
        assert env.season == "summer"
        assert env.is_summer_season is True
        assert env.is_business_hours is False
        assert env.day_period == "afternoon"
        assert env.day == "2026-07-25"

    def test_year_end_fields(self):
        env = Environment(timestamp=FRIDAY)
        assert env.quarter == "Q4"
        assert env.is_year_end is True
        assert env.is_holiday_season is True
        assert env.is_quarter_end is True
        assert env.is_pay_period is True  # third Friday
        assert env.is_business_hours is True

    def test_days_in_month(self):
        env = Environment(timestamp=SATURDAY)
        assert env.days_in_current_month == 31
        assert env.business_days_in_month == 23


class TestConstructors:
    def test_at_with_timezone(self):
        env = Environment.at(SATURDAY, tz=ZoneInfo("America/Caracas"))
        assert env.hour == 10  # 14:30 UTC == 10:30 VET
        assert env.timezone_name == "America/Caracas"

    def test_at_naive_assumed_utc(self):
        naive = datetime(2026, 7, 25, 14, 30)
        env = Environment.at(naive, tz=ZoneInfo("UTC"))
        assert env.hour == 14

    def test_at_with_extra(self):
        env = Environment.at(SATURDAY, site="NYC-01")
        assert env.extra["site"] == "NYC-01"
        assert env["site"] == "NYC-01"


class TestMappingAccess:
    def test_getitem_field(self):
        env = Environment(timestamp=SATURDAY)
        assert env["is_weekend"] is True
        assert env["quarter"] == "Q3"

    def test_getitem_missing_raises(self):
        env = Environment(timestamp=SATURDAY)
        with pytest.raises(KeyError):
            env["nonexistent"]
        assert env.get("nonexistent") is None

    def test_extra_wins_lookup(self):
        env = Environment(timestamp=SATURDAY, extra={"quarter": "custom"})
        assert env["quarter"] == "custom"


class TestToDict:
    def test_includes_all_computed_fields(self):
        d = Environment(timestamp=SATURDAY).to_dict()
        # Historic keys preserved
        for key in (
            "hour", "day_of_week", "day_period", "is_weekend", "quarter",
            "season", "week_position", "is_pay_period", "work_intensity",
            "reward_timing_score",
        ):
            assert key in d
        # New: previously-omitted fields now included
        assert d["dow"] == 5
        assert d["day"] == "2026-07-25"
        assert d["curdate"] == "2026-07-25"

    def test_extra_merged_computed_wins(self):
        env = Environment(timestamp=SATURDAY, extra={"site": "X", "hour": 99})
        d = env.to_dict()
        assert d["site"] == "X"
        assert d["hour"] == 14  # computed field wins

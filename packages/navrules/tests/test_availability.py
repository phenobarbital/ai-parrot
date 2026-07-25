from datetime import datetime, timezone

from navrules import AvailabilityWindow, Environment


def env_at(month: int, day: int, hour: int = 10) -> Environment:
    return Environment(
        timestamp=datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)
    )


class TestTimeWindow:
    def test_inside_window(self):
        w = AvailabilityWindow.from_dict(
            {"start_time": "09:00:00", "end_time": "17:00:00"}
        )
        assert w.matches(env_at(7, 20, hour=10)) is True

    def test_outside_window(self):
        w = AvailabilityWindow.from_dict(
            {"start_time": "09:00:00", "end_time": "17:00:00"}
        )
        assert w.matches(env_at(7, 20, hour=20)) is False

    def test_time_requires_both_bounds(self):
        w = AvailabilityWindow.from_dict({"start_time": "09:00:00"})
        assert w.matches(env_at(7, 20, hour=20)) is True


class TestDateWindow:
    def test_day_month_window(self):
        w = AvailabilityWindow.from_dict(
            {"start_date": "01-11", "end_date": "31-12"}
        )
        assert w.matches(env_at(12, 15)) is True
        assert w.matches(env_at(7, 15)) is False

    def test_slash_format_tolerated(self):
        w = AvailabilityWindow.from_dict(
            {"start_date": "01/11", "end_date": "31/12"}
        )
        assert w.matches(env_at(11, 20)) is True


class TestAttributeMatching:
    def test_scalar_equality(self):
        w = AvailabilityWindow.from_dict({"is_weekend": False})
        assert w.matches(env_at(7, 20)) is True  # Monday
        assert w.matches(env_at(7, 25)) is False  # Saturday

    def test_list_membership(self):
        w = AvailabilityWindow.from_dict({"quarter": ["Q3", "Q4"]})
        assert w.matches(env_at(8, 1)) is True
        assert w.matches(env_at(2, 1)) is False

    def test_range_membership(self):
        w = AvailabilityWindow(matches_attrs={"hour": range(9, 17)})
        assert w.matches(env_at(7, 20, hour=10)) is True
        assert w.matches(env_at(7, 20, hour=18)) is False

    def test_unknown_attr_never_matches(self):
        w = AvailabilityWindow.from_dict({"no_such_field": 1})
        assert w.matches(env_at(7, 20)) is False

    def test_extra_env_values_matchable(self):
        w = AvailabilityWindow.from_dict({"site": "NYC-01"})
        env = Environment(
            timestamp=datetime(2026, 7, 20, tzinfo=timezone.utc),
            extra={"site": "NYC-01"},
        )
        assert w.matches(env) is True

    def test_empty_availability_always_matches(self):
        w = AvailabilityWindow.from_dict({})
        assert w.matches(env_at(1, 1)) is True
        assert AvailabilityWindow.from_dict(None).matches(env_at(1, 1)) is True

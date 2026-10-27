from datetime import date
import pytest
from parrot.metrics.models import ComparisonPolicy
from parrot_tools.metrics.periods import comparison_period, resolve_period, series_buckets

TODAY = date(2026, 10, 27)


@pytest.mark.parametrize("preset,start,end", [
    ("today", TODAY, TODAY),
    ("yesterday", date(2026, 10, 26), date(2026, 10, 26)),
    ("this_week", date(2026, 10, 26), date(2026, 11, 1)),  # Week of Monday Oct 26 to Sunday Nov 1
    ("last_week", date(2026, 10, 19), date(2026, 10, 25)),  # Previous week Monday Oct 19 to Sunday Oct 25
    ("this_month", date(2026, 10, 1), date(2026, 10, 31)),
    ("last_month", date(2026, 9, 1), date(2026, 9, 30)),
    ("mtd", date(2026, 10, 1), TODAY),
    ("qtd", date(2026, 10, 1), TODAY),  # Q4 2026 QTD
    ("ytd", date(2026, 1, 1), TODAY),
    ("last_7d", date(2026, 10, 21), TODAY),
    ("last_30d", date(2026, 9, 28), TODAY),
    ("last_90d", date(2026, 7, 30), TODAY),
    ("this_year", date(2026, 1, 1), date(2026, 12, 31)),
    ("last_year", date(2025, 1, 1), date(2025, 12, 31)),
])
def test_resolve_period_presets(preset, start, end):
    p = resolve_period(preset, today=TODAY)
    assert (p.start, p.end) == (start, end)


def test_resolve_period_labels():
    # Test some specific labels
    assert resolve_period("today", today=TODAY).label == "October 27, 2026"
    assert resolve_period("yesterday", today=TODAY).label == "October 26, 2026"
    assert resolve_period("this_month", today=TODAY).label == "October 2026"
    assert resolve_period("last_7d", today=TODAY).label == "Last 7 days"
    assert resolve_period("this_year", today=TODAY).label == "2026"


def test_udf_keywords_only_expressible():
    assert resolve_period("today", today=TODAY).udf_keywords == {"start": "TODAY", "end": "TODAY"}
    assert resolve_period("yesterday", today=TODAY).udf_keywords == {"start": "YESTERDAY", "end": "YESTERDAY"}
    assert resolve_period("this_month", today=TODAY).udf_keywords == {"start": "FDOM", "end": "LDOM"}
    assert resolve_period("mtd", today=TODAY).udf_keywords == {"start": "FDOM", "end": "TODAY"}
    assert resolve_period("last_month", today=TODAY).udf_keywords is None
    assert resolve_period("ytd", today=TODAY).udf_keywords is None
    assert resolve_period("ytd", today=TODAY, single_placeholder=True).udf_keywords == {"start": "CURRENT_YEAR"}
    assert resolve_period("this_year", today=TODAY).udf_keywords is None
    assert resolve_period("this_year", today=TODAY, single_placeholder=True).udf_keywords == {"start": "CURRENT_YEAR"}
    assert resolve_period("last_year", today=TODAY).udf_keywords is None
    assert resolve_period("last_year", today=TODAY, single_placeholder=True).udf_keywords == {"start": "LAST_YEAR"}


def test_comparison_period_modes():
    cur = resolve_period("this_month", today=TODAY)
    prev = comparison_period(cur, ComparisonPolicy(mode="previous_period"))
    assert prev is not None
    assert prev.end == date(2026, 9, 30)
    assert prev.start == date(2026, 8, 31)  # Same length (31 days) ending the day before Oct 1
    assert comparison_period(cur, ComparisonPolicy(mode="none")) is None
    
    # Test same_period_last_year
    last_year = comparison_period(cur, ComparisonPolicy(mode="same_period_last_year"))
    assert last_year is not None
    assert last_year.start == date(2025, 10, 1)
    assert last_year.end == date(2025, 10, 31)


def test_comparison_period_leap_year():
    # Feb 29 in a leap year
    leap_day = date(2024, 2, 29)
    cur = resolve_period("today", today=leap_day)
    # Should handle Feb 29 -> Feb 28 correctly
    last_year = comparison_period(cur, ComparisonPolicy(mode="same_period_last_year"))
    assert last_year is not None
    assert last_year.start == date(2023, 2, 28)
    assert last_year.end == date(2023, 2, 28)


def test_comparison_period_custom_label():
    cur = resolve_period("this_month", today=TODAY)
    prev = comparison_period(cur, ComparisonPolicy(mode="previous_period", label="Previous Month"))
    assert prev is not None
    assert prev.label == "Previous Month"


def test_series_buckets_day():
    p = resolve_period("last_7d", today=TODAY)
    buckets = series_buckets(p, "day")
    assert len(buckets) == 7
    assert buckets[0] == date(2026, 10, 21)
    assert buckets[-1] == TODAY


def test_series_buckets_week():
    p = resolve_period("last_30d", today=TODAY)
    buckets = series_buckets(p, "week")
    # Expect weeks starting on Monday within the period
    assert len(buckets) == 5  # Roughly 4-5 weeks in 30 days
    # Check they're Mondays
    for bucket in buckets:
        assert bucket.weekday() == 0  # Monday


def test_series_buckets_month():
    p = resolve_period("last_90d", today=TODAY)
    buckets = series_buckets(p, "month")
    # Should include August, September, October (months with first days within July 30 - Oct 27)
    assert len(buckets) == 3
    assert date(2026, 8, 1) in buckets
    assert date(2026, 9, 1) in buckets
    assert date(2026, 10, 1) in buckets


def test_series_buckets_quarter():
    # Test with a longer period to see multiple quarters
    p = resolve_period("last_30d", today=date(2026, 10, 27))  # Ends in Q4
    buckets = series_buckets(p, "quarter")
    # Just Q4 2026 since the period is only 30 days
    assert len(buckets) >= 1
    # Should start on first day of quarter
    for bucket in buckets:
        assert bucket.month in [1, 4, 7, 10]  # First month of each quarter
        assert bucket.day == 1


def test_series_buckets_year():
    p = resolve_period("ytd", today=TODAY)
    buckets = series_buckets(p, "year")
    assert len(buckets) == 1
    assert buckets[0] == date(2026, 1, 1)
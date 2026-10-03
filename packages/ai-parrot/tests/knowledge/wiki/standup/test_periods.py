"""Regression cases for FEAT-627 period windows."""

from datetime import date
from pathlib import Path

import pytest

import parrot.knowledge.wiki.standup.periods as subject
from parrot.knowledge.wiki.project import StandupConfig


def test_day_week_month_boundaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Day horizon, week-start variants, leap month and year boundary are inclusive."""
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = StandupConfig(horizon_days=3)
    day = subject.window("day", date(2026, 1, 2), cfg)
    assert (day.start, day.end) == (date(2025, 12, 30), date(2026, 1, 5))
    assert (day.recent_start, day.upcoming_end) == (day.start, day.end)

    # 2026-10-03 is a Saturday.
    mon = subject.window("week", date(2026, 10, 3), cfg)
    assert (mon.start, mon.end) == (date(2026, 9, 28), date(2026, 10, 4))
    sun = subject.window("week", date(2026, 10, 3), StandupConfig(week_start="sunday"))
    assert (sun.start, sun.end) == (date(2026, 9, 27), date(2026, 10, 3))
    # A Sunday anchor starts its own week when Sunday-start.
    sun2 = subject.window("week", date(2026, 10, 4), StandupConfig(week_start="sunday"))
    assert (sun2.start, sun2.end) == (date(2026, 10, 4), date(2026, 10, 10))
    assert (mon.recent_start, mon.upcoming_end) == (mon.start, mon.end)

    leap = subject.window("month", date(2024, 2, 10), cfg)
    assert (leap.start, leap.end) == (date(2024, 2, 1), date(2024, 2, 29))
    dec = subject.window("month", date(2025, 12, 31), cfg)
    assert (dec.start, dec.end) == (date(2025, 12, 1), date(2025, 12, 31))

    with pytest.raises(ValueError):
        subject.window("year", date(2026, 1, 1), cfg)  # type: ignore[arg-type]


def test_stable_period_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Brief IDs converge for every date in a week or month and follow the Q9 formats."""
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = StandupConfig()
    assert subject.window("day", date(2026, 3, 9), cfg).brief_id == "brief:daily:2026-03-09"
    ids = {subject.window("week", date(2026, 1, d), cfg).brief_id for d in range(5, 12)}
    assert ids == {"brief:weekly:2026-W02"}
    # Year boundary: Mon 2025-12-29 .. Sun 2026-01-04 is ISO 2026-W01.
    assert {subject.window("week", d, cfg).brief_id for d in (date(2025, 12, 29), date(2026, 1, 4))} == {
        "brief:weekly:2026-W01"
    }
    sun_cfg = StandupConfig(week_start="sunday")
    # Sunday-start week Sun 2025-12-28 .. Sat 2026-01-03 converges to one id.
    sun_ids = {
        subject.window("week", date(2025, 12, 28 + i) if i < 4 else date(2026, 1, i - 3), sun_cfg).brief_id
        for i in range(7)
    }
    assert len(sun_ids) == 1
    months = {subject.window("month", date(2026, 2, d), cfg).brief_id for d in (1, 14, 28)}
    assert months == {"brief:monthly:2026-02"}

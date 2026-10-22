"""Pure calendar windows for deterministic brief identities."""

import calendar
from datetime import date, timedelta

from parrot.knowledge.wiki.project import StandupConfig
from parrot.knowledge.wiki.standup.models import Period, PeriodWindow


def window(period: Period, anchor: date, cfg: StandupConfig) -> PeriodWindow:
    """Compute inclusive period and horizon bounds from an already-local anchor.

    Args:
        period: ``day``, ``week`` or ``month``.
        anchor: Calendar date already resolved in the configured timezone.
        cfg: Standup settings (``horizon_days`` and ``week_start``).

    Returns:
        The inclusive window with stable ``brief_id``.

    Raises:
        ValueError: If ``period`` is not supported.
    """
    if period == "day":
        horizon = timedelta(days=cfg.horizon_days)
        return PeriodWindow(
            period=period,
            anchor=anchor,
            start=anchor - horizon,
            end=anchor + horizon,
            recent_start=anchor - horizon,
            upcoming_end=anchor + horizon,
            brief_id=f"brief:daily:{anchor.isoformat()}",
        )
    if period == "week":
        # Monday=0 ... Sunday=6; Sunday-start weeks begin the day after Saturday.
        offset = anchor.weekday() if cfg.week_start == "monday" else (anchor.weekday() + 1) % 7
        start = anchor - timedelta(days=offset)
        end = start + timedelta(days=6)
        iso_year, iso_week, _ = start.isocalendar()
        return PeriodWindow(
            period=period,
            anchor=anchor,
            start=start,
            end=end,
            recent_start=start,
            upcoming_end=end,
            brief_id=f"brief:weekly:{iso_year}-W{iso_week:02d}",
        )
    if period == "month":
        start = anchor.replace(day=1)
        end = anchor.replace(day=calendar.monthrange(anchor.year, anchor.month)[1])
        return PeriodWindow(
            period=period,
            anchor=anchor,
            start=start,
            end=end,
            recent_start=start,
            upcoming_end=end,
            brief_id=f"brief:monthly:{anchor.year:04d}-{anchor.month:02d}",
        )
    raise ValueError(f"Unsupported period {period!r}")

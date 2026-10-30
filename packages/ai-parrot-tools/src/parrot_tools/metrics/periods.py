"""Period presets → concrete date windows (spec §7 'Period resolution', binding)."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from parrot.metrics.models import ComparisonPolicy, Grain, PeriodPreset, ResolvedPeriod


def resolve_period(
    preset: PeriodPreset, *, today: date | None = None, grain: Grain = "month", single_placeholder: bool = False
) -> ResolvedPeriod:
    """Concrete inclusive ``start``/``end`` for ``preset``; ``udf_keywords`` only for expressible presets."""
    today = today or date.today()

    if preset == "today":
        return ResolvedPeriod(
            preset=preset,
            start=today,
            end=today,
            label=today.strftime("%B %d, %Y"),
            udf_keywords={"start": "TODAY", "end": "TODAY"},
        )
    elif preset == "yesterday":
        yesterday = today - timedelta(days=1)
        return ResolvedPeriod(
            preset=preset,
            start=yesterday,
            end=yesterday,
            label=yesterday.strftime("%B %d, %Y"),
            udf_keywords={"start": "YESTERDAY", "end": "YESTERDAY"},
        )
    elif preset == "this_week":
        # ISO week starts on Monday
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        return ResolvedPeriod(
            preset=preset, start=monday, end=sunday, label=f"Week of {monday.strftime('%B %d, %Y')}", udf_keywords=None
        )
    elif preset == "last_week":
        # Previous ISO week
        last_sunday = today - timedelta(days=today.weekday() + 1)
        last_monday = last_sunday - timedelta(days=6)
        return ResolvedPeriod(
            preset=preset,
            start=last_monday,
            end=last_sunday,
            label=f"Week of {last_monday.strftime('%B %d, %Y')}",
            udf_keywords=None,
        )
    elif preset == "this_month":
        first_day = date(today.year, today.month, 1)
        last_day = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
        return ResolvedPeriod(
            preset=preset,
            start=first_day,
            end=last_day,
            label=today.strftime("%B %Y"),
            udf_keywords={"start": "FDOM", "end": "LDOM"},
        )
    elif preset == "last_month":
        if today.month == 1:
            last_month_first = date(today.year - 1, 12, 1)
        else:
            last_month_first = date(today.year, today.month - 1, 1)
        last_month_last = date(today.year, today.month, 1) - timedelta(days=1)
        return ResolvedPeriod(
            preset=preset,
            start=last_month_first,
            end=last_month_last,
            label=last_month_first.strftime("%B %Y"),
            udf_keywords=None,
        )
    elif preset == "mtd":
        first_day = date(today.year, today.month, 1)
        return ResolvedPeriod(
            preset=preset,
            start=first_day,
            end=today,
            label=f"{today.strftime('%B %Y')} MTD",
            udf_keywords={"start": "FDOM", "end": "TODAY"},
        )
    elif preset == "qtd":
        # Determine quarter
        quarter = (today.month - 1) // 3 + 1
        quarter_start_month = (quarter - 1) * 3 + 1
        first_day = date(today.year, quarter_start_month, 1)
        return ResolvedPeriod(
            preset=preset, start=first_day, end=today, label=f"Q{quarter} {today.year} QTD", udf_keywords=None
        )
    elif preset == "ytd":
        first_day = date(today.year, 1, 1)
        if single_placeholder:
            return ResolvedPeriod(
                preset=preset,
                start=first_day,
                end=today,
                label=f"{today.year} YTD",
                udf_keywords={"start": "CURRENT_YEAR"},
            )
        else:
            return ResolvedPeriod(
                preset=preset, start=first_day, end=today, label=f"{today.year} YTD", udf_keywords=None
            )
    elif preset == "last_7d":
        start = today - timedelta(days=6)
        return ResolvedPeriod(preset=preset, start=start, end=today, label="Last 7 days", udf_keywords=None)
    elif preset == "last_30d":
        start = today - timedelta(days=29)
        return ResolvedPeriod(preset=preset, start=start, end=today, label="Last 30 days", udf_keywords=None)
    elif preset == "last_90d":
        start = today - timedelta(days=89)
        return ResolvedPeriod(preset=preset, start=start, end=today, label="Last 90 days", udf_keywords=None)
    elif preset == "this_year":
        first_day = date(today.year, 1, 1)
        last_day = date(today.year, 12, 31)
        if single_placeholder:
            return ResolvedPeriod(
                preset=preset,
                start=first_day,
                end=last_day,
                label=str(today.year),
                udf_keywords={"start": "CURRENT_YEAR"},
            )
        else:
            return ResolvedPeriod(
                preset=preset, start=first_day, end=last_day, label=str(today.year), udf_keywords=None
            )
    elif preset == "last_year":
        first_day = date(today.year - 1, 1, 1)
        last_day = date(today.year - 1, 12, 31)
        if single_placeholder:
            return ResolvedPeriod(
                preset=preset,
                start=first_day,
                end=last_day,
                label=str(today.year - 1),
                udf_keywords={"start": "LAST_YEAR"},
            )
        else:
            return ResolvedPeriod(
                preset=preset, start=first_day, end=last_day, label=str(today.year - 1), udf_keywords=None
            )
    else:
        raise ValueError(f"Unknown period preset: {preset}")


def comparison_period(period: ResolvedPeriod, policy: ComparisonPolicy) -> ResolvedPeriod | None:
    """previous_period → same length right before; same_period_last_year → shifted one year; none → ``None``."""
    if policy.mode == "none":
        return None

    if policy.mode == "previous_period":
        # Same length ending the day before period.start
        period_length = (period.end - period.start).days + 1
        new_end = period.start - timedelta(days=1)
        new_start = new_end - timedelta(days=period_length - 1)

        # Format label as ISO range
        label = f"{new_start.isoformat()} – {new_end.isoformat()}"
        if policy.label:
            label = policy.label

        return ResolvedPeriod(preset=period.preset, start=new_start, end=new_end, label=label, udf_keywords=None)

    elif policy.mode == "same_period_last_year":
        # Shift both bounds by one year
        try:
            new_start = date(period.start.year - 1, period.start.month, period.start.day)
            new_end = date(period.end.year - 1, period.end.month, period.end.day)
        except ValueError:
            # Handle leap year edge case (Feb 29 -> Feb 28)
            if period.start.month == 2 and period.start.day == 29:
                new_start = date(period.start.year - 1, 2, 28)
            else:
                new_start = date(period.start.year - 1, period.start.month, period.start.day)

            if period.end.month == 2 and period.end.day == 29:
                new_end = date(period.end.year - 1, 2, 28)
            else:
                new_end = date(period.end.year - 1, period.end.month, period.end.day)

        # Format label as ISO range
        label = f"{new_start.isoformat()} – {new_end.isoformat()}"
        if policy.label:
            label = policy.label

        return ResolvedPeriod(preset=period.preset, start=new_start, end=new_end, label=label, udf_keywords=None)

    else:
        raise ValueError(f"Unknown comparison policy mode: {policy.mode}")


def series_buckets(period: ResolvedPeriod, grain: Grain) -> list[date]:
    """Sorted bucket start dates covering ``period`` at ``grain`` (zero-fill skeleton for KPICard ``series``)."""
    buckets: list[date] = []
    current = period.start

    if grain == "day":
        while current <= period.end:
            buckets.append(current)
            current += timedelta(days=1)
    elif grain == "week":
        # ISO weeks start on Monday
        # Find the Monday of the week containing the start date
        monday = period.start - timedelta(days=period.start.weekday())
        current = monday
        while current <= period.end:
            if current >= period.start:  # Only include weeks that start on or after the period start
                buckets.append(current)
            current += timedelta(weeks=1)
    elif grain == "month":
        # First day of each month
        current_month = date(period.start.year, period.start.month, 1)
        while current_month <= period.end:
            if current_month >= period.start:  # Only include months that start on or after the period start
                buckets.append(current_month)
            if current_month.month == 12:
                current_month = date(current_month.year + 1, 1, 1)
            else:
                current_month = date(current_month.year, current_month.month + 1, 1)
    elif grain == "quarter":
        # First day of each quarter
        quarter = (period.start.month - 1) // 3 + 1
        quarter_start_month = (quarter - 1) * 3 + 1
        current_quarter = date(period.start.year, quarter_start_month, 1)
        while current_quarter <= period.end:
            if current_quarter >= period.start:  # Only include quarters that start on or after the period start
                buckets.append(current_quarter)
            if quarter_start_month == 10:
                current_quarter = date(current_quarter.year + 1, 1, 1)
                quarter_start_month = 1
            else:
                quarter_start_month += 3
                current_quarter = date(current_quarter.year, quarter_start_month, 1)
    elif grain == "year":
        # First day of each year
        current_year = date(period.start.year, 1, 1)
        while current_year <= period.end:
            if current_year >= period.start:  # Only include years that start on or after the period start
                buckets.append(current_year)
            current_year = date(current_year.year + 1, 1, 1)

    return sorted(buckets)

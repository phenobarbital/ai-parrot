"""Evaluation environment: temporal/ambient context shared by every rule.

Ported 1:1 from nav-rewards ``rewards/env/env.py`` (field names preserved so
existing condition definitions keep working), reimplemented as a stdlib
dataclass to keep the package dependency-free and construction cheap — a
payrate clock-out flow creates one Environment per event.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any, Literal, Optional


def utcnow() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(tz=timezone.utc)


@dataclass
class Environment:
    """Environment context for rule evaluation.

    All temporal fields are auto-computed from ``timestamp`` during
    initialization.  Only ``timestamp``, ``connection``, ``cache`` and
    ``extra`` are caller-supplied.

    Attributes:
        timestamp: Seed datetime every derived field is computed from.
        connection: Optional resource (e.g. a DB pool) exposed to rules.
        cache: Optional cache client (e.g. Redis) exposed to rules.
        extra: Free-form ambient values (site, tz name, business flags...).
    """

    timestamp: datetime = field(default_factory=utcnow)
    connection: Optional[Any] = None
    cache: Optional[Any] = None
    extra: dict[str, Any] = field(default_factory=dict)

    # --- computed temporal fields (populated in __post_init__) ---
    curtime: Optional[time] = field(init=False, default=None)
    dow: int = field(init=False, default=0)
    day_of_week: str = field(init=False, default="")
    day: str = field(init=False, default="")
    hour: int = field(init=False, default=0)
    curdate: Optional[date] = field(init=False, default=None)
    month: int = field(init=False, default=0)
    month_name: str = field(init=False, default="")
    year: int = field(init=False, default=0)

    day_period: Literal[
        "morning", "noon", "afternoon", "evening", "night"
    ] = field(init=False, default="morning")
    is_business_hours: bool = field(init=False, default=False)
    is_weekend: bool = field(init=False, default=False)
    is_weekday: bool = field(init=False, default=True)
    quarter: Literal["Q1", "Q2", "Q3", "Q4"] = field(init=False, default="Q1")
    season: Literal["spring", "summer", "fall", "winter"] = field(
        init=False, default="winter"
    )
    week_of_year: int = field(init=False, default=1)
    days_until_weekend: int = field(init=False, default=0)
    days_since_weekend: int = field(init=False, default=0)
    is_month_start: bool = field(init=False, default=False)
    is_month_end: bool = field(init=False, default=False)
    is_quarter_end: bool = field(init=False, default=False)
    is_year_end: bool = field(init=False, default=False)
    days_in_current_month: int = field(init=False, default=30)
    business_days_in_month: int = field(init=False, default=0)
    business_days_remaining: int = field(init=False, default=0)
    is_holiday_season: bool = field(init=False, default=False)
    is_summer_season: bool = field(init=False, default=False)
    week_position: Literal["first", "second", "third", "fourth", "last"] = field(
        init=False, default="first"
    )
    is_pay_period: bool = field(init=False, default=False)
    timezone_name: str = field(init=False, default="UTC")

    def __post_init__(self) -> None:
        ts = self.timestamp

        self.hour = ts.hour
        self.dow = ts.weekday()
        self.day_of_week = ts.strftime("%A")
        self.curdate = ts.date()
        self.curtime = ts.time()
        self.day = self.curdate.strftime("%Y-%m-%d")
        self.month = ts.month
        self.month_name = ts.strftime("%B")
        self.year = ts.year

        self.day_period = self._calculate_day_period()
        self.is_weekend = self.dow >= 5
        self.is_weekday = not self.is_weekend
        self.is_business_hours = self._is_business_hours()
        self.quarter = self._get_quarter()
        self.season = self._get_season()
        self.week_of_year = ts.isocalendar()[1]
        self.days_until_weekend = self._days_until_weekend()
        self.days_since_weekend = self._days_since_weekend()
        self.days_in_current_month = calendar.monthrange(self.year, self.month)[1]
        self.is_month_start = self.curdate.day <= 3
        self.is_month_end = self._is_month_end()
        self.is_quarter_end = self.month in (3, 6, 9, 12)
        self.is_year_end = self.month == 12
        self.business_days_in_month = self._count_business_days_in_month()
        self.business_days_remaining = self._count_business_days_remaining()
        self.is_holiday_season = self.month in (11, 12)
        self.is_summer_season = self.month in (6, 7, 8)
        self.week_position = self._get_week_position()
        self.is_pay_period = self._is_pay_period()
        self.timezone_name = self._get_timezone_name()

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------
    @classmethod
    def at(
        cls,
        timestamp: datetime,
        tz: Optional[tzinfo] = None,
        **resources: Any,
    ) -> "Environment":
        """Build an Environment at a given instant.

        Args:
            timestamp: The instant to evaluate at (e.g. a clock-out time).
            tz: If given, ``timestamp`` is converted to this timezone before
                derived fields are computed (naive timestamps are assumed UTC).
            **resources: ``connection``, ``cache`` and/or ``extra`` values.

        Returns:
            A fully computed Environment.
        """
        if tz is not None:
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            timestamp = timestamp.astimezone(tz)
        extra = resources.pop("extra", {})
        return cls(
            timestamp=timestamp,
            connection=resources.pop("connection", None),
            cache=resources.pop("cache", None),
            extra={**extra, **resources},
        )

    # ------------------------------------------------------------------
    # Mapping-style access (used by AvailabilityWindow and condition DSL)
    # ------------------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        if key in self.extra:
            return self.extra[key]
        try:
            return getattr(self, key)
        except AttributeError as exc:
            raise KeyError(key) from exc

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: str) -> bool:
        return key in self.extra or hasattr(self, key)

    # ------------------------------------------------------------------
    # Private helpers (ported verbatim)
    # ------------------------------------------------------------------
    def _calculate_day_period(self) -> str:
        """Calculate the period of day based on hour."""
        hour = self.timestamp.hour
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 13:
            return "noon"
        elif 13 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 21:
            return "evening"
        return "night"

    def _is_business_hours(self) -> bool:
        """Check if current time is within business hours (9-17, weekdays)."""
        return False if self.is_weekend else 9 <= self.hour < 17

    def _get_quarter(self) -> str:
        """Get the business quarter."""
        if self.month <= 3:
            return "Q1"
        elif self.month <= 6:
            return "Q2"
        elif self.month <= 9:
            return "Q3"
        return "Q4"

    def _get_season(self) -> str:
        """Get the meteorological season."""
        if self.month in (12, 1, 2):
            return "winter"
        elif self.month in (3, 4, 5):
            return "spring"
        elif self.month in (6, 7, 8):
            return "summer"
        return "fall"

    def _days_until_weekend(self) -> int:
        """Calculate days until next weekend (Saturday)."""
        return 0 if self.is_weekend else 5 - self.dow

    def _days_since_weekend(self) -> int:
        """Calculate days since last weekend ended (Sunday)."""
        if self.dow == 6:  # Sunday
            return 0
        elif self.dow == 5:  # Saturday
            return 6
        return self.dow + 1

    def _is_month_end(self) -> bool:
        """Check if we're in the last 3 days of the month."""
        return self.curdate.day > self.days_in_current_month - 3

    def _count_business_days_in_month(self) -> int:
        """Count business days (Mon-Fri) in current month."""
        first_day = self.curdate.replace(day=1)
        last_day = self.curdate.replace(day=self.days_in_current_month)
        business_days = 0
        current_day = first_day
        while current_day <= last_day:
            if current_day.weekday() < 5:
                business_days += 1
            current_day += timedelta(days=1)
        return business_days

    def _count_business_days_remaining(self) -> int:
        """Count remaining business days in current month."""
        last_day = self.curdate.replace(day=self.days_in_current_month)
        business_days = 0
        current_day = self.curdate + timedelta(days=1)
        while current_day <= last_day:
            if current_day.weekday() < 5:
                business_days += 1
            current_day += timedelta(days=1)
        return business_days

    def _get_week_position(self) -> str:
        """Get the position of current week in the month."""
        week_number = ((self.curdate.day - 1) // 7) + 1
        if self.curdate.day > self.days_in_current_month - 7:
            return "last"
        positions = ["first", "second", "third", "fourth", "last"]
        return positions[min(week_number - 1, 3)]

    def _is_pay_period(self) -> bool:
        """Check if we're in a typical bi-weekly pay period end."""
        if self.dow == 4:  # Friday
            friday_count = 0
            for day_num in range(1, self.curdate.day + 1):
                test_date = self.curdate.replace(day=day_num)
                if test_date.weekday() == 4:
                    friday_count += 1
            return friday_count in (1, 3)
        return False

    def _get_timezone_name(self) -> str:
        """Get timezone name if available."""
        try:
            if self.timestamp.tzinfo:
                return str(self.timestamp.tzinfo)
            return "UTC"
        except Exception:
            return "UTC"

    # ------------------------------------------------------------------
    # Public utility methods (ported verbatim)
    # ------------------------------------------------------------------
    def is_milestone_day(self) -> bool:
        """Check if today is a milestone day (1st, 15th, last day)."""
        return self.curdate.day in (1, 15, self.days_in_current_month)

    def is_mid_week(self) -> bool:
        """Check if today is mid-week (Tue, Wed, Thu)."""
        return self.dow in (1, 2, 3)

    def is_week_start(self) -> bool:
        """Check if today is start of work week (Monday)."""
        return self.dow == 0

    def is_week_end(self) -> bool:
        """Check if today is end of work week (Friday)."""
        return self.dow == 4

    def get_work_intensity(self) -> Literal["low", "medium", "high"]:
        """Get subjective work intensity based on day and time."""
        if self.is_weekend:
            return "low"
        elif self.is_month_end or self.is_quarter_end:
            return "high"
        elif self.day_period in ("morning", "afternoon") and self.is_weekday:
            return "high"
        elif self.day_period in ("evening", "night"):
            return "low"
        return "medium"

    def get_reward_timing_score(self) -> int:
        """Get a score (1-10) indicating how good the timing is for awards."""
        score = 5
        if self.day_period in ("morning", "noon"):
            score += 2
        if self.is_weekday:
            score += 1
        if self.is_month_start:
            score += 1
        if self.dow == 4:  # Friday
            score += 2
        if self.day_period == "night":
            score -= 2
        if self.is_weekend:
            score -= 1
        if self.is_month_end and not self.is_quarter_end:
            score -= 1
        return max(1, min(10, score))

    def to_dict(self) -> dict[str, Any]:
        """Serializable view of every derived field, for rule evaluation.

        Unlike the historical rewards implementation, this includes ALL
        computed fields (dow, day, curdate, curtime included) so declarative
        conditions can reference any of them.  ``extra`` values are merged in
        (computed fields win on collision).
        """
        return {
            **self.extra,
            "hour": self.hour,
            "dow": self.dow,
            "day": self.day,
            "curdate": self.curdate.isoformat() if self.curdate else None,
            "curtime": self.curtime.isoformat() if self.curtime else None,
            "day_of_week": self.day_of_week,
            "day_period": self.day_period,
            "is_business_hours": self.is_business_hours,
            "is_weekend": self.is_weekend,
            "is_weekday": self.is_weekday,
            "quarter": self.quarter,
            "season": self.season,
            "month": self.month,
            "month_name": self.month_name,
            "year": self.year,
            "week_of_year": self.week_of_year,
            "days_until_weekend": self.days_until_weekend,
            "days_since_weekend": self.days_since_weekend,
            "is_month_start": self.is_month_start,
            "is_month_end": self.is_month_end,
            "is_quarter_end": self.is_quarter_end,
            "is_year_end": self.is_year_end,
            "days_in_current_month": self.days_in_current_month,
            "business_days_in_month": self.business_days_in_month,
            "business_days_remaining": self.business_days_remaining,
            "is_holiday_season": self.is_holiday_season,
            "is_summer_season": self.is_summer_season,
            "week_position": self.week_position,
            "is_pay_period": self.is_pay_period,
            "timezone_name": self.timezone_name,
            "work_intensity": self.get_work_intensity(),
            "reward_timing_score": self.get_reward_timing_score(),
        }

"""AvailabilityWindow: ambient/temporal applicability of a rule set.

Extraction of nav-rewards ``RewardObject.evaluate_environment`` (base.py:309):
time-of-day windows, day-month date windows, and direct attribute matching
against the Environment (scalar equality, or membership for range/list).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Optional

from .environment import Environment

_RESERVED = ("start_time", "end_time", "start_date", "end_date")


def parse_time(value: str, fmt: str = "%H:%M:%S") -> time:
    """Parse ``HH:MM:SS`` into a time object."""
    return datetime.strptime(value, fmt).time()


def parse_day_month(value: str, year: Optional[int] = None) -> date:
    """Parse a ``DD-MM`` (or ``DD/MM``) string into a date in ``year``.

    Preserves the historical rewards behavior: the year is the current year
    unless given, and both separators are tolerated.
    """
    year = year or datetime.now().year
    try:
        return datetime.strptime(f"{year}-{value}", "%Y-%d-%m").date()
    except ValueError:
        return datetime.strptime(f"{value}/{year}", "%d/%m/%Y").date()


@dataclass
class AvailabilityWindow:
    """Declarative availability constraints evaluated against an Environment.

    Attributes:
        start_time / end_time: Inclusive time-of-day window.
        start_date / end_date: Inclusive day-month window (``DD-MM``), year
            taken from the environment's timestamp.
        matches_attrs: Extra attributes matched against the environment:
            scalar => equality; list/range => membership.
    """

    start_time: Optional[time] = None
    end_time: Optional[time] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    matches_attrs: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, availability: Optional[dict]) -> "AvailabilityWindow":
        """Build a window from the JSON availability_rule dict."""
        availability = availability or {}
        start_time = end_time = None
        if "start_time" in availability and "end_time" in availability:
            start_time = parse_time(availability["start_time"])
            end_time = parse_time(availability["end_time"])
        start_date = availability.get("start_date")
        end_date = availability.get("end_date")
        if not ("start_date" in availability and "end_date" in availability):
            start_date = end_date = None
        attrs = {
            k: v for k, v in availability.items() if k not in _RESERVED
        }
        return cls(
            start_time=start_time,
            end_time=end_time,
            start_date=start_date,
            end_date=end_date,
            matches_attrs=attrs,
        )

    def matches(self, env: Environment) -> bool:
        """True when the environment falls inside every declared constraint."""
        if self.start_time is not None and self.end_time is not None:
            current = env.timestamp.time()
            if not (self.start_time <= current <= self.end_time):
                return False
        if self.start_date is not None and self.end_date is not None:
            year = env.year
            start = parse_day_month(self.start_date, year)
            end = parse_day_month(self.end_date, year)
            if not (start <= env.curdate <= end):
                return False
        for key, val in self.matches_attrs.items():
            current_value = env.get(key)
            if isinstance(val, (range, list)):
                if current_value not in val:
                    return False
            elif current_value != val:
                return False
        return True

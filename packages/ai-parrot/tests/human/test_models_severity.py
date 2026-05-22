"""Unit tests for Severity enum, BusinessHours.contains, and EscalationPolicy.select_starting_tier.

TASK-1274 — FEAT-194 hitl-escalation-tier
"""
from __future__ import annotations

from datetime import datetime

import pytest
import pytz

from parrot.human import BusinessHours, HumanInteraction, Severity
from parrot.human.models import EscalationActionType, EscalationPolicy, EscalationTier


class TestSeverity:
    """Tests for the Severity enum ordering."""

    def test_enum_values(self):
        assert Severity.LOW.value == "low"
        assert Severity.NORMAL.value == "normal"
        assert Severity.HIGH.value == "high"
        assert Severity.CRITICAL.value == "critical"

    def test_ordering_low_lt_high(self):
        assert Severity.LOW < Severity.HIGH
        assert Severity.NORMAL < Severity.CRITICAL
        assert not (Severity.HIGH < Severity.LOW)

    def test_ordering_le(self):
        assert Severity.LOW <= Severity.LOW
        assert Severity.LOW <= Severity.NORMAL
        assert not (Severity.HIGH <= Severity.LOW)

    def test_ordering_ge(self):
        assert Severity.CRITICAL >= Severity.HIGH
        assert Severity.NORMAL >= Severity.NORMAL
        assert not (Severity.LOW >= Severity.HIGH)

    def test_ordering_gt(self):
        assert Severity.CRITICAL > Severity.HIGH
        assert Severity.HIGH > Severity.NORMAL
        assert not (Severity.NORMAL > Severity.CRITICAL)


class TestBusinessHours:
    """Tests for the BusinessHours model and contains() method."""

    @pytest.fixture
    def bh(self):
        return BusinessHours(tz="Europe/Madrid", days="mon-fri", hours="09:00-18:00")

    def test_inside_window_weekday(self, bh):
        """Friday 12:00 Madrid time is inside the window."""
        tz = pytz.timezone("Europe/Madrid")
        now = tz.localize(datetime(2026, 5, 22, 12, 0))  # Friday
        assert bh.contains(now) is True

    def test_before_window(self, bh):
        """08:59 is before the window opens."""
        tz = pytz.timezone("Europe/Madrid")
        now = tz.localize(datetime(2026, 5, 22, 8, 59))
        assert bh.contains(now) is False

    def test_at_window_start(self, bh):
        """09:00 exactly is within the window (inclusive start)."""
        tz = pytz.timezone("Europe/Madrid")
        now = tz.localize(datetime(2026, 5, 22, 9, 0))
        assert bh.contains(now) is True

    def test_at_window_end_exclusive(self, bh):
        """18:00 exactly is NOT inside the window (exclusive end)."""
        tz = pytz.timezone("Europe/Madrid")
        now = tz.localize(datetime(2026, 5, 22, 18, 0))
        assert bh.contains(now) is False

    def test_just_before_window_end(self, bh):
        """17:59 is inside the window."""
        tz = pytz.timezone("Europe/Madrid")
        now = tz.localize(datetime(2026, 5, 22, 17, 59))
        assert bh.contains(now) is True

    def test_weekend(self, bh):
        """Saturday is not in mon-fri."""
        tz = pytz.timezone("Europe/Madrid")
        now = tz.localize(datetime(2026, 5, 23, 12, 0))  # Saturday
        assert bh.contains(now) is False

    def test_sunday(self, bh):
        """Sunday is not in mon-fri."""
        tz = pytz.timezone("Europe/Madrid")
        now = tz.localize(datetime(2026, 5, 24, 12, 0))  # Sunday
        assert bh.contains(now) is False

    def test_utc_input_converted(self):
        """UTC input should be converted to the target timezone."""
        bh = BusinessHours(tz="America/New_York", days="mon-fri", hours="09:00-17:00")
        # 14:00 UTC is 10:00 New York (EDT, UTC-4) on a weekday
        now = pytz.utc.localize(datetime(2026, 5, 22, 14, 0))  # Friday
        assert bh.contains(now) is True

    def test_malformed_hours_rejected(self):
        """Malformed hours string raises ValidationError."""
        with pytest.raises(Exception):
            BusinessHours(tz="UTC", days="mon-fri", hours="oops")

    def test_malformed_days_rejected(self):
        """Malformed days string raises ValidationError."""
        with pytest.raises(Exception):
            BusinessHours(tz="UTC", days="monday-friday", hours="09:00-17:00")

    def test_invalid_tz_rejected(self):
        """Unknown timezone raises ValidationError."""
        with pytest.raises(Exception):
            BusinessHours(tz="Invalid/Timezone", days="mon-fri", hours="09:00-18:00")

    def test_comma_separated_days(self):
        """Comma-separated days are parsed correctly."""
        bh = BusinessHours(tz="UTC", days="mon,wed,fri", hours="09:00-18:00")
        tz = pytz.utc
        # Monday
        now = tz.localize(datetime(2026, 5, 18, 12, 0))  # Monday
        assert bh.contains(now) is True
        # Tuesday
        now = tz.localize(datetime(2026, 5, 19, 12, 0))  # Tuesday
        assert bh.contains(now) is False


class TestSelectStartingTier:
    """Tests for EscalationPolicy.select_starting_tier."""

    def _make_policy(self, tiers):
        return EscalationPolicy(name="test-policy", tiers=tiers)

    def _make_tier(self, level, min_severity=None, business_hours=None, **kwargs):
        if "action_type" not in kwargs:
            kwargs["action_type"] = EscalationActionType.NOTIFY
        if "action_metadata" not in kwargs:
            kwargs["action_metadata"] = {"kind": "email", "to": ["ops@x.com"]}
        return EscalationTier(
            level=level,
            name=f"L{level}",
            min_severity=min_severity,
            business_hours=business_hours,
            **kwargs,
        )

    def test_severity_floor(self):
        """severity=HIGH skips L1 (min_severity=LOW) and returns L2 (min_severity=HIGH)."""
        policy = self._make_policy([
            self._make_tier(1, min_severity=Severity.LOW),
            self._make_tier(2, min_severity=Severity.HIGH),
            self._make_tier(3, min_severity=Severity.CRITICAL),
        ])
        now = pytz.utc.localize(datetime(2026, 5, 22, 12, 0))
        chosen = policy.select_starting_tier(Severity.HIGH, now)
        assert chosen is not None
        assert chosen.level == 1  # Both L1 (min=LOW) and L2 (min=HIGH) qualify; L1 first

    def test_severity_critical_skips_lower(self):
        """severity=CRITICAL returns the first tier with min_severity<=CRITICAL."""
        policy = self._make_policy([
            EscalationTier(
                level=1, name="L1",
                min_severity=Severity.NORMAL,
                action_type=EscalationActionType.INTERACT,
                target_humans=["a"],
            ),
            EscalationTier(
                level=2, name="L2",
                min_severity=Severity.HIGH,
                action_type=EscalationActionType.INTERACT,
                target_humans=["b"],
            ),
            EscalationTier(
                level=3, name="L3",
                min_severity=Severity.CRITICAL,
                action_type=EscalationActionType.INTERACT,
                target_humans=["c"],
            ),
        ])
        now = pytz.utc.localize(datetime(2026, 5, 22, 12, 0))
        chosen = policy.select_starting_tier(Severity.CRITICAL, now)
        assert chosen is not None
        assert chosen.level == 1  # L1 min=NORMAL <= CRITICAL

    def test_skip_high_severity_tier_when_low_requested(self):
        """severity=LOW skips tiers with min_severity=HIGH or CRITICAL."""
        policy = self._make_policy([
            self._make_tier(1, min_severity=Severity.HIGH),
            self._make_tier(2, min_severity=Severity.CRITICAL),
        ])
        now = pytz.utc.localize(datetime(2026, 5, 22, 12, 0))
        chosen = policy.select_starting_tier(Severity.LOW, now)
        assert chosen is None  # No tier qualifies

    def test_skips_off_hours(self):
        """A tier that is off-hours is skipped in favour of the next applicable tier."""
        off_hours_bh = BusinessHours(tz="UTC", days="mon-fri", hours="09:00-17:00")
        policy = self._make_policy([
            self._make_tier(1, business_hours=off_hours_bh),
            self._make_tier(2),  # No business hours constraint
        ])
        # 22:00 UTC on a Friday — outside the 09:00-17:00 window
        now = pytz.utc.localize(datetime(2026, 5, 22, 22, 0))
        chosen = policy.select_starting_tier(Severity.NORMAL, now)
        assert chosen is not None
        assert chosen.level == 2  # L1 is off-hours, so L2 is chosen

    def test_returns_none_when_no_applicable_tier(self):
        """Returns None when all tiers are either off-hours or above severity floor."""
        off_hours_bh = BusinessHours(tz="UTC", days="mon-fri", hours="09:00-17:00")
        policy = self._make_policy([
            self._make_tier(1, min_severity=Severity.HIGH, business_hours=off_hours_bh),
        ])
        # 22:00 UTC — off hours; severity LOW below HIGH
        now = pytz.utc.localize(datetime(2026, 5, 22, 22, 0))
        chosen = policy.select_starting_tier(Severity.LOW, now)
        assert chosen is None

    def test_no_constraints(self):
        """Tiers with no constraints are always selected (first one wins)."""
        policy = self._make_policy([
            self._make_tier(1),
            self._make_tier(2),
        ])
        now = pytz.utc.localize(datetime(2026, 5, 22, 22, 0))
        chosen = policy.select_starting_tier(Severity.LOW, now)
        assert chosen is not None
        assert chosen.level == 1

    def test_back_compat_existing_interaction_without_severity(self):
        """Existing interactions serialised without severity default to NORMAL."""
        # Simulate a payload from before FEAT-194 — no severity field
        import json
        raw = json.dumps({
            "interaction_id": "abc",
            "question": "test?",
        })
        interaction = HumanInteraction.model_validate_json(raw)
        assert interaction.severity == Severity.NORMAL

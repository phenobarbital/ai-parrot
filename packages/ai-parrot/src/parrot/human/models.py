"""Core data models for the Human-in-the-Loop system."""
from __future__ import annotations

import re
from datetime import datetime, time, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import pytz
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


__all__ = [
    "InteractionType",
    "InteractionStatus",
    "TimeoutAction",
    "ConsensusMode",
    "ChoiceOption",
    "EscalationActionType",
    "Severity",
    "BusinessHours",
    "EscalationTier",
    "EscalationPolicy",
    "HumanInteraction",
    "HumanResponse",
    "InteractionResult",
]

# Severity ordering for comparison
_SEVERITY_ORDER: Dict[str, int] = {
    "low": 0,
    "normal": 1,
    "high": 2,
    "critical": 3,
}


class InteractionType(str, Enum):
    """Type of interaction requested from the human."""

    FREE_TEXT = "free_text"
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    APPROVAL = "approval"
    FORM = "form"
    POLL = "poll"


class InteractionStatus(str, Enum):
    """Lifecycle status of a human interaction."""

    PENDING = "pending"
    DELIVERED = "delivered"
    PARTIAL = "partial"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"


class TimeoutAction(str, Enum):
    """Action to take when an interaction times out."""

    CANCEL = "cancel"
    DEFAULT = "default"
    ESCALATE = "escalate"
    RETRY = "retry"


class ConsensusMode(str, Enum):
    """How to consolidate responses when multiple humans are involved."""

    FIRST_RESPONSE = "first_response"
    ALL_REQUIRED = "all_required"
    MAJORITY = "majority"
    QUORUM = "quorum"


class ChoiceOption(BaseModel):
    """A selectable option presented to the human."""

    key: str
    label: str
    description: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Severity(str, Enum):
    """Declared criticality of a human-interaction request.

    Higher severity may cause the manager to skip lower-priority tiers
    and start at a more appropriate level per ``EscalationPolicy.select_starting_tier``.
    """

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"

    def __le__(self, other: "Severity") -> bool:  # type: ignore[override]
        if not isinstance(other, Severity):
            return NotImplemented
        return _SEVERITY_ORDER[self.value] <= _SEVERITY_ORDER[other.value]

    def __lt__(self, other: "Severity") -> bool:  # type: ignore[override]
        if not isinstance(other, Severity):
            return NotImplemented
        return _SEVERITY_ORDER[self.value] < _SEVERITY_ORDER[other.value]

    def __ge__(self, other: "Severity") -> bool:  # type: ignore[override]
        if not isinstance(other, Severity):
            return NotImplemented
        return _SEVERITY_ORDER[self.value] >= _SEVERITY_ORDER[other.value]

    def __gt__(self, other: "Severity") -> bool:  # type: ignore[override]
        if not isinstance(other, Severity):
            return NotImplemented
        return _SEVERITY_ORDER[self.value] > _SEVERITY_ORDER[other.value]


# Day-name to weekday index (Monday=0, Sunday=6)
_DAY_NAMES: Dict[str, int] = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}


def _parse_days(days_str: str) -> List[int]:
    """Parse a days string into a sorted list of weekday indices (0=Mon, 6=Sun).

    Accepts:
        ``"mon-fri"``   — range (inclusive)
        ``"mon,wed,fri"`` — comma-separated list
        ``"mon-sun"``   — full week range
    """
    days_str = days_str.strip().lower()
    if "-" in days_str and "," not in days_str:
        parts = days_str.split("-", 1)
        if len(parts) != 2 or parts[0] not in _DAY_NAMES or parts[1] not in _DAY_NAMES:
            raise ValueError(
                f"Invalid days range {days_str!r}. Expected format like 'mon-fri'."
            )
        start, end = _DAY_NAMES[parts[0]], _DAY_NAMES[parts[1]]
        if start <= end:
            return list(range(start, end + 1))
        # Wrap-around (e.g., "fri-mon")
        return list(range(start, 7)) + list(range(0, end + 1))
    else:
        result: List[int] = []
        for day in days_str.split(","):
            day = day.strip()
            if day not in _DAY_NAMES:
                raise ValueError(
                    f"Unknown day name {day!r}. Use mon, tue, wed, thu, fri, sat, sun."
                )
            result.append(_DAY_NAMES[day])
        return sorted(result)


def _parse_hours(hours_str: str) -> Tuple[time, time]:
    """Parse an hours string ``"HH:MM-HH:MM"`` (24h) into two :class:`time` objects."""
    pattern = r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$"
    m = re.match(pattern, hours_str.strip())
    if not m:
        raise ValueError(
            f"Invalid hours string {hours_str!r}. "
            "Expected 24-hour format like '09:00-18:00'."
        )
    sh, sm, eh, em = (int(x) for x in m.groups())
    try:
        start = time(sh, sm)
        end = time(eh, em)
    except ValueError as exc:
        raise ValueError(
            f"Invalid time values in hours string {hours_str!r}: {exc}"
        ) from exc
    return start, end


class BusinessHours(BaseModel):
    """Defines a business-hours window for an escalation tier.

    When ``EscalationTier.business_hours`` is set, the manager will only
    dispatch that tier if the *current time* (in the given timezone) falls
    within the window.  Tiers whose window is currently closed are skipped.

    Attributes:
        tz: IANA timezone name, e.g. ``"Europe/Madrid"``.
        days: Day range or list, e.g. ``"mon-fri"`` or ``"mon,wed,fri"``.
        hours: 24-hour window, e.g. ``"09:00-18:00"``.

    Example::

        bh = BusinessHours(tz="Europe/Madrid", days="mon-fri", hours="09:00-18:00")
        bh.contains(datetime.now(pytz.timezone("Europe/Madrid")))
    """

    tz: str = Field(..., description="IANA timezone name, e.g. 'Europe/Madrid'")
    days: str = Field(..., description="Day range: 'mon-fri', 'mon,wed,fri', 'mon-sun'")
    hours: str = Field(..., description="24-hour window: '09:00-18:00'")

    @field_validator("tz")
    @classmethod
    def _validate_tz(cls, v: str) -> str:
        try:
            pytz.timezone(v)
        except pytz.UnknownTimeZoneError:
            raise ValueError(f"Unknown timezone {v!r}. Use an IANA timezone name.")
        return v

    @field_validator("days")
    @classmethod
    def _validate_days(cls, v: str) -> str:
        _parse_days(v)  # raises ValueError on malformed input
        return v

    @field_validator("hours")
    @classmethod
    def _validate_hours(cls, v: str) -> str:
        _parse_hours(v)  # raises ValueError on malformed input
        return v

    def contains(self, now: datetime) -> bool:
        """Return True if *now* falls within this business-hours window.

        Args:
            now: A timezone-aware datetime (or naive UTC will be treated as UTC).

        Returns:
            ``True`` if the day-of-week and time-of-day match the window.
        """
        tz = pytz.timezone(self.tz)
        if now.tzinfo is None:
            now = pytz.utc.localize(now)
        local_now = now.astimezone(tz)

        # Check weekday (0=Monday, 6=Sunday)
        valid_days = _parse_days(self.days)
        if local_now.weekday() not in valid_days:
            return False

        # Check time window
        start_t, end_t = _parse_hours(self.hours)
        current_t = local_now.time().replace(tzinfo=None)
        return start_t <= current_t < end_t


class EscalationActionType(str, Enum):
    """Actions performed when escalating to a tier."""

    INTERACT = "interact"  # Standard bi-directional interaction
    NOTIFY = "notify"  # One-way notification
    TICKET = "ticket"  # Open a ticket in an external system


class EscalationTier(BaseModel):
    """Definition of a single level in an escalation policy."""

    level: int = Field(ge=1, description="1-based tier ordering")
    name: str
    channel_type: Optional[str] = Field(
        default=None,
        description=(
            "Channel to dispatch this tier through. When None the manager "
            "falls back to the channel of the originating interaction."
        ),
    )
    target_humans: List[str] = Field(default_factory=list)
    timeout: float = Field(default=3600.0, gt=0, description="Seconds")
    action_type: EscalationActionType = EscalationActionType.INTERACT
    action_metadata: Dict[str, Any] = Field(default_factory=dict)

    # V1 completion fields (FEAT-194)
    min_severity: Optional[Severity] = Field(
        default=None,
        description=(
            "Minimum severity required to START at this tier. "
            "Tiers with min_severity > requested severity are skipped "
            "during starting-tier selection."
        ),
    )
    business_hours: Optional[BusinessHours] = Field(
        default=None,
        description=(
            "Optional business-hours window for this tier. "
            "When set, the tier is only entered if 'now' falls within the window."
        ),
    )

    @model_validator(mode="after")
    def _check_interact_has_targets(self) -> "EscalationTier":
        if (
            self.action_type == EscalationActionType.INTERACT
            and not self.target_humans
        ):
            raise ValueError(
                f"Tier {self.level} ('{self.name}') uses INTERACT but has "
                "no target_humans"
            )
        return self


class EscalationPolicy(BaseModel):
    """A series of tiered levels for escalating human-in-the-loop requests."""

    policy_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    tiers: List[EscalationTier] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_tier_levels(self) -> "EscalationPolicy":
        if not self.tiers:
            return self
        levels = sorted(t.level for t in self.tiers)
        expected = list(range(1, len(levels) + 1))
        if levels != expected:
            raise ValueError(
                f"Tier levels must be contiguous starting at 1, got {levels}"
            )
        return self

    def select_starting_tier(
        self,
        severity: "Severity",
        now: datetime,
    ) -> Optional["EscalationTier"]:
        """Return the first applicable tier for the given severity and time.

        A tier is considered applicable when:
        1. Its ``min_severity`` is <= *severity* (or ``min_severity`` is ``None``).
        2. Its ``business_hours`` window includes *now* (or ``business_hours`` is ``None``).

        Tiers are evaluated in ascending ``level`` order.  The first applicable
        tier is returned.  ``None`` is returned when no tier currently applies
        (caller should treat this as a chain-exhausted / terminal CANCEL).

        This is a **pure method** — no I/O, no logging.

        Args:
            severity: The declared criticality of the interaction.
            now: A timezone-aware datetime representing the current instant.

        Returns:
            The first applicable :class:`EscalationTier`, or ``None``.
        """
        sorted_tiers = sorted(self.tiers, key=lambda t: t.level)
        for tier in sorted_tiers:
            # Severity floor check: skip if tier requires higher severity than requested
            if tier.min_severity is not None and tier.min_severity > severity:
                continue
            # Business hours check
            if tier.business_hours is not None and not tier.business_hours.contains(now):
                continue
            return tier
        return None


class HumanInteraction(BaseModel):
    """Represents a request for human input."""

    interaction_id: str = Field(default_factory=lambda: str(uuid4()))

    # Content
    question: str
    context: Optional[str] = None
    interaction_type: InteractionType = InteractionType.FREE_TEXT
    options: Optional[List[ChoiceOption]] = None
    form_schema: Optional[Dict[str, Any]] = None
    default_response: Any = None

    # Routing
    target_humans: List[str] = Field(default_factory=list)
    consensus_mode: ConsensusMode = ConsensusMode.FIRST_RESPONSE

    # Timeout and escalation (seconds)
    timeout: float = Field(default=7200.0, gt=0)
    timeout_action: TimeoutAction = TimeoutAction.CANCEL
    escalation_targets: List[str] = Field(default_factory=list)

    # Tiered Escalation
    policy_id: Optional[str] = None
    policy: Optional[EscalationPolicy] = None
    current_tier_level: int = Field(default=0, ge=0)
    severity: Severity = Field(
        default=Severity.NORMAL,
        description=(
            "Declared criticality of this interaction. "
            "The manager uses this to select the starting tier when a policy is active."
        ),
    )

    # Traceability
    source_agent: Optional[str] = None
    source_flow: Optional[str] = None
    source_node: Optional[str] = None

    # State (managed by the engine)
    status: InteractionStatus = InteractionStatus.PENDING

    @model_validator(mode="after")
    def _check_payload(self) -> "HumanInteraction":
        """Ensure required payload fields match the interaction type."""
        if self.interaction_type == InteractionType.FORM and not self.form_schema:
            raise ValueError(
                "FORM interactions require a non-empty form_schema"
            )
        if self.interaction_type in {
            InteractionType.SINGLE_CHOICE,
            InteractionType.MULTI_CHOICE,
            InteractionType.POLL,
        } and not self.options:
            raise ValueError(
                f"{self.interaction_type.value} interactions require options"
            )
        return self


class HumanResponse(BaseModel):
    """Response from a human to an interaction.

    Note:
        ``response_type`` reuses :class:`InteractionType` to describe the
        *format* the channel actually delivered (e.g. Telegram may deliver
        a FORM as FREE_TEXT). The compatibility map lives in
        ``HumanInteractionManager._COMPATIBLE_TYPES``.
    """

    model_config = ConfigDict(extra="forbid")

    interaction_id: str
    respondent: str
    response_type: InteractionType

    # Value depends on response_type:
    #   free_text     -> str
    #   single_choice -> str (key of ChoiceOption)
    #   multi_choice  -> List[str] (keys)
    #   approval      -> bool
    #   form          -> dict
    #   poll          -> str (key)
    value: Any

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the response was captured",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_value_shape(self) -> "HumanResponse":
        """Light type-check against ``response_type``.

        Only validates the cases where the runtime shape is unambiguous
        (bool / list / dict). ``free_text`` and the *_choice text-key
        variants accept ``Any`` to stay tolerant of channel quirks.
        """
        rt = self.response_type
        v = self.value
        if rt == InteractionType.APPROVAL and not isinstance(v, bool):
            raise ValueError("approval responses must be a bool")
        if rt == InteractionType.MULTI_CHOICE and not isinstance(v, list):
            raise ValueError("multi_choice responses must be a list")
        if rt == InteractionType.FORM and not isinstance(v, dict):
            raise ValueError("form responses must be a dict")
        return self


class InteractionResult(BaseModel):
    """Consolidated result of an interaction after consensus evaluation."""

    interaction_id: str
    status: InteractionStatus
    responses: List[HumanResponse] = Field(default_factory=list)
    consolidated_value: Any = None
    timed_out: bool = False
    escalated: bool = False
    tier_level: int = Field(default=0, ge=0)
    action_metadata: Dict[str, Any] = Field(default_factory=dict)

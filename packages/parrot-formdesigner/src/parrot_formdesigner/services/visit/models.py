"""Pydantic v2 models for the Visit & Event Lifecycle (FEAT-303).

Hierarchy: ``Event`` (container) → ``Shift`` (staff assignment) →
``Visit`` (single-rep execution) → ``FormSubmission`` (recap response).

Design decisions (spec §8):
- All models use ``ConfigDict(extra="forbid")`` for strict schema enforcement.
- UUIDs are generated via ``default_factory`` so models are immutable by default.
- ``Event.meta`` carries geofence parameters (``geofence_lat``,
  ``geofence_lon``, ``geofence_radius_m``) until FEAT-302 provides a proper
  ``Location`` entity.
- ``Visit.submission_id`` is the sole FK to ``FormSubmission``; no
  ``visit_id`` column is added to ``FormSubmission``.
- Allowed state-machine transitions are encoded in ``EVENT_TRANSITIONS`` and
  ``SHIFT_TRANSITIONS`` module-level dicts.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------


class EventStatus(str, Enum):
    """Life-cycle states for an ``Event`` container."""

    REQUESTED = "requested"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    MISSED = "missed"


class ShiftStatus(str, Enum):
    """Life-cycle states for a ``Shift`` (staff assignment)."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    MISSED = "missed"


# ---------------------------------------------------------------------------
# Allowed state-machine transitions
# ---------------------------------------------------------------------------

#: Valid ``(from, to)`` pairs for ``EventStatus``.
EVENT_TRANSITIONS: dict[EventStatus, set[EventStatus]] = {
    EventStatus.REQUESTED: {EventStatus.SCHEDULED, EventStatus.CANCELLED},
    EventStatus.SCHEDULED: {
        EventStatus.IN_PROGRESS,
        EventStatus.CANCELLED,
        EventStatus.MISSED,
    },
    EventStatus.IN_PROGRESS: {
        EventStatus.COMPLETED,
        EventStatus.CANCELLED,
        EventStatus.MISSED,
    },
    EventStatus.COMPLETED: set(),
    EventStatus.CANCELLED: set(),
    EventStatus.MISSED: set(),
}

#: Valid ``(from, to)`` pairs for ``ShiftStatus``.
SHIFT_TRANSITIONS: dict[ShiftStatus, set[ShiftStatus]] = {
    ShiftStatus.PENDING: {ShiftStatus.IN_PROGRESS, ShiftStatus.MISSED},
    ShiftStatus.IN_PROGRESS: {ShiftStatus.COMPLETED, ShiftStatus.MISSED},
    ShiftStatus.COMPLETED: set(),
    ShiftStatus.MISSED: set(),
}

# ---------------------------------------------------------------------------
# Value models
# ---------------------------------------------------------------------------


class GpsCoord(BaseModel):
    """A single GPS coordinate sample.

    Attributes:
        lat: Latitude in decimal degrees (WGS-84).
        lon: Longitude in decimal degrees (WGS-84).
        accuracy_m: Optional horizontal accuracy radius in metres.
        recorded_at: Optional UTC timestamp when the sample was captured.
    """

    model_config = ConfigDict(extra="forbid")

    lat: float
    lon: float
    accuracy_m: float | None = None
    recorded_at: datetime | None = None


class MissedReason(BaseModel):
    """Tenant-scoped catalogue entry for a Missed Reason.

    Attributes:
        reason_id: Unique identifier (UUID).
        label: Human-readable label shown in the UI.
        tenant: The tenant this reason belongs to (hard isolation).
        active: Whether this reason is currently selectable.
    """

    model_config = ConfigDict(extra="forbid")

    reason_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    label: str
    tenant: str
    active: bool = True


# ---------------------------------------------------------------------------
# Core lifecycle models
# ---------------------------------------------------------------------------


class Visit(BaseModel):
    """Single-rep execution record within a Shift.

    Attributes:
        visit_id: Unique identifier (UUID).
        shift_id: FK to the parent ``Shift.shift_id``.
        check_in: UTC timestamp of check-in.
        check_out: UTC timestamp of check-out.
        check_in_coord: GPS coordinate recorded at check-in.
        check_out_coord: GPS coordinate recorded at check-out.
        gps_breadcrumb: Ordered list of GPS samples captured during the visit.
        missed_reason_id: FK to the ``MissedReason.reason_id`` (when missed).
        gps_outside: ``True`` when the rep was outside the geofence at
            checkout — submission is blocked while this flag is set.
        submission_id: FK to ``FormSubmission.submission_id`` once the recap
            is persisted. This is the sole linkage between Visit and the recap.
        meta: Arbitrary key-value metadata.
        tenant: Tenant slug for multi-tenancy.
    """

    model_config = ConfigDict(extra="forbid")

    visit_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    shift_id: str
    check_in: datetime | None = None
    check_out: datetime | None = None
    check_in_coord: GpsCoord | None = None
    check_out_coord: GpsCoord | None = None
    gps_breadcrumb: list[GpsCoord] = Field(default_factory=list)
    missed_reason_id: str | None = None
    gps_outside: bool = False
    submission_id: str | None = None
    meta: dict[str, Any] | None = None
    tenant: str | None = None


class Shift(BaseModel):
    """Staff assignment within an Event.

    Attributes:
        shift_id: Unique identifier (UUID).
        event_id: FK to the parent ``Event.event_id``.
        staff_id: FK to the user (ai-parrot auth system).
        status: Current lifecycle status.
        scheduled_start: Optional planned start time (UTC).
        scheduled_end: Optional planned end time (UTC).
        visit: The associated ``Visit`` once the shift is activated.
    """

    model_config = ConfigDict(extra="forbid")

    shift_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_id: str
    staff_id: str
    status: ShiftStatus = ShiftStatus.PENDING
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    visit: Visit | None = None


class Event(BaseModel):
    """Top-level container representing a multi-shift execution at a location.

    Attributes:
        event_id: Unique identifier (UUID).
        status: Current lifecycle status.
        org_node_id: FK to the store/program in the Org Graph (FEAT-302).
            Treated as an opaque string here.
        recap_ids: List of ``FormSchema.form_id`` values for recap forms.
        shifts: List of staff-assigned ``Shift`` objects.
        scheduled_start: Optional planned event start time (UTC).
        scheduled_end: Optional planned event end time (UTC).
        is_adhoc: ``True`` for guerrilla/ad-hoc stops (not pre-scheduled).
        tenant: Tenant slug for multi-tenancy.
        meta: Arbitrary metadata — carries geofence parameters
            (``geofence_lat``, ``geofence_lon``, ``geofence_radius_m``)
            until FEAT-302 provides a proper ``Location`` entity.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: EventStatus = EventStatus.REQUESTED
    org_node_id: str
    recap_ids: list[str] = Field(default_factory=list)
    shifts: list[Shift] = Field(default_factory=list)
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    is_adhoc: bool = False
    tenant: str | None = None
    meta: dict[str, Any] | None = None

"""Clock-event Pydantic models for Workday Time Tracking write operations.

These are pure data models with no SOAP coupling.  They are used by the
write handlers (PutTimeClockEventsType, ImportTimeClockEventsType,
ImportReportedTimeBlocksType) and by the Workday component for input
validation before any SOAP call (G7).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Clock_Event_Type constraint
# ---------------------------------------------------------------------------

ClockEventType = Literal["In", "Break", "Meal", "Out"]
"""Valid values for Clock_Event_Type_Reference per Workday WWS v46.1 docs.

This is a BUSINESS RULE, NOT a WSDL xsd:enumeration.  The Literal enforces
it at Pydantic-validation time so invalid values are rejected before any
SOAP call (G7).
"""


# ---------------------------------------------------------------------------
# ClockEvent — one time-clock event for Put_/Import_Time_Clock_Events
# ---------------------------------------------------------------------------

class ClockEvent(BaseModel):
    """One Time Clock Event for Put_Time_Clock_Events / Import_Time_Clock_Events.

    Field names mirror the Workday Time Tracking operation; all references
    are resolved to ID-typed SOAP structures inside the handler.

    Args:
        employee_id: Workday Employee_ID (required, plain xsd:string).
        event_datetime: Time_Clock_Event_Date_Time (required, xsd:dateTime).
        clock_event_type: Clock_Event_Type_Reference value — one of
            ``In``, ``Break``, ``Meal``, ``Out`` (required).
        time_clock_event_id: CLIENT-assigned Time_Clock_Event_ID.  Leave
            ``None`` to let Workday auto-generate.  This is the per-event
            identifier; Workday returns NO WID in the Put response (v46.1).
            REQUIRED when ``delete=True`` — you can only delete an event you
            can identify.
        position_id: Optional Position_ID (plain xsd:string).
        time_zone: Optional Time_Zone_Reference value (``type="Time_Zone_ID"``).
        time_entry_code: Optional Time_Entry_Code (plain xsd:string, NOT a
            reference wrapper).
        auto_submit: Whether to auto-submit for approval (default ``False``).
        comment: Optional free-text comment.
        delete: Soft-delete this event via ``Put_Time_Clock_Events``
            (emits ``Delete_Time_Clock_Event=Y``; the block stays visible
            with ``Is_Deleted=true`` on read). Requires
            ``time_clock_event_id``.
        location: Organisational location OVERRIDE (plain ``xsd:string``,
            NOT geo coordinates). Workday derives a worker's default
            location from their position; this field is the location they
            *actually* worked at — there is no separate override field.
        cost_center: Cost-centre override (plain ``xsd:string``).
        override_rate: Presence-based rate override — a value including
            ``0`` is sent, ``None`` omits it entirely.
        latitude: GPS latitude captured by a mobile client. Carried on the
            model for the calling API to persist in its own store; the
            Time Tracking WSDL has NO geo field in any version (v27.1 →
            v46.1), so this is NEVER serialised into the SOAP payload.
        longitude: GPS longitude — same caveat as ``latitude``.
    """

    employee_id: str
    event_datetime: datetime
    clock_event_type: ClockEventType
    time_clock_event_id: str | None = None
    position_id: str | None = None
    time_zone: str | None = None
    time_entry_code: str | None = None
    auto_submit: bool = False
    comment: str | None = None
    delete: bool = False
    location: str | None = None
    cost_center: str | None = None
    override_rate: float | None = Field(default=None, ge=0)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)

    @model_validator(mode="after")
    def _delete_requires_event_id(self) -> ClockEvent:
        """Ensure a delete request identifies the event it targets.

        Raises:
            ValueError: ``delete=True`` without ``time_clock_event_id``.
        """
        if self.delete and not self.time_clock_event_id:
            raise ValueError(
                "ClockEvent: delete=True requires time_clock_event_id — "
                "you can only delete an event you can identify."
            )
        return self

    class Config:
        extra = "allow"


# ---------------------------------------------------------------------------
# ReportedTimeBlock — one reported time block for Import_Reported_Time_Blocks
# ---------------------------------------------------------------------------

class ReportedTimeBlock(BaseModel):
    """One reported time block for Import_Reported_Time_Blocks.

    Args:
        employee_id: Workday Employee_ID (required).
        position_id: Optional Position_ID.
        start_datetime: Block start date/time (required).
        end_datetime: Block end date/time (optional; ISO-8601 string accepted).
        time_entry_code: Optional Time_Entry_Code (plain string).
        reported_quantity: Optional duration/quantity of time.
        comment: Optional free-text comment.
        override_rate: Override Rate used while reporting time; presence-based
            — a value including ``0`` is sent, ``None`` omits it.
    """

    employee_id: str
    position_id: str | None = None
    start_datetime: datetime
    end_datetime: str | None = None
    time_entry_code: str | None = None
    reported_quantity: float | None = None
    comment: str | None = None
    override_rate: float | None = Field(default=None, ge=0)

    class Config:
        extra = "allow"


# ---------------------------------------------------------------------------
# ClockEventResult — per-row submission outcome
# ---------------------------------------------------------------------------

class ClockEventResult(BaseModel):
    """Per-row submission outcome echoed back into the flow (G6).

    Notes:
        - ``Put_Time_Clock_Events`` returns ONLY ``Response_Text`` — no
          per-event WID (verified Workday WWS v46.1).  ``event_id`` carries
          the CLIENT-assigned ``Time_Clock_Event_ID`` we sent (echoed back);
          ``submitted``/``error`` are atomic per batch.
        - ``Import_*`` responses return a single ``Import_Process_Reference``
          (async — not awaited, see Non-Goals).  ``event_id`` is that
          reference, repeated on every row.

    Args:
        submitted: ``True`` if the event was accepted; ``False`` on fault.
        event_id: For Put — the client-assigned ``Time_Clock_Event_ID``.
            For Import — the batch ``Import_Process_Reference``.
        error: Fault message when ``submitted=False``; ``None`` on success.
    """

    submitted: bool
    event_id: str | None = None
    error: str | None = None

"""Pydantic v2 models for GigSmart engagements API surface."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


class AddEngagementInput(BaseModel, frozen=True):
    """Input for the ``addEngagement`` mutation.

    All instances are immutable (``frozen=True``) for safe passing as
    GraphQL variables.

    Args:
        gig_id: The gig to create the engagement for.
        worker_id: Optional worker to target; omit to create an open offer.
        initial_state: Optional initial engagement state.
        pay_rate: ISO-4217 money scalar override for this engagement.
        pay_schedule: Payment schedule override.
        note: Optional note to the worker.
        cancel_conflicting_engagements: Whether to cancel conflicting active engagements.
    """

    model_config = ConfigDict(populate_by_name=True)

    gig_id: str = Field(alias="gigId")
    worker_id: str | None = Field(default=None, alias="workerId")
    initial_state: Literal["OFFERED", "BID_REQUESTED", "SCHEDULED"] | None = Field(
        default=None, alias="initialState"
    )
    pay_rate: str | None = Field(default=None, alias="payRate")
    pay_schedule: Literal["FIXED", "HOURLY", "INFO_REQUIRED"] | None = Field(
        default=None, alias="paySchedule"
    )
    note: str | None = None
    cancel_conflicting_engagements: bool | None = Field(
        default=None, alias="cancelConflictingEngagements"
    )


class TransitionEngagementInput(BaseModel, frozen=True):
    """Input for the single ``transitionEngagement`` mutation.

    This is the **only** mutation for ALL engagement state changes.
    There are no separate hire, accept, cancel, or end mutations.

    Args:
        engagement_id: Opaque ID of the engagement to transition.
        action: EngagementStateAction value (e.g. ``"HIRE"``, ``"CANCEL"``,
            ``"START"``, ``"END"``, ``"APPROVE_TIMESHEET"``).
        cancel_conflicting_engagements: Whether to cancel conflicting active
            engagements when applying this transition.
    """

    model_config = ConfigDict(populate_by_name=True)

    engagement_id: str = Field(alias="engagementId")
    action: str  # EngagementStateAction — 48 values; using str for forward-compat
    cancel_conflicting_engagements: bool | None = Field(
        default=None, alias="cancelConflictingEngagements"
    )


class Engagement(BaseModel):
    """A GigSmart engagement resource linking a worker to a gig.

    Args:
        id: Opaque prefixed engagement ID (e.g. ``"eng_0WjivXE8xbrgBuEkfpANQP"``).
        gig_id: ID of the parent gig.
        worker_display_name: Worker's display name (PII — may be scrubbed in logs).
        current_state: Dict containing at least ``{"name": "<EngagementStateName>"}``.
        applied_at: Timestamp when the worker applied.
        hired_at: Timestamp when the worker was hired.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    gig_id: str | None = Field(default=None, alias="gigId")
    worker_display_name: str | None = Field(default=None, alias="workerDisplayName")
    current_state: dict = Field(alias="currentState")
    applied_at: datetime | None = Field(default=None, alias="appliedAt")
    hired_at: datetime | None = Field(default=None, alias="hiredAt")

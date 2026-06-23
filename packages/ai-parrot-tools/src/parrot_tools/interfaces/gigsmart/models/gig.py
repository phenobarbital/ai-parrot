"""Pydantic v2 models for GigSmart gigs (shifts) API surface."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


# GigStateName enum values from schema introspection:
GigStateName = Literal[
    "ACTIVE",
    "CANCELED",
    "COMPLETED",
    "DRAFT",
    "EXPIRED",
    "IN_PROGRESS",
    "INACTIVE",
    "INCOMPLETE",
    "PENDING_REVIEW",
    "RECONCILED",
    "UPCOMING",
]

# Allowed transition actions for transitionGig mutation:
GigStateAction = Literal["CANCEL", "CLOSE", "MARK_AS_COMPLETE", "PUBLISH"]


class PostShiftInput(BaseModel, frozen=True):
    """Input for the ``postShift`` mutation.

    All instances are immutable (``frozen=True``) for safe passing as
    GraphQL variables.

    Args:
        organization_id: The organisation that will host the shift.
        organization_position_id: Position template for the shift.
        organization_location_id: Physical location for the shift.
        starts_at: Shift start time (ISO-8601 datetime with timezone).
        ends_at: Shift end time (ISO-8601 datetime with timezone).
        pay_rate: ISO-4217 money scalar override (defaults to position rate).
        slots_available: Number of worker slots (minimum 1).
        description: Optional shift-specific instructions (max 5 000 chars).
        requester_id: Optional requester who manages this shift.
    """

    model_config = ConfigDict(populate_by_name=True)

    organization_id: str = Field(alias="organizationId")
    organization_position_id: str = Field(alias="organizationPositionId")
    organization_location_id: str = Field(alias="organizationLocationId")
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime = Field(alias="endsAt")
    pay_rate: str | None = Field(default=None, alias="payRate")
    slots_available: int = Field(default=1, ge=1, alias="slotsAvailable")
    description: str | None = Field(default=None, max_length=5000)
    requester_id: str | None = Field(default=None, alias="requesterId")


class TransitionGigInput(BaseModel, frozen=True):
    """Input for the ``transitionGig`` mutation.

    Args:
        gig_id: Opaque ID of the gig to transition (e.g. ``"gig_..."``).
        action: The transition action to apply.
    """

    model_config = ConfigDict(populate_by_name=True)

    gig_id: str = Field(alias="gigId")
    action: GigStateAction


class Gig(BaseModel):
    """A GigSmart shift/gig resource.

    Args:
        id: Opaque prefixed gig ID (e.g. ``"gig_9ucAiJfkccqJKbnVytgviu"``).
        name: Optional auto-generated or human-assigned shift name.
        starts_at: Shift start time.
        ends_at: Shift end time.
        current_state: Dict containing at least ``{"name": "<GigStateName>"}``.
        slots_available: Number of open worker slots.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str | None = None
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime = Field(alias="endsAt")
    current_state: dict = Field(alias="currentState")
    slots_available: int | None = Field(default=None, alias="slotsAvailable")

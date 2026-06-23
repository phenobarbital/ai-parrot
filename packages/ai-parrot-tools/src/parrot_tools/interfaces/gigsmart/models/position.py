"""Pydantic v2 models for GigSmart positions API surface."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


class AddOrganizationPositionInput(BaseModel, frozen=True):
    """Input for the ``addOrganizationPosition`` mutation.

    All instances are immutable (``frozen=True``) for safe passing as
    GraphQL variables.

    Args:
        organization_id: Target organisation ID.
        name: Position display name.
        description: Detailed position description.
        pay_rate: ISO-4217 money scalar, e.g. ``"20.00"``.
        pay_schedule: Payment schedule type.
        gig_category_id: Category ID from the GigSmart category taxonomy.
        gig_position_id: Optional position template ID.
        state: Initial position state.
        accepts_tips: Whether tips are accepted for this position.
        requires_vehicle: Whether workers need a vehicle.
        estimated_mileage: Estimated driving mileage per shift.
    """

    model_config = ConfigDict(populate_by_name=True)

    organization_id: str = Field(alias="organizationId")
    name: str | None = None
    description: str | None = None
    pay_rate: str | None = Field(default=None, alias="payRate")
    pay_schedule: Literal["FIXED", "HOURLY", "INFO_REQUIRED"] | None = Field(
        default=None, alias="paySchedule"
    )
    gig_category_id: str | None = Field(default=None, alias="gigCategoryId")
    gig_position_id: str | None = Field(default=None, alias="gigPositionId")
    state: str | None = None
    accepts_tips: bool | None = Field(default=None, alias="acceptsTips")
    requires_vehicle: bool | None = Field(default=None, alias="requiresVehicle")
    estimated_mileage: float | None = Field(default=None, alias="estimatedMileage")


class Position(BaseModel):
    """A GigSmart organisation position template.

    Args:
        id: Opaque prefixed position ID (e.g. ``"pos_..."``).
        name: Position display name.
        description: Optional longer description.
        pay_rate: ISO-4217 money scalar (e.g. ``"20.00"``).
        created_at: Optional creation timestamp.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str | None = None
    description: str | None = None
    pay_rate: str | None = Field(default=None, alias="payRate")
    created_at: datetime | None = Field(default=None, alias="createdAt")

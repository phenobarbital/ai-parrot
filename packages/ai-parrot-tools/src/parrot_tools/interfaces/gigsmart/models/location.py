"""Pydantic v2 models for GigSmart locations API surface."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict


class PlaceResult(BaseModel):
    """A single address suggestion from the placeAutocomplete query.

    Args:
        label: Human-readable address label.
        place_id: Opaque place identifier to use in location mutations.
        place_provider: The geocoding provider (e.g. ``"GOOGLE"``, ``"HERE"``).
    """

    model_config = ConfigDict(populate_by_name=True)

    label: str
    place_id: str = Field(alias="placeId")
    place_provider: str = Field(alias="placeProvider")


class AddOrganizationLocationInput(BaseModel, frozen=True):
    """Input for the ``addOrganizationLocation`` mutation.

    All instances are immutable (``frozen=True``) for safe passing as
    GraphQL variables.

    Args:
        organization_id: The organisation to add the location to.
        name: Location name (1–120 characters).
        place_id: Optional Google/geocoder place ID to resolve the address.
        address: Raw address string, used when place_id is not available.
        primary_contact_id: Optional ID of the requester contact for this location.
        payment_method_id: Optional payment method to associate with the location.
        arrival_instructions: Instructions for workers arriving at the location.
        location_instructions: Additional location-specific instructions.
    """

    model_config = ConfigDict(populate_by_name=True)

    organization_id: str = Field(alias="organizationId")
    name: str = Field(min_length=1, max_length=120)
    place_id: str | None = Field(default=None, alias="placeId")
    address: str | None = None
    primary_contact_id: str | None = Field(default=None, alias="primaryContactId")
    payment_method_id: str | None = Field(default=None, alias="paymentMethodId")
    arrival_instructions: str | None = Field(default=None, alias="arrivalInstructions")
    location_instructions: str | None = Field(default=None, alias="locationInstructions")


class OrganizationLocation(BaseModel):
    """A location belonging to a GigSmart organisation.

    Args:
        id: Opaque prefixed location ID (e.g. ``"loc_..."``).
        name: Location display name.
        state: Location status/state string.
        latitude: Optional GPS latitude.
        longitude: Optional GPS longitude.
        created_at: Optional creation timestamp.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    state: str
    latitude: float | None = None
    longitude: float | None = None
    created_at: datetime | None = Field(default=None, alias="createdAt")

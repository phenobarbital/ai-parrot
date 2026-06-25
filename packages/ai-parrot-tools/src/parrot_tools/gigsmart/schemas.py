"""Pydantic input schemas for GigSmartToolkit @tool_schema decorators.

One schema class per tool method — used to validate LLM tool call arguments
before they are forwarded to the GraphQL client.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------

class ListOrganizationsInput(BaseModel):
    """Input for list_organizations tool."""

    first: int = Field(default=25, ge=1, le=100, description="Maximum number of orgs to return.")
    after: str | None = Field(default=None, description="Pagination cursor.")
    filter_name: str | None = Field(default=None, description="Filter organizations by name substring.")


class GetOrganizationInput(BaseModel):
    """Input for get_organization tool."""

    organization_id: str = Field(description="Organization ID (e.g. org_xxx).")


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

class ListLocationsInput(BaseModel):
    """Input for list_locations tool."""

    organization_id: str = Field(description="Organization ID.")
    first: int = Field(default=25, ge=1, le=100, description="Maximum locations to return.")
    after: str | None = Field(default=None, description="Pagination cursor.")


class PlaceAutocompleteInput(BaseModel):
    """Input for place_autocomplete tool."""

    search_text: str = Field(description="Address search text for autocomplete.")


class AddOrganizationLocationInput(BaseModel):
    """Input for add_organization_location tool."""

    organization_id: str = Field(description="Target organization ID.")
    name: str = Field(min_length=1, max_length=120, description="Location name (1-120 chars).")
    place_id: str | None = Field(default=None, description="Geocoder place ID.")
    address: str | None = Field(default=None, description="Raw address string (if no place_id).")
    arrival_instructions: str | None = Field(default=None, description="Worker arrival notes.")
    location_instructions: str | None = Field(default=None, description="On-site instructions.")


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

class ListPositionsInput(BaseModel):
    """Input for list_positions tool."""

    organization_id: str = Field(description="Organization ID.")
    first: int = Field(default=25, ge=1, le=100, description="Maximum positions to return.")
    after: str | None = Field(default=None, description="Pagination cursor.")


class GetPositionInput(BaseModel):
    """Input for get_position tool."""

    position_id: str = Field(description="Position ID (e.g. pos_xxx).")


class AddOrganizationPositionInput(BaseModel):
    """Input for add_organization_position tool."""

    organization_id: str = Field(description="Target organization ID.")
    name: str = Field(description="Position name.")
    category_id: str | None = Field(default=None, description="GigSmart gig category ID.")
    description: str | None = Field(default=None, description="Position description.")
    pay_rate: str | None = Field(default=None, description="Pay rate as ISO-4217 string (e.g. '20.00').")
    pay_schedule: str | None = Field(default=None, description="FIXED, HOURLY, or INFO_REQUIRED.")


# ---------------------------------------------------------------------------
# Gigs / Shifts
# ---------------------------------------------------------------------------

class ListGigsInput(BaseModel):
    """Input for list_gigs tool."""

    organization_id: str = Field(description="Organization ID.")
    first: int = Field(default=25, ge=1, le=100, description="Maximum gigs to return.")
    after: str | None = Field(default=None, description="Pagination cursor.")
    state_filter: str | None = Field(default=None, description="Filter by gig state (e.g. ACTIVE, UPCOMING).")


class GetGigInput(BaseModel):
    """Input for get_gig tool."""

    gig_id: str = Field(description="Gig ID (e.g. gig_xxx).")


class PostShiftInput(BaseModel):
    """Input for post_shift tool."""

    organization_id: str = Field(description="Organization ID.")
    position_id: str = Field(description="Organization position ID.")
    location_id: str = Field(description="Organization location ID.")
    starts_at: datetime = Field(description="Shift start time (ISO-8601 with timezone).")
    ends_at: datetime = Field(description="Shift end time (ISO-8601 with timezone).")
    slots_available: int = Field(default=1, ge=1, description="Number of worker slots.")
    pay_rate: str | None = Field(default=None, description="Pay rate override (e.g. '22.50').")
    description: str | None = Field(default=None, max_length=5000, description="Shift description.")


class TransitionGigInput(BaseModel):
    """Input for transition_gig tool."""

    gig_id: str = Field(description="Gig ID to transition.")
    action: str = Field(description="Transition action: CANCEL, CLOSE, MARK_AS_COMPLETE, or PUBLISH.")


# ---------------------------------------------------------------------------
# Engagements
# ---------------------------------------------------------------------------

class ListEngagementsInput(BaseModel):
    """Input for list_engagements tool."""

    gig_id: str = Field(description="Gig ID.")
    first: int = Field(default=25, ge=1, le=100, description="Maximum engagements to return.")
    after: str | None = Field(default=None, description="Pagination cursor.")
    state_filter: str | None = Field(default=None, description="Filter by engagement state.")


class GetEngagementInput(BaseModel):
    """Input for get_engagement tool."""

    engagement_id: str = Field(description="Engagement ID (e.g. eng_xxx).")


class TransitionEngagementInput(BaseModel):
    """Input for transition_engagement tool."""

    engagement_id: str = Field(description="Engagement ID to transition.")
    action: str = Field(description="Action: HIRE, ACCEPT, START, END, CANCEL, OFFER, PAUSE, RESUME, etc.")
    cancel_conflicting: bool | None = Field(default=None, description="Cancel conflicting engagements.")


class ListEngagementStatesInput(BaseModel):
    """Input for list_engagement_states tool."""

    engagement_id: str = Field(description="Engagement ID.")


# ---------------------------------------------------------------------------
# Timesheets
# ---------------------------------------------------------------------------

class ListTimesheetsInput(BaseModel):
    """Input for list_timesheets tool."""

    engagement_id: str = Field(description="Engagement ID.")


class GetTimesheetInput(BaseModel):
    """Input for get_timesheet tool."""

    timesheet_id: str = Field(description="Timesheet ID (e.g. engts_xxx).")


class ApproveTimesheetInput(BaseModel):
    """Input for approve_timesheet tool."""

    timesheet_id: str = Field(description="Timesheet ID to approve.")
    mutation_lock: str | None = Field(default=None, description="Optimistic concurrency lock token.")


class RemoveTimesheetDisputeInput(BaseModel):
    """Input for remove_timesheet_dispute tool."""

    timesheet_id: str = Field(description="Timesheet ID to reject/send back for worker resubmission.")


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

class AddConversationMessageInput(BaseModel):
    """Input for add_conversation_message tool."""

    engagement_id: str = Field(description="Engagement ID for the conversation thread.")
    body: str = Field(description="Message body text.")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

class SearchGigsInput(BaseModel):
    """Input for search_gigs tool."""

    query: str = Field(description="Search query text.")
    location: str | None = Field(default=None, description="Location filter string.")
    radius_miles: float | None = Field(default=None, description="Search radius in miles.")
    first: int = Field(default=25, ge=1, le=100, description="Maximum results.")


class GetGigSummaryInput(BaseModel):
    """Input for get_gig_summary tool."""

    gig_id: str = Field(description="Gig ID to get a full summary for.")

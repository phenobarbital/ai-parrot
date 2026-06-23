"""GigSmartToolkit — AbstractToolkit exposing GigSmart API surfaces as LLM tools.

Provides 23 async tool methods organised into 7 surfaces:
- Organizations (2): list_organizations, get_organization
- Locations (3): list_locations, place_autocomplete, add_organization_location
- Positions (3): list_positions, get_position, add_organization_position
- Gigs/Shifts (4): list_gigs, get_gig, post_shift, transition_gig
- Engagements (4): list_engagements, get_engagement, transition_engagement, list_engagement_states
- Timesheets (4): list_timesheets, get_timesheet, approve_timesheet, remove_timesheet_dispute
- Messages (1): add_conversation_message
- Utilities (2): search_gigs, get_gig_summary

Write mutations are gated via ``confirming_tools`` (HITL confirmation required).
Large result sets (>10 items) optionally spill to WorkingMemory DataFrames via
the optional ``WorkingMemoryToolkit`` composition.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from parrot_tools.toolkit import AbstractToolkit
from parrot_tools.decorators import tool_schema

from parrot_tools.interfaces.gigsmart.client import GigSmartClient
from parrot_tools.interfaces.gigsmart.config import GigSmartConfig
from parrot_tools.interfaces.gigsmart.models.gig import PostShiftInput as _PostShiftInput
from parrot_tools.interfaces.gigsmart.models.engagement import TransitionEngagementInput as _TransitionEngagementInput
from parrot_tools.interfaces.gigsmart.models.location import AddOrganizationLocationInput as _AddOrgLocInput
from parrot_tools.interfaces.gigsmart.models.position import AddOrganizationPositionInput as _AddOrgPosInput
from parrot_tools.interfaces.gigsmart.models.timesheet import (
    ApproveEngagementTimesheetInput as _ApproveTSInput,
    RemoveEngagementTimesheetInput as _RemoveTSInput,
)
from parrot_tools.interfaces.gigsmart.queries.gigs import (
    LIST_GIGS,
    GET_GIG,
    POST_SHIFT,
    TRANSITION_GIG,
    SEARCH_GIGS,
    GET_GIG_SUMMARY,
)
from parrot_tools.interfaces.gigsmart.queries.locations import (
    LIST_LOCATIONS,
    ADD_ORGANIZATION_LOCATION,
    PLACE_AUTOCOMPLETE,
)
from parrot_tools.interfaces.gigsmart.queries.positions import (
    LIST_POSITIONS,
    GET_POSITION,
    ADD_ORGANIZATION_POSITION,
)
from parrot_tools.interfaces.gigsmart.queries.engagements import (
    LIST_ENGAGEMENTS,
    GET_ENGAGEMENT,
    TRANSITION_ENGAGEMENT,
    LIST_ENGAGEMENT_STATES,
)
from parrot_tools.interfaces.gigsmart.queries.timesheets import (
    LIST_TIMESHEETS,
    GET_TIMESHEET,
    APPROVE_ENGAGEMENT_TIMESHEET,
    REMOVE_ENGAGEMENT_TIMESHEET,
)
from parrot_tools.interfaces.gigsmart.queries.messages import ADD_USER_MESSAGE

from parrot_tools.gigsmart.schemas import (
    ListOrganizationsInput,
    GetOrganizationInput,
    ListLocationsInput,
    PlaceAutocompleteInput,
    AddOrganizationLocationInput,
    ListPositionsInput,
    GetPositionInput,
    AddOrganizationPositionInput,
    ListGigsInput,
    GetGigInput,
    PostShiftInput,
    TransitionGigInput,
    ListEngagementsInput,
    GetEngagementInput,
    TransitionEngagementInput,
    ListEngagementStatesInput,
    ListTimesheetsInput,
    GetTimesheetInput,
    ApproveTimesheetInput,
    RemoveTimesheetDisputeInput,
    AddConversationMessageInput,
    SearchGigsInput,
    GetGigSummaryInput,
)


class GigSmartToolkit(AbstractToolkit):
    """LLM toolkit for interacting with the GigSmart staffing platform API.

    Exposes 23 async methods as tools. Write mutations are gated via
    ``confirming_tools`` for human-in-the-loop safety. Large list results
    (>10 items) optionally spill to WorkingMemory DataFrames when a
    ``WorkingMemoryToolkit`` instance is provided.

    Args:
        config: GigSmartConfig carrying client credentials and endpoint settings.
        wm: Optional WorkingMemoryToolkit for DataFrame spilling.
        **kwargs: Additional kwargs forwarded to AbstractToolkit.__init__.

    Example::

        config = GigSmartConfig.from_env()
        toolkit = GigSmartToolkit(config=config)
        tools = toolkit.get_tools()
    """

    name: str = "gigsmart"
    description: str = "Tools for interacting with the GigSmart staffing platform API."
    tool_prefix: str = "gs"

    #: Write mutations require HITL confirmation.
    confirming_tools: frozenset = frozenset({
        "post_shift",
        "transition_gig",
        "transition_engagement",
        "add_organization_location",
        "add_organization_position",
        "approve_timesheet",
        "remove_timesheet_dispute",
        "add_conversation_message",
    })

    def __init__(
        self,
        config: GigSmartConfig,
        wm: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._client = GigSmartClient(config)
        self._wm = wm

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Open the underlying GigSmartClient session."""
        await self._client.start()

    async def stop(self) -> None:
        """Close the underlying GigSmartClient session."""
        await self._client.close()

    async def cleanup(self) -> None:
        """Alias for stop() — closes the client session."""
        await self._client.close()

    # ------------------------------------------------------------------
    # Post-execute WorkingMemory spilling
    # ------------------------------------------------------------------

    async def _post_execute(self, tool_name: str, result: Any, **kwargs: Any) -> Any:
        """Spill large list results to WorkingMemory when configured."""
        if self._wm is not None and isinstance(result, list) and len(result) > 10:
            try:
                import pandas as pd
                df = pd.DataFrame(result)
                await self._wm.store(
                    key=f"gs_{tool_name}",
                    df=df,
                    description=f"GigSmart {tool_name} results ({len(result)} items)",
                )
                return {
                    "spilled_to_working_memory": f"gs_{tool_name}",
                    "count": len(result),
                }
            except Exception as exc:
                self.logger.warning(
                    "GigSmartToolkit: failed to spill '%s' to WorkingMemory: %s",
                    tool_name,
                    exc,
                )
        return result

    # ------------------------------------------------------------------
    # Scope enforcement helper
    # ------------------------------------------------------------------

    async def _require_write_scope(self, scope: str) -> None:
        """Assert the current token grants *scope*; raises GigSmartAuthError if not.

        Args:
            scope: OAuth scope string required for the write operation.

        Raises:
            GigSmartAuthError: When the current grant type does not allow the scope.
        """
        await self._client._auth.ensure_scope(scope)

    # ==================================================================
    # Organizations
    # ==================================================================

    @tool_schema(ListOrganizationsInput)
    async def list_organizations(
        self,
        first: int = 25,
        after: str | None = None,
        filter_name: str | None = None,
    ) -> list[dict]:
        """List organizations accessible to the authenticated requester.

        Returns a list of organization summaries. Use pagination cursors to
        retrieve additional pages of results.

        Args:
            first: Maximum number of organizations to return (1-100).
            after: Pagination cursor from a previous response.
            filter_name: Optional name filter substring.

        Returns:
            List of organization dicts with id, name, and related metadata.
        """
        query = """
        query ListOrganizations($first: Int, $after: String, $filter: OrganizationFilter) {
          viewer {
            ... on OrganizationRequester {
              organization {
                id
                name
              }
            }
          }
        }
        """
        variables: dict = {"first": first, "after": after}
        if filter_name:
            variables["filter"] = {"name": filter_name}
        data = await self._client.execute(query, variables)
        viewer = data.get("viewer", {})
        org = viewer.get("organization")
        if org:
            return [org]
        return []

    @tool_schema(GetOrganizationInput)
    async def get_organization(self, organization_id: str) -> dict:
        """Get details for a specific organization by ID.

        Args:
            organization_id: Organization ID (e.g. org_xxx).

        Returns:
            Organization dict with id, name, and related metadata.
        """
        query = """
        query GetOrganization($id: ID!) {
          node(id: $id) {
            ... on Organization {
              id
              name
            }
          }
        }
        """
        data = await self._client.execute(query, {"id": organization_id})
        return data.get("node") or {}

    # ==================================================================
    # Locations
    # ==================================================================

    @tool_schema(ListLocationsInput)
    async def list_locations(
        self,
        organization_id: str,
        first: int = 25,
        after: str | None = None,
    ) -> list[dict]:
        """List locations for an organization.

        Returns a list of location summaries including ID, name, state, and
        GPS coordinates. Use pagination cursors to retrieve additional pages.

        Args:
            organization_id: Organization ID.
            first: Maximum number of locations to return (1-100).
            after: Pagination cursor from a previous response.

        Returns:
            List of location dicts.
        """
        nodes = await self._client.paginate(
            LIST_LOCATIONS,
            {"organizationId": organization_id, "first": first, "after": after},
            "organization.locations",
            page_size=first,
        )
        return nodes

    @tool_schema(PlaceAutocompleteInput)
    async def place_autocomplete(self, search_text: str) -> list[dict]:
        """Search for address suggestions using GigSmart place autocomplete.

        Use this to resolve human-readable addresses into placeIds before
        calling add_organization_location.

        Args:
            search_text: Address or location search string.

        Returns:
            List of place suggestion dicts with label, placeId, and placeProvider.
        """
        data = await self._client.execute(
            PLACE_AUTOCOMPLETE,
            {"input": {"searchText": search_text}},
        )
        return data.get("placeAutocomplete", {}).get("results", [])

    @tool_schema(AddOrganizationLocationInput)
    async def add_organization_location(
        self,
        organization_id: str,
        name: str,
        place_id: str | None = None,
        address: str | None = None,
        arrival_instructions: str | None = None,
        location_instructions: str | None = None,
    ) -> dict:
        """Create a new location for an organization.

        Use place_autocomplete first to resolve the address into a placeId.
        This is a write mutation and requires HITL confirmation.

        Args:
            organization_id: Target organization ID.
            name: Location name (1-120 characters).
            place_id: Geocoder place ID (preferred over raw address).
            address: Raw address string (used when place_id is unavailable).
            arrival_instructions: Instructions for workers arriving at this location.
            location_instructions: On-site location instructions.

        Returns:
            The created OrganizationLocation dict with id, name, and state.
        """
        await self._require_write_scope("write:locations")
        inp = _AddOrgLocInput(
            organization_id=organization_id,
            name=name,
            place_id=place_id,
            address=address,
            arrival_instructions=arrival_instructions,
            location_instructions=location_instructions,
        )
        data = await self._client.execute(
            ADD_ORGANIZATION_LOCATION,
            {"input": inp.model_dump(by_alias=True, exclude_none=True)},
            is_mutation=True,
        )
        return data.get("addOrganizationLocation", {}).get("organizationLocation") or {}

    # ==================================================================
    # Positions
    # ==================================================================

    @tool_schema(ListPositionsInput)
    async def list_positions(
        self,
        organization_id: str,
        first: int = 25,
        after: str | None = None,
    ) -> list[dict]:
        """List positions for an organization.

        Returns position templates including ID, name, description, and pay rate.

        Args:
            organization_id: Organization ID.
            first: Maximum number of positions to return (1-100).
            after: Pagination cursor from a previous response.

        Returns:
            List of position dicts.
        """
        nodes = await self._client.paginate(
            LIST_POSITIONS,
            {"organizationId": organization_id, "first": first, "after": after},
            "organization.positions",
            page_size=first,
        )
        return nodes

    @tool_schema(GetPositionInput)
    async def get_position(self, position_id: str) -> dict:
        """Get details for a specific position by ID.

        Args:
            position_id: Position ID (e.g. pos_xxx).

        Returns:
            Position dict with id, name, description, and payRate.
        """
        data = await self._client.execute(GET_POSITION, {"id": position_id})
        return data.get("node") or {}

    @tool_schema(AddOrganizationPositionInput)
    async def add_organization_position(
        self,
        organization_id: str,
        name: str,
        category_id: str | None = None,
        description: str | None = None,
        pay_rate: str | None = None,
        pay_schedule: str | None = None,
    ) -> dict:
        """Create a new position for an organization.

        This is a write mutation and requires HITL confirmation.

        Args:
            organization_id: Target organization ID.
            name: Position name.
            category_id: GigSmart gig category ID (optional).
            description: Position description (optional).
            pay_rate: Pay rate as ISO-4217 string (e.g. '20.00').
            pay_schedule: FIXED, HOURLY, or INFO_REQUIRED.

        Returns:
            The created OrganizationPosition dict.
        """
        await self._require_write_scope("write:positions")
        inp = _AddOrgPosInput(
            organization_id=organization_id,
            name=name,
            gig_category_id=category_id,
            description=description,
            pay_rate=pay_rate,
            pay_schedule=pay_schedule,  # type: ignore[arg-type]
        )
        data = await self._client.execute(
            ADD_ORGANIZATION_POSITION,
            {"input": inp.model_dump(by_alias=True, exclude_none=True)},
            is_mutation=True,
        )
        return data.get("addOrganizationPosition", {}).get("organizationPosition") or {}

    # ==================================================================
    # Gigs / Shifts
    # ==================================================================

    @tool_schema(ListGigsInput)
    async def list_gigs(
        self,
        organization_id: str,
        first: int = 25,
        after: str | None = None,
        state_filter: str | None = None,
    ) -> list[dict]:
        """List gigs (shifts) for an organization with optional state filtering.

        Returns a list of gig summaries including ID, name, dates, state, and
        pay rate. Use state_filter with values like ACTIVE, UPCOMING, COMPLETED.

        Args:
            organization_id: Organization ID.
            first: Maximum number of gigs to return (1-100).
            after: Pagination cursor from a previous response.
            state_filter: Optional gig state filter (e.g. ACTIVE, UPCOMING).

        Returns:
            List of gig dicts.
        """
        variables: dict = {"organizationId": organization_id, "first": first}
        if after:
            variables["after"] = after
        if state_filter:
            variables["filter"] = {"gigStateName": state_filter}
        nodes = await self._client.paginate(
            LIST_GIGS,
            variables,
            "organization.gigs",
            page_size=first,
        )
        return nodes

    @tool_schema(GetGigInput)
    async def get_gig(self, gig_id: str) -> dict:
        """Get full details for a specific gig by ID.

        Args:
            gig_id: Gig ID (e.g. gig_xxx).

        Returns:
            Gig dict with id, name, dates, state, slotsAvailable, and payRate.
        """
        data = await self._client.execute(GET_GIG, {"id": gig_id})
        return data.get("node") or {}

    @tool_schema(PostShiftInput)
    async def post_shift(
        self,
        organization_id: str,
        position_id: str,
        location_id: str,
        starts_at: datetime,
        ends_at: datetime,
        slots_available: int = 1,
        pay_rate: str | None = None,
        description: str | None = None,
    ) -> dict:
        """Post a new shift (gig) for an organization.

        This is a write mutation and requires HITL confirmation.
        The shift will be created in DRAFT state; use transition_gig(action=PUBLISH)
        to make it visible to workers.

        Args:
            organization_id: Organization that will host the shift.
            position_id: Organization position ID for the shift type.
            location_id: Organization location ID where the shift takes place.
            starts_at: Shift start time (ISO-8601 with timezone).
            ends_at: Shift end time (ISO-8601 with timezone).
            slots_available: Number of worker slots to fill (minimum 1).
            pay_rate: Pay rate override as ISO-4217 string (e.g. '22.50').
            description: Optional shift-specific instructions (max 5000 chars).

        Returns:
            The created shift dict with id, name, dates, and currentState.
        """
        await self._require_write_scope("write:gigs")
        inp = _PostShiftInput(
            organization_id=organization_id,
            organization_position_id=position_id,
            organization_location_id=location_id,
            starts_at=starts_at,
            ends_at=ends_at,
            slots_available=slots_available,
            pay_rate=pay_rate,
            description=description,
        )
        data = await self._client.execute(
            POST_SHIFT,
            {"input": inp.model_dump(by_alias=True, exclude_none=True)},
            is_mutation=True,
        )
        return data.get("postShift", {}).get("shift") or {}

    @tool_schema(TransitionGigInput)
    async def transition_gig(self, gig_id: str, action: str) -> dict:
        """Transition a gig to a new state.

        This is a write mutation and requires HITL confirmation.
        Valid actions: CANCEL, CLOSE, MARK_AS_COMPLETE, PUBLISH.

        Args:
            gig_id: Gig ID to transition (e.g. gig_xxx).
            action: Transition action — CANCEL, CLOSE, MARK_AS_COMPLETE, or PUBLISH.

        Returns:
            The updated gig dict with id, name, and currentState.
        """
        await self._require_write_scope("write:gigs")
        data = await self._client.execute(
            TRANSITION_GIG,
            {"input": {"gigId": gig_id, "action": action}},
            is_mutation=True,
        )
        return data.get("transitionGig", {}).get("gig") or {}

    # ==================================================================
    # Engagements
    # ==================================================================

    @tool_schema(ListEngagementsInput)
    async def list_engagements(
        self,
        gig_id: str,
        first: int = 25,
        after: str | None = None,
        state_filter: str | None = None,
    ) -> list[dict]:
        """List engagements for a gig with optional state filtering.

        Engagements link workers to gigs. Each engagement tracks one worker's
        lifecycle from application through payment.

        Args:
            gig_id: Gig ID to list engagements for.
            first: Maximum number of engagements to return (1-100).
            after: Pagination cursor from a previous response.
            state_filter: Filter by engagement state (e.g. SCHEDULED, HIRED).

        Returns:
            List of engagement dicts.
        """
        variables: dict = {"gigId": gig_id, "first": first}
        if after:
            variables["after"] = after
        if state_filter:
            variables["filter"] = {"currentStateName": state_filter}
        nodes = await self._client.paginate(
            LIST_ENGAGEMENTS,
            variables,
            "node.engagements",
            page_size=first,
        )
        return nodes

    @tool_schema(GetEngagementInput)
    async def get_engagement(self, engagement_id: str) -> dict:
        """Get full details for a specific engagement by ID.

        Args:
            engagement_id: Engagement ID (e.g. eng_xxx).

        Returns:
            Engagement dict with id, gigId, workerDisplayName, currentState, etc.
        """
        data = await self._client.execute(GET_ENGAGEMENT, {"id": engagement_id})
        return data.get("node") or {}

    @tool_schema(TransitionEngagementInput)
    async def transition_engagement(
        self,
        engagement_id: str,
        action: str,
        cancel_conflicting: bool | None = None,
    ) -> dict:
        """Transition an engagement to a new state.

        This is the SINGLE mutation for ALL engagement state transitions.
        This is a write mutation and requires HITL confirmation.

        Key actions: HIRE, ACCEPT, START, END, CANCEL, OFFER, PAUSE, RESUME,
        APPROVE_TIMESHEET, BID, DENY_APPLICATION, RESCIND.

        Args:
            engagement_id: Engagement ID to transition.
            action: EngagementStateAction value (e.g. HIRE, CANCEL, END).
            cancel_conflicting: Whether to cancel conflicting active engagements.

        Returns:
            Updated engagement dict with id and currentState.
        """
        await self._require_write_scope("write:engagements")
        inp = _TransitionEngagementInput(
            engagement_id=engagement_id,
            action=action,
            cancel_conflicting_engagements=cancel_conflicting,
        )
        data = await self._client.execute(
            TRANSITION_ENGAGEMENT,
            {"input": inp.model_dump(by_alias=True, exclude_none=True)},
            is_mutation=True,
        )
        return data.get("transitionEngagement", {}).get("engagement") or {}

    @tool_schema(ListEngagementStatesInput)
    async def list_engagement_states(self, engagement_id: str) -> list[dict]:
        """List the full state history for an engagement.

        Returns a chronological list of all state transitions the engagement
        has gone through.

        Note: Returns only the first page of results. For engagements with many
        state transitions, not all states may be returned.

        Args:
            engagement_id: Engagement ID to inspect.

        Returns:
            List of state transition dicts with name and transitionedAt.
        """
        data = await self._client.execute(LIST_ENGAGEMENT_STATES, {"id": engagement_id})
        node = data.get("node") or {}
        states_conn = node.get("engagementStates", {})
        edges = states_conn.get("edges", [])
        return [edge["node"] for edge in edges if "node" in edge]

    # ==================================================================
    # Timesheets
    # ==================================================================

    @tool_schema(ListTimesheetsInput)
    async def list_timesheets(self, engagement_id: str) -> list[dict]:
        """List timesheets for an engagement.

        Timesheets record hours worked and payment details. An engagement may
        have multiple timesheet variants (ADMIN, FINAL, REQUESTER, WORKER, etc.).

        Note: Returns only the first page of results. For engagements with many
        timesheets, not all timesheets may be returned.

        Args:
            engagement_id: Engagement ID.

        Returns:
            List of timesheet dicts with id, isApproved, variant, and paymentStyle.
        """
        data = await self._client.execute(LIST_TIMESHEETS, {"engagementId": engagement_id})
        node = data.get("node") or {}
        ts_conn = node.get("timesheets", {})
        edges = ts_conn.get("edges", [])
        return [edge["node"] for edge in edges if "node" in edge]

    @tool_schema(GetTimesheetInput)
    async def get_timesheet(self, timesheet_id: str) -> dict:
        """Get full details for a specific timesheet by ID.

        Args:
            timesheet_id: Timesheet ID (e.g. engts_xxx).

        Returns:
            Timesheet dict with id, engagementId, isApproved, variant, and paymentStyle.
        """
        data = await self._client.execute(GET_TIMESHEET, {"id": timesheet_id})
        return data.get("node") or {}

    @tool_schema(ApproveTimesheetInput)
    async def approve_timesheet(
        self, timesheet_id: str, mutation_lock: str | None = None
    ) -> dict:
        """Approve a worker's timesheet.

        This is a write mutation and requires HITL confirmation.
        Once approved, the timesheet proceeds to payment processing.

        Args:
            timesheet_id: Timesheet ID to approve.
            mutation_lock: Optional optimistic concurrency lock token.

        Returns:
            Updated timesheet dict with id and isApproved.
        """
        await self._require_write_scope("write:engagements")
        inp = _ApproveTSInput(timesheet_id=timesheet_id, mutation_lock=mutation_lock)
        data = await self._client.execute(
            APPROVE_ENGAGEMENT_TIMESHEET,
            {"input": inp.model_dump(by_alias=True, exclude_none=True)},
            is_mutation=True,
        )
        return data.get("approveEngagementTimesheet", {}).get("engagementTimesheet") or {}

    @tool_schema(RemoveTimesheetDisputeInput)
    async def remove_timesheet_dispute(self, timesheet_id: str) -> dict:
        """Reject a timesheet and send it back to the worker for resubmission.

        This is a write mutation and requires HITL confirmation.
        The worker will be notified to review and resubmit their timesheet.
        This does NOT delete the timesheet record.

        Args:
            timesheet_id: Timesheet ID to reject/send back.

        Returns:
            Updated timesheet dict.
        """
        await self._require_write_scope("write:engagements")
        inp = _RemoveTSInput(timesheet_id=timesheet_id)
        data = await self._client.execute(
            REMOVE_ENGAGEMENT_TIMESHEET,
            {"input": inp.model_dump(by_alias=True, exclude_none=True)},
            is_mutation=True,
        )
        return data.get("removeEngagementTimesheet", {}).get("engagementTimesheet") or {}

    # ==================================================================
    # Messages
    # ==================================================================

    @tool_schema(AddConversationMessageInput)
    async def add_conversation_message(
        self, engagement_id: str, body: str
    ) -> dict:
        """Send a message to a worker via the engagement conversation thread.

        This is a write mutation and requires HITL confirmation.

        Args:
            engagement_id: Engagement ID for the conversation thread.
            body: Message body text to send.

        Returns:
            The created message dict with id, body, and insertedAt.
        """
        await self._require_write_scope("write:messages")
        data = await self._client.execute(
            ADD_USER_MESSAGE,
            {"input": {"engagementId": engagement_id, "body": body}},
            is_mutation=True,
        )
        return data.get("addUserMessage", {}).get("userMessage") or {}

    # ==================================================================
    # Utilities
    # ==================================================================

    @tool_schema(SearchGigsInput)
    async def search_gigs(
        self,
        query: str,
        location: str | None = None,
        radius_miles: float | None = None,
        first: int = 25,
    ) -> list[dict]:
        """Search for gigs matching a text query and optional location filter.

        Returns gig summaries that match the given search criteria.

        Args:
            query: Search query text.
            location: Optional location name or address to filter by proximity.
            radius_miles: Optional search radius in miles (requires location).
            first: Maximum number of results to return (1-100).

        Returns:
            List of matching gig dicts.
        """
        variables: dict = {"first": first, "filter": {"query": query}}
        data = await self._client.execute(SEARCH_GIGS, variables)
        edges = data.get("gigs", {}).get("edges", [])
        return [edge["node"] for edge in edges if "node" in edge]

    @tool_schema(GetGigSummaryInput)
    async def get_gig_summary(self, gig_id: str) -> dict:
        """Get an enriched summary of a gig including engagement counts and timesheet status.

        Combines the gig's core data with a count of engagements by state, making
        it useful for a quick operational overview of a shift.

        Args:
            gig_id: Gig ID (e.g. gig_xxx).

        Returns:
            Enriched gig dict with id, name, dates, state, and engagement summary.
        """
        data = await self._client.execute(GET_GIG_SUMMARY, {"id": gig_id})
        return data.get("node") or {}

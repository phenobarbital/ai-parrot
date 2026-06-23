"""GigSmart Pydantic v2 models — public exports.

All input models are ``frozen=True`` and serialize to camelCase via
``model_dump(by_alias=True)`` for use as GraphQL variables.
"""

from __future__ import annotations

from parrot_tools.interfaces.gigsmart.models.common import (
    OAuthToken,
    RelayConnection,
    RelayEdge,
    RelayPageInfo,
)
from parrot_tools.interfaces.gigsmart.models.engagement import (
    AddEngagementInput,
    Engagement,
    TransitionEngagementInput,
)
from parrot_tools.interfaces.gigsmart.models.gig import (
    Gig,
    GigStateAction,
    GigStateName,
    PostShiftInput,
    TransitionGigInput,
)
from parrot_tools.interfaces.gigsmart.models.location import (
    AddOrganizationLocationInput,
    OrganizationLocation,
    PlaceResult,
)
from parrot_tools.interfaces.gigsmart.models.position import (
    AddOrganizationPositionInput,
    Position,
)
from parrot_tools.interfaces.gigsmart.models.timesheet import (
    AddEngagementDisputeInput,
    ApproveEngagementTimesheetInput,
    EngagementTimesheet,
    RemoveEngagementTimesheetInput,
    SetEngagementDisputeApprovalInput,
)

__all__ = [
    # Common
    "OAuthToken",
    "RelayConnection",
    "RelayEdge",
    "RelayPageInfo",
    # Locations
    "AddOrganizationLocationInput",
    "OrganizationLocation",
    "PlaceResult",
    # Positions
    "AddOrganizationPositionInput",
    "Position",
    # Gigs
    "Gig",
    "GigStateAction",
    "GigStateName",
    "PostShiftInput",
    "TransitionGigInput",
    # Engagements
    "AddEngagementInput",
    "Engagement",
    "TransitionEngagementInput",
    # Timesheets & disputes
    "AddEngagementDisputeInput",
    "ApproveEngagementTimesheetInput",
    "EngagementTimesheet",
    "RemoveEngagementTimesheetInput",
    "SetEngagementDisputeApprovalInput",
]

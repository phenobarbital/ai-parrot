"""GigSmart GraphQL document strings — public exports.

All documents are plain Python string constants. No external graphql
library is used; documents are validated at integration test time.
"""

from parrot_tools.interfaces.gigsmart.queries.fragments import PAGE_INFO_FRAGMENT
from parrot_tools.interfaces.gigsmart.queries.gigs import (
    GET_GIG,
    LIST_GIGS,
    POST_SHIFT,
    TRANSITION_GIG,
    VIEWER_QUERY,
)
from parrot_tools.interfaces.gigsmart.queries.engagements import (
    ADD_ENGAGEMENT,
    GET_ENGAGEMENT,
    LIST_ENGAGEMENT_STATES,
    LIST_ENGAGEMENTS,
    TRANSITION_ENGAGEMENT,
)
from parrot_tools.interfaces.gigsmart.queries.locations import (
    ADD_ORGANIZATION_LOCATION,
    GET_LOCATION,
    LIST_LOCATIONS,
    PLACE_AUTOCOMPLETE,
)
from parrot_tools.interfaces.gigsmart.queries.positions import (
    ADD_ORGANIZATION_POSITION,
    GET_POSITION,
    LIST_POSITIONS,
)
from parrot_tools.interfaces.gigsmart.queries.timesheets import (
    ADD_ENGAGEMENT_DISPUTE,
    APPROVE_ENGAGEMENT_TIMESHEET,
    GET_TIMESHEET,
    LIST_TIMESHEETS,
    REMOVE_ENGAGEMENT_TIMESHEET,
    SET_ENGAGEMENT_DISPUTE_APPROVAL,
)
from parrot_tools.interfaces.gigsmart.queries.messages import ADD_USER_MESSAGE

__all__ = [
    "PAGE_INFO_FRAGMENT",
    # Viewer / auth
    "VIEWER_QUERY",
    # Gigs
    "GET_GIG",
    "LIST_GIGS",
    "POST_SHIFT",
    "TRANSITION_GIG",
    # Engagements
    "ADD_ENGAGEMENT",
    "GET_ENGAGEMENT",
    "LIST_ENGAGEMENT_STATES",
    "LIST_ENGAGEMENTS",
    "TRANSITION_ENGAGEMENT",
    # Locations
    "ADD_ORGANIZATION_LOCATION",
    "GET_LOCATION",
    "LIST_LOCATIONS",
    "PLACE_AUTOCOMPLETE",
    # Positions
    "ADD_ORGANIZATION_POSITION",
    "GET_POSITION",
    "LIST_POSITIONS",
    # Timesheets & disputes
    "ADD_ENGAGEMENT_DISPUTE",
    "APPROVE_ENGAGEMENT_TIMESHEET",
    "GET_TIMESHEET",
    "LIST_TIMESHEETS",
    "REMOVE_ENGAGEMENT_TIMESHEET",
    "SET_ENGAGEMENT_DISPUTE_APPROVAL",
    # Messages
    "ADD_USER_MESSAGE",
]

"""Unit tests for GigSmart GraphQL document strings."""

import pytest

from parrot_tools.interfaces.gigsmart.queries.gigs import LIST_GIGS, POST_SHIFT, TRANSITION_GIG
from parrot_tools.interfaces.gigsmart.queries.engagements import (
    LIST_ENGAGEMENTS,
    TRANSITION_ENGAGEMENT,
    ADD_ENGAGEMENT,
)
from parrot_tools.interfaces.gigsmart.queries.locations import (
    LIST_LOCATIONS,
    ADD_ORGANIZATION_LOCATION,
    PLACE_AUTOCOMPLETE,
)
from parrot_tools.interfaces.gigsmart.queries.positions import (
    LIST_POSITIONS,
    ADD_ORGANIZATION_POSITION,
)
from parrot_tools.interfaces.gigsmart.queries.timesheets import (
    APPROVE_ENGAGEMENT_TIMESHEET,
    REMOVE_ENGAGEMENT_TIMESHEET,
    LIST_TIMESHEETS,
)
from parrot_tools.interfaces.gigsmart.queries.fragments import PAGE_INFO_FRAGMENT
from parrot_tools.interfaces.gigsmart import queries


class TestGraphQLDocuments:
    """Tests for GraphQL document string correctness."""

    # Relay pagination assertions
    def test_list_gigs_uses_relay(self):
        """LIST_GIGS uses Relay edges/node/pageInfo pattern."""
        assert "edges" in LIST_GIGS
        assert "node" in LIST_GIGS
        assert "pageInfo" in LIST_GIGS

    def test_list_engagements_uses_relay(self):
        """LIST_ENGAGEMENTS uses Relay edges/node/pageInfo pattern."""
        assert "edges" in LIST_ENGAGEMENTS
        assert "node" in LIST_ENGAGEMENTS
        assert "pageInfo" in LIST_ENGAGEMENTS

    def test_list_locations_uses_relay(self):
        """LIST_LOCATIONS uses Relay edges/node/pageInfo pattern."""
        assert "edges" in LIST_LOCATIONS
        assert "node" in LIST_LOCATIONS
        assert "pageInfo" in LIST_LOCATIONS

    def test_list_positions_uses_relay(self):
        """LIST_POSITIONS uses Relay edges/node/pageInfo pattern."""
        assert "edges" in LIST_POSITIONS
        assert "node" in LIST_POSITIONS
        assert "pageInfo" in LIST_POSITIONS

    def test_list_timesheets_uses_relay(self):
        """LIST_TIMESHEETS uses Relay edges/node/pageInfo pattern."""
        assert "edges" in LIST_TIMESHEETS
        assert "node" in LIST_TIMESHEETS
        assert "pageInfo" in LIST_TIMESHEETS

    # Input variable patterns
    def test_post_shift_uses_input_var(self):
        """POST_SHIFT uses $input variable with PostShiftInput type."""
        assert "$input" in POST_SHIFT
        assert "PostShiftInput" in POST_SHIFT

    def test_add_organization_location_uses_input(self):
        """ADD_ORGANIZATION_LOCATION uses $input variable."""
        assert "$input" in ADD_ORGANIZATION_LOCATION
        assert "addOrganizationLocation" in ADD_ORGANIZATION_LOCATION

    def test_add_organization_position_uses_input(self):
        """ADD_ORGANIZATION_POSITION uses $input variable."""
        assert "$input" in ADD_ORGANIZATION_POSITION
        assert "addOrganizationPosition" in ADD_ORGANIZATION_POSITION

    def test_approve_timesheet_uses_input(self):
        """APPROVE_ENGAGEMENT_TIMESHEET uses $input variable."""
        assert "$input" in APPROVE_ENGAGEMENT_TIMESHEET
        assert "approveEngagementTimesheet" in APPROVE_ENGAGEMENT_TIMESHEET

    def test_remove_timesheet_uses_input(self):
        """REMOVE_ENGAGEMENT_TIMESHEET uses $input variable."""
        assert "$input" in REMOVE_ENGAGEMENT_TIMESHEET
        assert "removeEngagementTimesheet" in REMOVE_ENGAGEMENT_TIMESHEET

    # Transition mutations are single-mutation per surface
    def test_transition_engagement_is_single_mutation(self):
        """TRANSITION_ENGAGEMENT uses the single transitionEngagement mutation."""
        assert "transitionEngagement" in TRANSITION_ENGAGEMENT
        assert "$input" in TRANSITION_ENGAGEMENT

    def test_transition_gig_is_single_mutation(self):
        """TRANSITION_GIG uses the single transitionGig mutation."""
        assert "transitionGig" in TRANSITION_GIG
        assert "$input" in TRANSITION_GIG

    # Fragment
    def test_page_info_fragment_defined(self):
        """PAGE_INFO_FRAGMENT contains required fields."""
        assert "PageInfoFields" in PAGE_INFO_FRAGMENT
        assert "hasNextPage" in PAGE_INFO_FRAGMENT
        assert "endCursor" in PAGE_INFO_FRAGMENT

    # No hallucinated mutations
    def test_no_edit_timesheet_in_any_module(self):
        """No module contains the non-existent editTimesheet mutation."""
        for name in dir(queries):
            val = getattr(queries, name, "")
            if isinstance(val, str):
                assert "editTimesheet" not in val, f"Hallucinated editTimesheet in {name}"

    def test_no_hire_worker_mutation(self):
        """No standalone hireWorker mutation exists."""
        for name in dir(queries):
            val = getattr(queries, name, "")
            if isinstance(val, str):
                assert "hireWorker" not in val, f"Hallucinated hireWorker in {name}"

    def test_no_create_gig_or_post_gig(self):
        """createGig and postGig do not appear (correct name is postShift)."""
        for name in dir(queries):
            val = getattr(queries, name, "")
            if isinstance(val, str):
                assert "createGig" not in val, f"Hallucinated createGig in {name}"
                assert "postGig" not in val, f"Hallucinated postGig in {name}"

    # All documents are non-empty strings
    def test_all_exported_documents_nonempty(self):
        """Every exported document string is non-empty."""
        for name in queries.__all__:
            val = getattr(queries, name)
            assert isinstance(val, str) and len(val.strip()) > 0, (
                f"Document {name} is empty or not a string"
            )

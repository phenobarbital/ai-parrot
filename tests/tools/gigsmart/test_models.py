"""Unit tests for GigSmart Pydantic v2 models."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

from parrot_tools.interfaces.gigsmart.models.common import (
    RelayConnection,
    RelayEdge,
    RelayPageInfo,
    OAuthToken,
)
from parrot_tools.interfaces.gigsmart.models.gig import (
    PostShiftInput,
    TransitionGigInput,
    Gig,
)
from parrot_tools.interfaces.gigsmart.models.engagement import (
    TransitionEngagementInput,
    AddEngagementInput,
    Engagement,
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
    EngagementTimesheet,
    ApproveEngagementTimesheetInput,
    RemoveEngagementTimesheetInput,
    AddEngagementDisputeInput,
    SetEngagementDisputeApprovalInput,
)


# ---------------------------------------------------------------------------
# RelayConnection / RelayPageInfo / RelayEdge
# ---------------------------------------------------------------------------

class TestRelayConnection:
    """Tests for Relay pagination generics."""

    def test_parse_connection_with_camelcase(self):
        """RelayConnection[dict] parses camelCase API response."""
        data = {
            "edges": [{"node": {"id": "gig_abc", "name": "Test"}, "cursor": "c1"}],
            "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
        }
        conn = RelayConnection[dict].model_validate(data)
        assert len(conn.edges) == 1
        assert conn.edges[0].node == {"id": "gig_abc", "name": "Test"}
        assert conn.page_info.has_next_page is True
        assert conn.page_info.end_cursor == "c1"

    def test_nodes_helper(self):
        """RelayConnection.nodes() returns the unwrapped list."""
        data = {
            "edges": [
                {"node": {"id": "a"}, "cursor": "c1"},
                {"node": {"id": "b"}, "cursor": "c2"},
            ],
            "pageInfo": {"hasNextPage": False},
        }
        conn = RelayConnection[dict].model_validate(data)
        nodes = conn.nodes()
        assert nodes == [{"id": "a"}, {"id": "b"}]

    def test_empty_edges(self):
        """RelayConnection handles empty edges list."""
        conn = RelayConnection[dict].model_validate({
            "edges": [],
            "pageInfo": {"hasNextPage": False},
        })
        assert conn.nodes() == []

    def test_page_info_defaults(self):
        """RelayPageInfo sets hasPreviousPage=False by default."""
        pi = RelayPageInfo.model_validate({"hasNextPage": False})
        assert pi.has_previous_page is False
        assert pi.start_cursor is None
        assert pi.end_cursor is None


# ---------------------------------------------------------------------------
# OAuthToken
# ---------------------------------------------------------------------------

class TestOAuthToken:
    """Tests for OAuthToken parsing and expiry helpers."""

    def test_parse_token_response(self):
        """OAuthToken parses a typical API response dict."""
        resp = {
            "access_token": "tok-xyz",
            "token_type": "bearer",
            "expires_in": 3600,
            "scope": "read:gigs read:engagements",
        }
        tok = OAuthToken.model_validate(resp)
        assert tok.access_token == "tok-xyz"
        assert tok.expires_in == 3600
        assert tok.scope == "read:gigs read:engagements"

    def test_expires_at_computed(self):
        """expires_at is computed from expires_in when not provided."""
        resp = {"access_token": "t", "expires_in": 900, "scope": "read:gigs"}
        tok = OAuthToken.model_validate(resp)
        assert tok.expires_at is not None
        remaining = (tok.expires_at - datetime.now(timezone.utc)).total_seconds()
        assert 890 < remaining <= 910  # allow small clock skew

    def test_needs_refresh_near_expiry(self):
        """needs_refresh() returns True when token expires within threshold."""
        resp = {"access_token": "t", "expires_in": 60, "scope": "read:gigs"}
        tok = OAuthToken.model_validate(resp)
        assert tok.needs_refresh(threshold_seconds=120) is True

    def test_is_expired(self):
        """is_expired() returns True for a token past its expiry time."""
        resp = {"access_token": "t", "expires_in": 1, "scope": "read:gigs"}
        tok = OAuthToken.model_validate(resp)
        # Force an expired time
        tok.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert tok.is_expired() is True


# ---------------------------------------------------------------------------
# PostShiftInput — frozen + camelCase
# ---------------------------------------------------------------------------

class TestPostShiftInput:
    """Tests for PostShiftInput validation and serialisation."""

    def _make_input(self, **overrides):
        defaults = dict(
            organization_id="org_1",
            organization_position_id="pos_1",
            organization_location_id="loc_1",
            starts_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 7, 1, 17, 0, tzinfo=timezone.utc),
        )
        defaults.update(overrides)
        return PostShiftInput(**defaults)

    def test_frozen_immutability(self):
        """Assigning to a frozen model raises ValidationError."""
        inp = self._make_input()
        with pytest.raises(Exception):
            inp.organization_id = "changed"

    def test_camelcase_serialization(self):
        """model_dump(by_alias=True) produces camelCase keys."""
        inp = self._make_input()
        dumped = inp.model_dump(by_alias=True)
        assert "organizationId" in dumped
        assert "startsAt" in dumped
        assert "endsAt" in dumped
        assert "slotsAvailable" in dumped

    def test_slots_available_minimum_1(self):
        """slots_available < 1 raises ValidationError."""
        with pytest.raises(Exception):
            self._make_input(slots_available=0)

    def test_default_slots_available(self):
        """Default slots_available is 1."""
        inp = self._make_input()
        assert inp.slots_available == 1

    def test_description_max_length(self):
        """description over 5000 characters raises ValidationError."""
        with pytest.raises(Exception):
            self._make_input(description="x" * 5001)


# ---------------------------------------------------------------------------
# TransitionGigInput
# ---------------------------------------------------------------------------

class TestTransitionGigInput:
    """Tests for TransitionGigInput."""

    def test_valid_action(self):
        """CANCEL is a valid gig action."""
        inp = TransitionGigInput(gig_id="gig_1", action="CANCEL")
        assert inp.action == "CANCEL"

    def test_frozen(self):
        """TransitionGigInput is frozen."""
        inp = TransitionGigInput(gig_id="gig_1", action="PUBLISH")
        with pytest.raises(Exception):
            inp.gig_id = "changed"

    def test_camelcase_serialization(self):
        """model_dump(by_alias=True) uses gigId."""
        inp = TransitionGigInput(gig_id="gig_1", action="CLOSE")
        dumped = inp.model_dump(by_alias=True)
        assert "gigId" in dumped


# ---------------------------------------------------------------------------
# TransitionEngagementInput
# ---------------------------------------------------------------------------

class TestTransitionEngagementInput:
    """Tests for TransitionEngagementInput — single mutation for all transitions."""

    def test_hire_action(self):
        """HIRE is accepted as an action string."""
        inp = TransitionEngagementInput(engagement_id="eng_1", action="HIRE")
        assert inp.action == "HIRE"

    def test_camelcase_serialization(self):
        """model_dump(by_alias=True) uses engagementId."""
        inp = TransitionEngagementInput(engagement_id="eng_1", action="CANCEL")
        dumped = inp.model_dump(by_alias=True)
        assert "engagementId" in dumped

    def test_frozen(self):
        """TransitionEngagementInput is immutable."""
        inp = TransitionEngagementInput(engagement_id="eng_1", action="START")
        with pytest.raises(Exception):
            inp.action = "END"


# ---------------------------------------------------------------------------
# Location models
# ---------------------------------------------------------------------------

class TestLocationModels:
    """Tests for location-related models."""

    def test_add_location_input_frozen(self):
        """AddOrganizationLocationInput is frozen."""
        inp = AddOrganizationLocationInput(organization_id="org_1", name="HQ")
        with pytest.raises(Exception):
            inp.name = "Changed"

    def test_add_location_camelcase(self):
        """model_dump(by_alias=True) uses organizationId."""
        inp = AddOrganizationLocationInput(organization_id="org_1", name="HQ")
        dumped = inp.model_dump(by_alias=True)
        assert "organizationId" in dumped

    def test_name_min_length(self):
        """Name shorter than 1 char raises ValidationError."""
        with pytest.raises(Exception):
            AddOrganizationLocationInput(organization_id="org_1", name="")


# ---------------------------------------------------------------------------
# Timesheet models
# ---------------------------------------------------------------------------

class TestTimesheetModels:
    """Tests for timesheet and dispute models."""

    def test_approve_input_frozen(self):
        """ApproveEngagementTimesheetInput is frozen."""
        inp = ApproveEngagementTimesheetInput(timesheet_id="engts_1")
        with pytest.raises(Exception):
            inp.timesheet_id = "changed"

    def test_approve_camelcase(self):
        """model_dump(by_alias=True) uses timesheetId."""
        inp = ApproveEngagementTimesheetInput(timesheet_id="engts_1")
        dumped = inp.model_dump(by_alias=True)
        assert "timesheetId" in dumped

    def test_remove_input_frozen(self):
        """RemoveEngagementTimesheetInput is frozen."""
        inp = RemoveEngagementTimesheetInput(timesheet_id="engts_1")
        with pytest.raises(Exception):
            inp.timesheet_id = "changed"

    def test_set_dispute_approval_frozen(self):
        """SetEngagementDisputeApprovalInput is frozen."""
        inp = SetEngagementDisputeApprovalInput(dispute_id="d_1", accept=True)
        with pytest.raises(Exception):
            inp.accept = False

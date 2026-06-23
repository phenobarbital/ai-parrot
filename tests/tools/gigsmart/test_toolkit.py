"""Unit tests for GigSmartToolkit — AbstractToolkit for LLM Agents."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_tools.gigsmart.toolkit import GigSmartToolkit
from parrot_tools.interfaces.gigsmart.config import GigSmartConfig


@pytest.fixture
def config():
    """GigSmartConfig with test credentials."""
    return GigSmartConfig(client_id="test", client_secret="secret")


@pytest.fixture
def toolkit(config):
    """GigSmartToolkit with a mocked client."""
    tk = GigSmartToolkit(config=config)
    tk._client = AsyncMock()
    return tk


# ---------------------------------------------------------------------------
# Structure & registration
# ---------------------------------------------------------------------------

class TestGigSmartToolkitStructure:
    """Tests for toolkit class attributes and tool registration."""

    def test_inherits_abstract_toolkit(self, toolkit):
        """GigSmartToolkit inherits from AbstractToolkit."""
        from parrot_tools.toolkit import AbstractToolkit
        assert isinstance(toolkit, AbstractToolkit)

    def test_name(self, toolkit):
        """toolkit.name is 'gigsmart'."""
        assert toolkit.name == "gigsmart"

    def test_tool_prefix(self, toolkit):
        """toolkit.tool_prefix is 'gs'."""
        assert toolkit.tool_prefix == "gs"

    def test_confirming_tools_set(self, toolkit):
        """Expected write methods are in confirming_tools."""
        assert "post_shift" in toolkit.confirming_tools
        assert "transition_gig" in toolkit.confirming_tools
        assert "transition_engagement" in toolkit.confirming_tools
        assert "add_organization_location" in toolkit.confirming_tools
        assert "add_organization_position" in toolkit.confirming_tools
        assert "approve_timesheet" in toolkit.confirming_tools
        assert "remove_timesheet_dispute" in toolkit.confirming_tools
        assert "add_conversation_message" in toolkit.confirming_tools

    def test_read_tools_not_in_confirming(self, toolkit):
        """Read-only methods are NOT in confirming_tools."""
        assert "list_gigs" not in toolkit.confirming_tools
        assert "get_gig" not in toolkit.confirming_tools
        assert "list_locations" not in toolkit.confirming_tools
        assert "list_engagements" not in toolkit.confirming_tools

    def test_has_23_tools(self, toolkit):
        """GigSmartToolkit exposes exactly 23 tools."""
        tools = toolkit.get_tools()
        assert len(tools) == 23, (
            f"Expected 23 tools but got {len(tools)}: {[t.name for t in tools]}"
        )

    def test_tool_names_prefixed(self, toolkit):
        """All tool names are prefixed with 'gs_'."""
        tools = toolkit.get_tools()
        for tool in tools:
            assert tool.name.startswith("gs_"), (
                f"Tool '{tool.name}' does not start with 'gs_'"
            )

    def test_all_confirming_tools_in_toolkit(self, toolkit):
        """Every confirming_tool has a corresponding method in the toolkit."""
        tools = toolkit.get_tools()
        tool_base_names = {t.name.removeprefix("gs_") for t in tools}
        for ct in toolkit.confirming_tools:
            assert ct in tool_base_names, (
                f"Confirming tool '{ct}' not found among toolkit methods"
            )


# ---------------------------------------------------------------------------
# Tool method behaviour (with mocked client)
# ---------------------------------------------------------------------------

class TestGigSmartToolkitMethods:
    """Tests for individual toolkit tool methods."""

    @pytest.mark.asyncio
    async def test_list_gigs(self, toolkit):
        """list_gigs() calls client.paginate and returns results."""
        toolkit._client.paginate = AsyncMock(return_value=[{"id": "gig_1"}])
        result = await toolkit.list_gigs(organization_id="org_1")
        assert len(result) == 1
        assert result[0]["id"] == "gig_1"
        toolkit._client.paginate.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_gig(self, toolkit):
        """get_gig() calls client.execute and returns the node."""
        toolkit._client.execute = AsyncMock(return_value={"node": {"id": "gig_1", "name": "Test"}})
        result = await toolkit.get_gig(gig_id="gig_1")
        assert result == {"id": "gig_1", "name": "Test"}

    @pytest.mark.asyncio
    async def test_transition_gig(self, toolkit):
        """transition_gig() calls execute with the correct mutation."""
        toolkit._client.execute = AsyncMock(
            return_value={"transitionGig": {"gig": {"id": "gig_1", "currentState": {"name": "CANCELED"}}}}
        )
        result = await toolkit.transition_gig(gig_id="gig_1", action="CANCEL")
        assert result is not None
        assert result.get("id") == "gig_1"
        toolkit._client.execute.assert_called_once()
        call_kwargs = toolkit._client.execute.call_args
        assert call_kwargs.kwargs.get("is_mutation") is True

    @pytest.mark.asyncio
    async def test_post_shift(self, toolkit):
        """post_shift() calls execute with is_mutation=True."""
        toolkit._client.execute = AsyncMock(
            return_value={"postShift": {"shift": {"id": "gig_2", "name": "Shift"}}}
        )
        result = await toolkit.post_shift(
            organization_id="org_1",
            position_id="pos_1",
            location_id="loc_1",
            starts_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 7, 1, 17, 0, tzinfo=timezone.utc),
        )
        assert result.get("id") == "gig_2"
        call_kwargs = toolkit._client.execute.call_args
        assert call_kwargs.kwargs.get("is_mutation") is True

    @pytest.mark.asyncio
    async def test_transition_engagement(self, toolkit):
        """transition_engagement() calls execute with is_mutation=True."""
        toolkit._client.execute = AsyncMock(
            return_value={"transitionEngagement": {"engagement": {"id": "eng_1", "currentState": {"name": "SCHEDULED"}}}}
        )
        result = await toolkit.transition_engagement(engagement_id="eng_1", action="HIRE")
        assert result is not None
        assert result.get("id") == "eng_1"
        call_kwargs = toolkit._client.execute.call_args
        assert call_kwargs.kwargs.get("is_mutation") is True

    @pytest.mark.asyncio
    async def test_approve_timesheet(self, toolkit):
        """approve_timesheet() calls execute with is_mutation=True."""
        toolkit._client.execute = AsyncMock(
            return_value={"approveEngagementTimesheet": {"engagementTimesheet": {"id": "engts_1", "isApproved": True}}}
        )
        result = await toolkit.approve_timesheet(timesheet_id="engts_1")
        assert result.get("isApproved") is True
        call_kwargs = toolkit._client.execute.call_args
        assert call_kwargs.kwargs.get("is_mutation") is True

    @pytest.mark.asyncio
    async def test_list_locations(self, toolkit):
        """list_locations() calls client.paginate."""
        toolkit._client.paginate = AsyncMock(return_value=[{"id": "loc_1", "name": "HQ"}])
        result = await toolkit.list_locations(organization_id="org_1")
        assert result == [{"id": "loc_1", "name": "HQ"}]

    @pytest.mark.asyncio
    async def test_add_conversation_message_is_mutation(self, toolkit):
        """add_conversation_message() uses is_mutation=True."""
        toolkit._client.execute = AsyncMock(
            return_value={"addUserMessage": {"userMessage": {"id": "msg_1", "body": "Hello"}}}
        )
        result = await toolkit.add_conversation_message(
            engagement_id="eng_1", body="Hello"
        )
        assert result.get("body") == "Hello"
        call_kwargs = toolkit._client.execute.call_args
        assert call_kwargs.kwargs.get("is_mutation") is True

    @pytest.mark.asyncio
    async def test_search_gigs(self, toolkit):
        """search_gigs() calls execute and returns node list."""
        toolkit._client.execute = AsyncMock(
            return_value={"gigs": {"edges": [{"node": {"id": "gig_1"}}]}}
        )
        result = await toolkit.search_gigs(query="warehouse")
        assert result == [{"id": "gig_1"}]

    @pytest.mark.asyncio
    async def test_get_gig_summary(self, toolkit):
        """get_gig_summary() returns the enriched node."""
        toolkit._client.execute = AsyncMock(
            return_value={"node": {"id": "gig_1", "engagements": {"totalCount": 3}}}
        )
        result = await toolkit.get_gig_summary(gig_id="gig_1")
        assert result.get("id") == "gig_1"
        assert result.get("engagements", {}).get("totalCount") == 3


# ---------------------------------------------------------------------------
# WorkingMemory spilling
# ---------------------------------------------------------------------------

class TestWorkingMemorySpilling:
    """Tests for optional WorkingMemory DataFrame spilling."""

    @pytest.mark.asyncio
    async def test_spills_large_result(self, config):
        """Results with >10 items spill to WorkingMemory when wm is configured."""
        mock_wm = MagicMock()
        mock_wm.store = AsyncMock(return_value={"stored": True})
        tk = GigSmartToolkit(config=config, wm=mock_wm)
        tk._client = AsyncMock()

        large_result = [{"id": f"gig_{i}"} for i in range(15)]
        result = await tk._post_execute("list_gigs", large_result)

        assert result.get("spilled_to_working_memory") == "gs_list_gigs"
        assert result.get("count") == 15
        mock_wm.store.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_spill_small_result(self, config):
        """Results with <=10 items are returned as-is."""
        mock_wm = MagicMock()
        mock_wm.store = AsyncMock()
        tk = GigSmartToolkit(config=config, wm=mock_wm)

        small_result = [{"id": f"gig_{i}"} for i in range(5)]
        result = await tk._post_execute("list_gigs", small_result)

        assert result == small_result
        mock_wm.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_spill_without_wm(self, config):
        """Results are returned as-is when no WorkingMemory is configured."""
        tk = GigSmartToolkit(config=config)
        large_result = [{"id": f"gig_{i}"} for i in range(20)]
        result = await tk._post_execute("list_gigs", large_result)
        assert result == large_result

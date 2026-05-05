"""Unit tests for the HITLDemoAgent (agents/demo.py)."""
import pytest
from parrot.agents.demo import HITLDemoAgent, BookFlightTool
from parrot.registry import agent_registry
from parrot.core.exceptions import HumanInteractionInterrupt


@pytest.fixture
def demo_agent():
    return HITLDemoAgent()


@pytest.fixture
def book_flight_tool():
    return BookFlightTool()


class TestHITLDemoAgent:
    def test_demo_agent_registers(self):
        """demo agent is registered in the agent_registry."""
        assert agent_registry.has("hitl_demo")
        # Verify the registered factory is our class
        metadata = agent_registry.get_metadata("hitl_demo")
        assert metadata is not None
        assert metadata.factory is HITLDemoAgent

    def test_demo_agent_has_tools(self, demo_agent):
        """demo agent has WebHumanTool, HandoffTool, and BookFlightTool."""
        tool_names = [t.name for t in demo_agent.agent_tools()]
        assert "ask_human" in tool_names
        assert "handoff_to_human" in tool_names
        assert "book_flight" in tool_names

    def test_demo_agent_agent_id(self, demo_agent):
        """demo agent has agent_id set to 'hitl_demo'."""
        assert demo_agent.agent_id == "hitl_demo"


class TestBookFlightTool:
    @pytest.mark.asyncio
    async def test_book_flight_raises_on_bad_date(self, book_flight_tool):
        """BookFlightTool raises HumanInteractionInterrupt on malformed date."""
        with pytest.raises(HumanInteractionInterrupt):
            await book_flight_tool._execute(
                destination="Paris",
                date="next year",
            )

    @pytest.mark.asyncio
    async def test_book_flight_succeeds_on_valid_date(self, book_flight_tool):
        """BookFlightTool returns confirmation on valid date."""
        result = await book_flight_tool._execute(
            destination="Paris",
            date="2026-05-15",
        )
        assert result is not None
        assert isinstance(result, str)
        assert "confirmation" in result.lower()

    def test_book_flight_tool_name(self, book_flight_tool):
        """BookFlightTool has name 'book_flight'."""
        assert book_flight_tool.name == "book_flight"

    @pytest.mark.asyncio
    async def test_book_flight_valid_date_contains_destination(self, book_flight_tool):
        """BookFlightTool confirmation includes the destination."""
        result = await book_flight_tool._execute(
            destination="Tokyo",
            date="2026-08-01",
        )
        assert "Tokyo" in result

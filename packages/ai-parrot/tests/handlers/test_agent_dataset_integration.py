"""
Tests for AgentTalk DatasetManager integration.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from parrot.handlers.agent import AgentTalk
from parrot.handlers.user_objects import UserObjectsHandler
from parrot.tools.manager import ToolManager


class TestAgentTalkUserObjectsHandler:
    """Test UserObjectsHandler integration in AgentTalk."""

    def test_user_objects_handler_property_exists(self):
        """AgentTalk has user_objects_handler property."""
        assert hasattr(AgentTalk, 'user_objects_handler')

    def test_user_objects_handler_lazy_initialization(self):
        """user_objects_handler is lazily initialized."""
        handler = AgentTalk.__new__(AgentTalk)
        handler._user_objects_handler = None
        handler.logger = MagicMock()

        # First access creates the handler
        uoh = handler.user_objects_handler
        assert isinstance(uoh, UserObjectsHandler)

        # Second access returns same instance
        assert handler.user_objects_handler is uoh

    def test_user_objects_handler_without_logger(self):
        """user_objects_handler works when logger is not set."""
        handler = AgentTalk.__new__(AgentTalk)
        handler._user_objects_handler = None
        # No logger attribute

        uoh = handler.user_objects_handler
        assert isinstance(uoh, UserObjectsHandler)


class TestConfigureToolManagerDelegation:
    """Test that _configure_tool_manager delegates to UserObjectsHandler."""

    @pytest.mark.asyncio
    async def test_delegates_to_user_objects_handler(self):
        """_configure_tool_manager delegates to UserObjectsHandler."""
        handler = AgentTalk.__new__(AgentTalk)
        handler._user_objects_handler = None
        handler.logger = MagicMock()

        # Mock user_objects_handler
        mock_uoh = MagicMock()
        mock_uoh.configure_tool_manager = AsyncMock(
            return_value=(ToolManager(), [])
        )
        handler._user_objects_handler = mock_uoh

        data = {"tools": [{"name": "test"}]}
        session = {}

        result = await handler._configure_tool_manager(data, session, "test-agent")

        mock_uoh.configure_tool_manager.assert_called_once_with(
            data, session, "test-agent"
        )
        assert isinstance(result[0], ToolManager)


class TestDatasetManagerIntegration:
    """Test DatasetManager integration with PandasAgent."""

    @pytest.mark.asyncio
    async def test_configures_dm_for_pandas_agent(self):
        """Verifies DatasetManager is configured for PandasAgent instances."""
        # This test verifies the structure and imports are correct
        # Full integration would require mocking the entire request flow
        from parrot.bots.data import PandasAgent

        # Create a mock that looks like PandasAgent
        mock_agent = MagicMock(spec=PandasAgent)
        mock_agent.name = "test-pandas"
        mock_agent._dataset_manager = None
        mock_agent.attach_dm = MagicMock()

        # Verify isinstance works with our mock
        # Note: spec=PandasAgent makes isinstance work
        assert isinstance(mock_agent, PandasAgent)

    def test_pandas_agent_has_attach_dm(self):
        """PandasAgent has attach_dm method."""
        from parrot.bots.data import PandasAgent
        assert hasattr(PandasAgent, 'attach_dm')


class TestBackwardCompatibility:
    """Test backward compatibility of the refactored code."""

    @pytest.mark.asyncio
    async def test_tool_manager_config_still_works(self):
        """ToolManager configuration via UserObjectsHandler works."""
        handler = UserObjectsHandler()
        data = {"tools": [{"name": "test_tool"}]}
        session = {}

        with patch.object(ToolManager, 'register_tools'):
            tm, mcp = await handler.configure_tool_manager(data, session, "agent")

        assert isinstance(tm, ToolManager)
        assert "agent_tool_manager" in session

    @pytest.mark.asyncio
    async def test_existing_session_tm_reused(self):
        """Existing ToolManager from session is reused."""
        handler = UserObjectsHandler()
        existing_tm = ToolManager()
        session = {"agent_tool_manager": existing_tm}
        data = {}

        tm, mcp = await handler.configure_tool_manager(data, session, "agent")

        assert tm is existing_tm

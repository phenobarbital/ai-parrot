"""
Tests for UserObjectsHandler - Session-Scoped User Object Management.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import pandas as pd
from parrot.handlers.user_objects import UserObjectsHandler
from parrot.tools.dataset_manager import DatasetManager
from parrot.tools.manager import ToolManager


class TestUserObjectsHandlerInit:
    """Test UserObjectsHandler initialization."""

    def test_init_with_logger(self):
        """UserObjectsHandler accepts custom logger."""
        mock_logger = MagicMock()
        handler = UserObjectsHandler(logger=mock_logger)
        assert handler.logger is mock_logger

    def test_init_without_logger(self):
        """UserObjectsHandler creates default logger when none provided."""
        handler = UserObjectsHandler()
        assert handler.logger is not None


class TestSessionKeyGeneration:
    """Test session key generation."""

    def test_with_agent_name(self):
        """Session key includes agent name prefix."""
        handler = UserObjectsHandler()
        key = handler.get_session_key("my-agent", "dataset_manager")
        assert key == "my-agent_dataset_manager"

    def test_without_agent_name(self):
        """Session key without agent name prefix."""
        handler = UserObjectsHandler()
        key = handler.get_session_key(None, "tool_manager")
        assert key == "tool_manager"

    def test_empty_agent_name(self):
        """Empty string agent name treated as no prefix."""
        handler = UserObjectsHandler()
        key = handler.get_session_key("", "dataset_manager")
        assert key == "dataset_manager"

    def test_tool_manager_key(self):
        """Generates correct tool_manager key."""
        handler = UserObjectsHandler()
        key = handler.get_session_key("analytics", "tool_manager")
        assert key == "analytics_tool_manager"


class TestConfigureDatasetManager:
    """Test configure_dataset_manager method."""

    @pytest.mark.asyncio
    async def test_creates_new_dm_if_not_in_session(self):
        """Creates new DatasetManager when not in session."""
        handler = UserObjectsHandler()
        session = {}
        agent = MagicMock()
        agent.name = "test-agent"
        agent._dataset_manager = None

        dm = await handler.configure_dataset_manager(session, agent)

        assert isinstance(dm, DatasetManager)
        assert "test-agent_dataset_manager" in session
        assert session["test-agent_dataset_manager"] is dm

    @pytest.mark.asyncio
    async def test_returns_existing_dm_from_session(self):
        """Returns existing DatasetManager from session."""
        handler = UserObjectsHandler()
        existing_dm = DatasetManager()
        session = {"test-agent_dataset_manager": existing_dm}
        agent = MagicMock()
        agent.name = "test-agent"

        dm = await handler.configure_dataset_manager(session, agent)

        assert dm is existing_dm

    @pytest.mark.asyncio
    async def test_copies_datasets_from_agent_dm(self):
        """Copies datasets from agent's DatasetManager to user's."""
        handler = UserObjectsHandler()
        session = {}

        # Create agent with DatasetManager containing a dataset
        agent_dm = DatasetManager()
        df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
        agent_dm.add_dataframe("test_df", df)

        agent = MagicMock()
        agent.name = "test-agent"
        agent._dataset_manager = agent_dm

        dm = await handler.configure_dataset_manager(session, agent)

        # Verify dataset was copied
        datasets = dm.list_dataframes()
        assert "test_df" in datasets

    @pytest.mark.asyncio
    async def test_copies_multiple_datasets(self):
        """Copies multiple datasets from agent's DatasetManager."""
        handler = UserObjectsHandler()
        session = {}

        # Create agent with multiple datasets
        agent_dm = DatasetManager()
        df1 = pd.DataFrame({'x': [1, 2]})
        df2 = pd.DataFrame({'y': [3, 4]})
        agent_dm.add_dataframe("sales", df1)
        agent_dm.add_dataframe("inventory", df2)

        agent = MagicMock()
        agent.name = "analytics-agent"
        agent._dataset_manager = agent_dm

        dm = await handler.configure_dataset_manager(session, agent)

        datasets = dm.list_dataframes()
        assert "sales" in datasets
        assert "inventory" in datasets

    @pytest.mark.asyncio
    async def test_uses_custom_agent_name(self):
        """Uses provided agent_name instead of agent.name."""
        handler = UserObjectsHandler()
        session = {}
        agent = MagicMock()
        agent.name = "original-name"
        agent._dataset_manager = None

        await handler.configure_dataset_manager(
            session, agent, agent_name="custom-name"
        )

        assert "custom-name_dataset_manager" in session
        assert "original-name_dataset_manager" not in session

    @pytest.mark.asyncio
    async def test_handles_none_session(self):
        """Creates DatasetManager even with None session."""
        handler = UserObjectsHandler()
        agent = MagicMock()
        agent.name = "test-agent"
        agent._dataset_manager = None

        dm = await handler.configure_dataset_manager(None, agent)

        assert isinstance(dm, DatasetManager)

    @pytest.mark.asyncio
    async def test_handles_agent_without_dataset_manager_attr(self):
        """Handles agent without _dataset_manager attribute."""
        handler = UserObjectsHandler()
        session = {}
        agent = MagicMock(spec=['name'])  # Only has 'name' attribute
        agent.name = "test-agent"

        dm = await handler.configure_dataset_manager(session, agent)

        assert isinstance(dm, DatasetManager)
        assert len(dm.list_dataframes()) == 0


class TestConfigureToolManager:
    """Test configure_tool_manager method."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_config_provided(self):
        """Returns None when no tool configuration in data."""
        handler = UserObjectsHandler()
        data = {"message": "hello"}
        session = {}

        tm, mcp_servers = await handler.configure_tool_manager(data, session)

        assert tm is None
        assert mcp_servers == []

    @pytest.mark.asyncio
    async def test_returns_existing_tm_from_session(self):
        """Returns existing ToolManager from session when no new config."""
        handler = UserObjectsHandler()
        existing_tm = ToolManager()
        data = {"message": "hello"}
        session = {"test-agent_tool_manager": existing_tm}

        tm, mcp_servers = await handler.configure_tool_manager(
            data, session, agent_name="test-agent"
        )

        assert tm is existing_tm

    @pytest.mark.asyncio
    async def test_creates_new_tm_with_tools_payload(self):
        """Creates new ToolManager when tools payload provided."""
        handler = UserObjectsHandler()
        # tools expects list of dicts per ToolConfig model
        data = {"tools": [{"name": "tool1"}, {"name": "tool2"}]}
        session = {}

        with patch.object(ToolManager, 'register_tools') as mock_register:
            tm, mcp_servers = await handler.configure_tool_manager(
                data, session, agent_name="test-agent"
            )

            assert isinstance(tm, ToolManager)
            assert "test-agent_tool_manager" in session
            mock_register.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_on_invalid_tool_config(self):
        """Raises ValueError when tool_config is not a dict."""
        handler = UserObjectsHandler()
        data = {"tool_config": "invalid"}
        session = {}

        with pytest.raises(ValueError, match="tool_config must be an object"):
            await handler.configure_tool_manager(data, session)

    @pytest.mark.asyncio
    async def test_pops_config_keys_from_data(self):
        """Removes tool_config, tools, mcp_servers from data dict."""
        handler = UserObjectsHandler()
        data = {
            "message": "hello",
            "tools": [{"name": "tool1"}],
            "tool_config": {},
            "mcp_servers": []
        }
        session = {}

        with patch.object(ToolManager, 'register_tools'):
            await handler.configure_tool_manager(data, session)

        assert "tools" not in data
        assert "tool_config" not in data
        assert "mcp_servers" not in data
        assert data == {"message": "hello"}

    @pytest.mark.asyncio
    async def test_extends_existing_tm_in_session(self):
        """Extends existing ToolManager when tool config provided."""
        handler = UserObjectsHandler()
        existing_tm = ToolManager()
        data = {"tools": [{"name": "new_tool"}]}
        session = {"my-agent_tool_manager": existing_tm}

        with patch.object(existing_tm, 'register_tools'):
            tm, _ = await handler.configure_tool_manager(
                data, session, agent_name="my-agent"
            )

            assert tm is existing_tm

    @pytest.mark.asyncio
    async def test_saves_tool_config_to_session(self):
        """Saves tool configuration dict to session."""
        handler = UserObjectsHandler()
        data = {"tools": [{"name": "tool1"}]}
        session = {}

        with patch.object(ToolManager, 'register_tools'):
            await handler.configure_tool_manager(data, session, agent_name="agent")

        assert "agent_tool_config" in session


class TestAddMcpServersToToolManager:
    """Test _add_mcp_servers_to_tool_manager method."""

    @pytest.mark.asyncio
    async def test_adds_mcp_servers(self):
        """Adds MCP server configurations to ToolManager."""
        handler = UserObjectsHandler()
        tm = MagicMock(spec=ToolManager)
        tm.add_mcp_server = AsyncMock(return_value=["tool1", "tool2"])

        mcp_configs = [
            {"name": "test-server", "url": "http://localhost:8080"}
        ]

        await handler._add_mcp_servers_to_tool_manager(tm, mcp_configs)

        tm.add_mcp_server.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_mcp_server_failure(self):
        """Logs error but continues when MCP server fails to add."""
        handler = UserObjectsHandler()
        handler.logger = MagicMock()
        tm = MagicMock(spec=ToolManager)
        tm.add_mcp_server = AsyncMock(side_effect=Exception("Connection failed"))

        mcp_configs = [
            {"name": "failing-server", "url": "http://localhost:9999"}
        ]

        # Should not raise
        await handler._add_mcp_servers_to_tool_manager(tm, mcp_configs)

        handler.logger.error.assert_called()


class TestIntegration:
    """Integration tests for UserObjectsHandler."""

    @pytest.mark.asyncio
    async def test_full_flow_dataset_manager(self):
        """Full flow: create DM → add data → retrieve same DM."""
        handler = UserObjectsHandler()
        session = {}

        # First call - agent with data
        agent_dm = DatasetManager()
        agent_dm.add_dataframe("orders", pd.DataFrame({'id': [1, 2, 3]}))

        agent = MagicMock()
        agent.name = "data-agent"
        agent._dataset_manager = agent_dm

        dm1 = await handler.configure_dataset_manager(session, agent)
        assert "orders" in dm1.list_dataframes()

        # Second call - should return same DM
        dm2 = await handler.configure_dataset_manager(session, agent)
        assert dm1 is dm2

    @pytest.mark.asyncio
    async def test_session_isolation(self):
        """Different sessions have isolated managers."""
        handler = UserObjectsHandler()
        session1 = {}
        session2 = {}

        agent = MagicMock()
        agent.name = "shared-agent"
        agent._dataset_manager = None

        dm1 = await handler.configure_dataset_manager(session1, agent)
        dm2 = await handler.configure_dataset_manager(session2, agent)

        assert dm1 is not dm2

    @pytest.mark.asyncio
    async def test_agent_name_isolation(self):
        """Different agent names have isolated managers in same session."""
        handler = UserObjectsHandler()
        session = {}

        agent1 = MagicMock()
        agent1.name = "agent-a"
        agent1._dataset_manager = None

        agent2 = MagicMock()
        agent2.name = "agent-b"
        agent2._dataset_manager = None

        dm1 = await handler.configure_dataset_manager(session, agent1)
        dm2 = await handler.configure_dataset_manager(session, agent2)

        assert dm1 is not dm2
        assert "agent-a_dataset_manager" in session
        assert "agent-b_dataset_manager" in session

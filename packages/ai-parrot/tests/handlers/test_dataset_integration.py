"""
Integration tests for DatasetManager support feature (FEAT-021).

Tests complete workflows across UserObjectsHandler, DatasetManager,
and DatasetManagerHandler components.
"""
import pytest
import pandas as pd
from unittest.mock import MagicMock
from parrot.handlers.user_objects import UserObjectsHandler
from parrot.tools.dataset_manager import DatasetManager


class TestUploadActivateUseFlow:
    """Integration tests for complete upload → list → activate → verify flow."""

    @pytest.mark.asyncio
    async def test_upload_activate_use_flow(self):
        """Full flow: create DM → upload → list → activate → verify."""
        # Create components
        handler = UserObjectsHandler()
        session = {}

        # Simulate agent with empty DM
        agent = MagicMock()
        agent.name = "analytics-agent"
        agent._dataset_manager = None

        # Get user's DM
        dm = await handler.configure_dataset_manager(session, agent)

        # Upload dataset
        df = pd.DataFrame({'x': [1, 2, 3], 'y': [4, 5, 6]})
        dm.add_dataframe("uploaded", df)

        # Verify in list
        datasets_list = await dm.list_available()
        names = [d['name'] for d in datasets_list]
        assert "uploaded" in names

        # Deactivate and verify
        dm.deactivate("uploaded")
        active_names = await dm.get_active()
        assert "uploaded" not in active_names

        # Activate and verify
        dm.activate("uploaded")
        active_names = await dm.get_active()
        assert "uploaded" in active_names

    @pytest.mark.asyncio
    async def test_multiple_dataset_operations(self):
        """Test multiple dataset operations in sequence."""
        handler = UserObjectsHandler()
        session = {}

        agent = MagicMock()
        agent.name = "data-agent"
        agent._dataset_manager = None

        dm = await handler.configure_dataset_manager(session, agent)

        # Add multiple datasets
        dm.add_dataframe("sales", pd.DataFrame({'month': [1, 2, 3], 'revenue': [100, 200, 300]}))
        dm.add_dataframe("inventory", pd.DataFrame({'item': ['A', 'B'], 'qty': [10, 20]}))
        dm.add_dataframe("customers", pd.DataFrame({'id': [1, 2, 3]}))

        # List all
        datasets = await dm.list_available()
        assert len(datasets) == 3

        # Deactivate one
        dm.deactivate("inventory")
        active = await dm.get_active()
        assert "inventory" not in active
        assert "sales" in active
        assert "customers" in active

        # Remove one
        dm.remove("customers")
        datasets = await dm.list_available()
        assert len(datasets) == 2
        names = [d['name'] for d in datasets]
        assert "customers" not in names

    @pytest.mark.asyncio
    async def test_query_slug_registration(self):
        """Test adding query slugs for lazy loading."""
        handler = UserObjectsHandler()
        session = {}

        agent = MagicMock()
        agent.name = "query-agent"
        agent._dataset_manager = None

        dm = await handler.configure_dataset_manager(session, agent)

        # Add query slug
        dm.add_query("monthly_sales", "sales_monthly_report")

        # Verify in list (not loaded yet)
        datasets = await dm.list_available()
        assert len(datasets) == 1
        assert datasets[0]['name'] == "monthly_sales"
        assert datasets[0]['loaded'] is False


class TestSessionPersistence:
    """Integration tests for session-scoped DatasetManager persistence."""

    @pytest.mark.asyncio
    async def test_session_persistence(self):
        """DatasetManager persists across multiple handler calls."""
        handler = UserObjectsHandler()
        session = {}

        agent = MagicMock()
        agent.name = "test-agent"
        agent._dataset_manager = None

        # First call - create DM
        dm1 = await handler.configure_dataset_manager(session, agent)
        dm1.add_dataframe("first", pd.DataFrame({'a': [1]}))

        # Second call - should get same DM
        dm2 = await handler.configure_dataset_manager(session, agent)

        assert dm1 is dm2
        datasets = await dm2.list_available()
        names = [d['name'] for d in datasets]
        assert "first" in names

    @pytest.mark.asyncio
    async def test_session_isolation_by_agent(self):
        """Different agents have isolated DatasetManagers in same session."""
        handler = UserObjectsHandler()
        session = {}

        agent1 = MagicMock()
        agent1.name = "agent-alpha"
        agent1._dataset_manager = None

        agent2 = MagicMock()
        agent2.name = "agent-beta"
        agent2._dataset_manager = None

        # Get DMs for both agents
        dm1 = await handler.configure_dataset_manager(session, agent1)
        dm2 = await handler.configure_dataset_manager(session, agent2)

        # They should be different instances
        assert dm1 is not dm2

        # Add data to one
        dm1.add_dataframe("alpha_data", pd.DataFrame({'x': [1]}))

        # Verify isolation
        datasets1 = await dm1.list_available()
        datasets2 = await dm2.list_available()

        assert len(datasets1) == 1
        assert len(datasets2) == 0

    @pytest.mark.asyncio
    async def test_session_isolation_across_sessions(self):
        """Different sessions have completely isolated DatasetManagers."""
        handler = UserObjectsHandler()
        session1 = {}
        session2 = {}

        agent = MagicMock()
        agent.name = "shared-agent"
        agent._dataset_manager = None

        # Get DMs for same agent in different sessions
        dm1 = await handler.configure_dataset_manager(session1, agent)
        dm2 = await handler.configure_dataset_manager(session2, agent)

        # They should be different instances
        assert dm1 is not dm2

        # Verify session keys exist in each session
        assert "shared-agent_dataset_manager" in session1
        assert "shared-agent_dataset_manager" in session2


class TestDatasetCopyingFromAgent:
    """Integration tests for copying datasets from agent's DatasetManager."""

    @pytest.mark.asyncio
    async def test_copies_agent_datasets_to_user(self):
        """User's DM receives copies of agent's pre-configured datasets."""
        handler = UserObjectsHandler()
        session = {}

        # Create agent with pre-loaded DatasetManager
        agent_dm = DatasetManager()
        agent_dm.add_dataframe("preloaded_sales", pd.DataFrame({'month': [1, 2], 'total': [100, 200]}))
        agent_dm.add_dataframe("preloaded_inventory", pd.DataFrame({'sku': ['A', 'B']}))

        agent = MagicMock()
        agent.name = "preconfigured-agent"
        agent._dataset_manager = agent_dm

        # Get user's DM
        user_dm = await handler.configure_dataset_manager(session, agent)

        # User's DM should have copies of agent's datasets
        datasets = await user_dm.list_available()
        names = [d['name'] for d in datasets]

        assert "preloaded_sales" in names
        assert "preloaded_inventory" in names

    @pytest.mark.asyncio
    async def test_user_modifications_dont_affect_agent(self):
        """Changes to user's DM don't affect the original agent's DM."""
        handler = UserObjectsHandler()
        session = {}

        # Create agent with pre-loaded DatasetManager
        agent_dm = DatasetManager()
        original_df = pd.DataFrame({'value': [1, 2, 3]})
        agent_dm.add_dataframe("shared_data", original_df)

        agent = MagicMock()
        agent.name = "agent-with-data"
        agent._dataset_manager = agent_dm

        # Get user's DM
        user_dm = await handler.configure_dataset_manager(session, agent)

        # Modify user's copy
        user_dm.add_dataframe("user_only", pd.DataFrame({'x': [1]}))
        user_dm.deactivate("shared_data")

        # Agent's DM should be unaffected
        agent_datasets = await agent_dm.list_available()
        agent_names = [d['name'] for d in agent_datasets]

        assert "user_only" not in agent_names  # User's addition not in agent
        assert "shared_data" in agent_names

        # Agent's shared_data should still be active
        agent_active = await agent_dm.get_active()
        assert "shared_data" in agent_active


class TestToolManagerIntegration:
    """Integration tests for ToolManager and DatasetManager together."""

    @pytest.mark.asyncio
    async def test_tool_and_dataset_manager_coexist(self):
        """Both ToolManager and DatasetManager can exist in same session."""
        handler = UserObjectsHandler()
        session = {}

        agent = MagicMock()
        agent.name = "full-agent"
        agent._dataset_manager = None

        # Configure DatasetManager
        dm = await handler.configure_dataset_manager(session, agent)
        dm.add_dataframe("data", pd.DataFrame({'x': [1]}))

        # Verify both keys can exist in session
        # (ToolManager would be configured via configure_tool_manager)
        dm_key = handler.get_session_key("full-agent", "dataset_manager")
        tm_key = handler.get_session_key("full-agent", "tool_manager")

        assert dm_key in session
        # ToolManager not configured yet, so key shouldn't exist
        assert tm_key not in session

        # Session should support both types
        session[tm_key] = "mock_tool_manager"
        assert dm_key in session
        assert tm_key in session


class TestEdgeCases:
    """Edge case tests for DatasetManager integration."""

    @pytest.mark.asyncio
    async def test_none_session_handling(self):
        """Handler works correctly with None session."""
        handler = UserObjectsHandler()

        agent = MagicMock()
        agent.name = "orphan-agent"
        agent._dataset_manager = None

        # Should not raise, should return a valid DM
        dm = await handler.configure_dataset_manager(None, agent)

        assert isinstance(dm, DatasetManager)
        dm.add_dataframe("test", pd.DataFrame({'x': [1]}))
        datasets = await dm.list_available()
        assert len(datasets) == 1

    @pytest.mark.asyncio
    async def test_agent_without_dataset_manager_attr(self):
        """Handler works with agent that has no _dataset_manager attribute."""
        handler = UserObjectsHandler()
        session = {}

        # Agent without _dataset_manager (not a PandasAgent)
        agent = MagicMock(spec=['name'])
        agent.name = "basic-agent"

        dm = await handler.configure_dataset_manager(session, agent)

        assert isinstance(dm, DatasetManager)
        datasets = await dm.list_available()
        assert len(datasets) == 0  # Empty, since agent had no datasets

    @pytest.mark.asyncio
    async def test_empty_agent_name(self):
        """Handler works with empty agent name."""
        handler = UserObjectsHandler()
        session = {}

        agent = MagicMock()
        agent.name = ""
        agent._dataset_manager = None

        dm = await handler.configure_dataset_manager(session, agent, agent_name="")

        assert isinstance(dm, DatasetManager)
        # Key should be just "dataset_manager" without prefix
        assert "dataset_manager" in session

    @pytest.mark.asyncio
    async def test_custom_agent_name_override(self):
        """Handler uses custom agent_name when provided."""
        handler = UserObjectsHandler()
        session = {}

        agent = MagicMock()
        agent.name = "original-name"
        agent._dataset_manager = None

        dm = await handler.configure_dataset_manager(
            session, agent, agent_name="custom-name"
        )

        assert isinstance(dm, DatasetManager)
        assert "custom-name_dataset_manager" in session
        assert "original-name_dataset_manager" not in session

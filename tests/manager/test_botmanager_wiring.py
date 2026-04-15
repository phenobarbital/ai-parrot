"""Unit tests for BotManager wiring — registry.setup(app) call (TASK-711).

Tests verify that load_bots() calls registry.setup(app) before load_modules().
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch


class TestBotManagerWiring:
    """Tests for BotManager.load_bots() registry.setup() wiring."""

    def _make_mock_manager(self):
        """Create a BotManager-like mock with the load_bots method bound."""
        from parrot.manager.manager import BotManager

        # Create a BotManager with a temporary agents_dir
        import tempfile
        from pathlib import Path
        from parrot.registry.registry import AgentRegistry

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = AgentRegistry(agents_dir=Path(tmpdir) / "agents")

        # Create a minimal BotManager subclass with mocked async methods
        manager = MagicMock(spec=BotManager)
        manager.enable_registry_bots = True
        manager.enable_database_bots = False
        manager.registry = registry
        manager.load_bots = BotManager.load_bots.__get__(manager, BotManager)
        return manager, registry

    @pytest.mark.asyncio
    async def test_load_bots_calls_registry_setup(self):
        """load_bots() calls registry.setup(app)."""
        from parrot.manager.manager import BotManager

        manager = MagicMock(spec=BotManager)
        manager.enable_registry_bots = True
        manager.enable_database_bots = False

        mock_registry = MagicMock()
        mock_registry.setup = MagicMock()
        mock_registry.load_modules = AsyncMock()
        mock_registry.discover_config_agents = MagicMock(return_value=0)
        mock_registry.agents_dir = MagicMock()
        mock_registry.agents_dir.__truediv__ = MagicMock(return_value=MagicMock(is_dir=lambda: False))
        mock_registry.instantiate_startup_agents = AsyncMock(return_value=[])
        manager.registry = mock_registry
        manager.logger = MagicMock()
        manager._process_startup_results = AsyncMock()
        manager._log_final_state = MagicMock()

        mock_app = MagicMock()
        await BotManager.load_bots(manager, mock_app)

        mock_registry.setup.assert_called_once_with(mock_app)

    @pytest.mark.asyncio
    async def test_load_bots_setup_before_modules(self):
        """registry.setup(app) is called before registry.load_modules()."""
        from parrot.manager.manager import BotManager

        call_order = []

        manager = MagicMock(spec=BotManager)
        manager.enable_registry_bots = True
        manager.enable_database_bots = False

        mock_registry = MagicMock()

        def track_setup(app):
            call_order.append('setup')

        async def track_load_modules():
            call_order.append('load_modules')

        mock_registry.setup = MagicMock(side_effect=track_setup)
        mock_registry.load_modules = AsyncMock(side_effect=track_load_modules)
        mock_registry.discover_config_agents = MagicMock(return_value=0)
        mock_registry.agents_dir = MagicMock()
        mock_registry.agents_dir.__truediv__ = MagicMock(
            return_value=MagicMock(is_dir=lambda: False)
        )
        mock_registry.instantiate_startup_agents = AsyncMock(return_value=[])
        manager.registry = mock_registry
        manager.logger = MagicMock()
        manager._process_startup_results = AsyncMock()
        manager._log_final_state = MagicMock()

        mock_app = MagicMock()
        await BotManager.load_bots(manager, mock_app)

        # Verify ordering
        assert call_order.index('setup') < call_order.index('load_modules'), (
            f"setup() should be called before load_modules(), got order: {call_order}"
        )

    @pytest.mark.asyncio
    async def test_load_bots_no_registry_bots_skips_setup(self):
        """registry.setup(app) is inside the enable_registry_bots block."""
        from parrot.manager.manager import BotManager

        manager = MagicMock(spec=BotManager)
        manager.enable_registry_bots = False  # Registry loading disabled
        manager.enable_database_bots = False

        mock_registry = MagicMock()
        mock_registry.setup = MagicMock()
        manager.registry = mock_registry
        manager.logger = MagicMock()
        manager._log_final_state = MagicMock()

        mock_app = MagicMock()
        await BotManager.load_bots(manager, mock_app)

        # setup() should NOT be called when registry bots are disabled
        mock_registry.setup.assert_not_called()

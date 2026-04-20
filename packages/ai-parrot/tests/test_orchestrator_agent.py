"""Tests for OrchestratorAgent enhancements."""
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# The conftest installs module stubs via sys.modules.setdefault(), which means
# any module already present in sys.modules keeps the real implementation.
# Force-remove any previously installed stubs for the modules we need real
# implementations of, then import the real parrot modules.
# ---------------------------------------------------------------------------

for _key in list(sys.modules.keys()):
    if (
        "parrot.models" in _key
        or "parrot.bots" in _key
        or "parrot.clients" in _key
        or "parrot.tools" in _key
        or "parrot.registry" in _key
    ):
        sys.modules.pop(_key, None)

from parrot.bots.orchestration.agent import OrchestratorAgent  # noqa: E402
from parrot.models.responses import AIMessage  # noqa: E402
from parrot.models.basic import CompletionUsage  # noqa: E402


def _make_ai_message(**overrides) -> AIMessage:
    defaults = {
        "input": "test",
        "output": "test answer",
        "model": "test-model",
        "provider": "test",
        "usage": CompletionUsage(),
        "metadata": {},
    }
    defaults.update(overrides)
    return AIMessage(**defaults)


def _make_mock_agent(name: str):
    agent = MagicMock()
    agent.name = name
    agent.role = f"{name} role"
    agent.goal = f"{name} goal"
    agent.capabilities = None
    agent.is_configured = True
    agent.tool_manager = MagicMock()
    return agent


class TestRegistryIntegration:

    @pytest.mark.asyncio
    @patch("parrot.bots.orchestration.agent.agent_registry")
    async def test_add_agent_by_name_resolves_from_registry(self, mock_registry):
        mock_agent = _make_mock_agent("finance_pokemon")
        mock_registry.get_instance = AsyncMock(return_value=mock_agent)

        orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)
        orchestrator.agent_tools = {}
        orchestrator.specialist_agents = {}
        orchestrator._llm = None
        orchestrator.tool_manager = MagicMock()
        orchestrator.logger = MagicMock()

        await orchestrator.add_agent_by_name("finance_pokemon")

        mock_registry.get_instance.assert_awaited_once_with("finance_pokemon")
        assert "finance_pokemon" in orchestrator.specialist_agents

    @pytest.mark.asyncio
    @patch("parrot.bots.orchestration.agent.agent_registry")
    async def test_add_agent_by_name_raises_on_not_found(self, mock_registry):
        mock_registry.get_instance = AsyncMock(return_value=None)

        orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)
        orchestrator.agent_tools = {}
        orchestrator.specialist_agents = {}
        orchestrator.logger = MagicMock()

        with pytest.raises(ValueError, match="not found in registry"):
            await orchestrator.add_agent_by_name("nonexistent_agent")

    @pytest.mark.asyncio
    @patch("parrot.bots.orchestration.agent.agent_registry")
    async def test_add_agent_by_name_with_custom_tool_name(self, mock_registry):
        mock_agent = _make_mock_agent("finance_epson")
        mock_registry.get_instance = AsyncMock(return_value=mock_agent)

        orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)
        orchestrator.agent_tools = {}
        orchestrator.specialist_agents = {}
        orchestrator._llm = None
        orchestrator.tool_manager = MagicMock()
        orchestrator.logger = MagicMock()

        await orchestrator.add_agent_by_name(
            "finance_epson",
            tool_name="epson_data",
            description="Epson financial data"
        )

        assert "epson_data" in orchestrator.agent_tools
        assert orchestrator.agent_tools["epson_data"].description == "Epson financial data"

    def test_agent_names_stored_as_pending(self):
        with patch("parrot.bots.orchestration.agent.BasicAgent.__init__", return_value=None):
            orchestrator = OrchestratorAgent(
                name="TestOrch",
                agent_names=["agent_a", "agent_b"],
            )
            orchestrator.agent_tools = {}
            orchestrator.specialist_agents = {}
            assert orchestrator._pending_agent_names == ["agent_a", "agent_b"]

    def test_agent_names_defaults_to_empty(self):
        with patch("parrot.bots.orchestration.agent.BasicAgent.__init__", return_value=None):
            orchestrator = OrchestratorAgent(name="TestOrch")
            orchestrator.agent_tools = {}
            orchestrator.specialist_agents = {}
            assert orchestrator._pending_agent_names == []

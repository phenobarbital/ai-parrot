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
from parrot.models.crew import AgentResult  # noqa: E402
from parrot.bots.flow.storage.memory import ExecutionMemory  # noqa: E402


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


class TestPassthroughMode:

    def _make_orchestrator(self):
        orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)
        orchestrator.agent_tools = {}
        orchestrator.specialist_agents = {}
        orchestrator._llm = None
        orchestrator.tool_manager = MagicMock()
        orchestrator.logger = MagicMock()
        return orchestrator

    def test_is_passthrough_eligible_with_data(self):
        orchestrator = self._make_orchestrator()
        specialist_msg = _make_ai_message(data={"revenue": [100]})
        memory = ExecutionMemory(original_query="test")
        memory.results["agent_a"] = AgentResult(
            agent_id="agent_a",
            agent_name="Agent A",
            task="test",
            result="text",
            ai_message=specialist_msg,
            metadata={},
            execution_time=1.0,
        )
        orchestrator._execution_memory = memory
        orch_response = _make_ai_message()
        assert orchestrator._is_passthrough_eligible(orch_response) is True

    def test_is_passthrough_eligible_with_artifacts(self):
        orchestrator = self._make_orchestrator()
        specialist_msg = _make_ai_message(
            artifacts=[{"type": "sql", "content": "SELECT *"}]
        )
        memory = ExecutionMemory(original_query="test")
        memory.results["agent_a"] = AgentResult(
            agent_id="agent_a",
            agent_name="Agent A",
            task="test",
            result="text",
            ai_message=specialist_msg,
            metadata={},
            execution_time=1.0,
        )
        orchestrator._execution_memory = memory
        assert orchestrator._is_passthrough_eligible(_make_ai_message()) is True

    def test_is_passthrough_eligible_with_code(self):
        orchestrator = self._make_orchestrator()
        specialist_msg = _make_ai_message(code="df.sum()")
        memory = ExecutionMemory(original_query="test")
        memory.results["agent_a"] = AgentResult(
            agent_id="agent_a",
            agent_name="Agent A",
            task="test",
            result="text",
            ai_message=specialist_msg,
            metadata={},
            execution_time=1.0,
        )
        orchestrator._execution_memory = memory
        assert orchestrator._is_passthrough_eligible(_make_ai_message()) is True

    def test_not_passthrough_eligible_text_only(self):
        orchestrator = self._make_orchestrator()
        specialist_msg = _make_ai_message()  # no data, no artifacts, no code
        memory = ExecutionMemory(original_query="test")
        memory.results["agent_a"] = AgentResult(
            agent_id="agent_a",
            agent_name="Agent A",
            task="test",
            result="text",
            ai_message=specialist_msg,
            metadata={},
            execution_time=1.0,
        )
        orchestrator._execution_memory = memory
        assert orchestrator._is_passthrough_eligible(_make_ai_message()) is False

    def test_not_passthrough_eligible_no_ai_message(self):
        orchestrator = self._make_orchestrator()
        memory = ExecutionMemory(original_query="test")
        memory.results["agent_a"] = AgentResult(
            agent_id="agent_a",
            agent_name="Agent A",
            task="test",
            result="text",
            ai_message=None,
            metadata={},
            execution_time=1.0,
        )
        orchestrator._execution_memory = memory
        assert orchestrator._is_passthrough_eligible(_make_ai_message()) is False

    def test_build_passthrough_response(self):
        orchestrator = self._make_orchestrator()
        specialist_msg = _make_ai_message(
            output="Q4 revenue is $1M",
            data={"revenue": [1000000]},
            code="df['revenue'].sum()",
        )
        orch_response = _make_ai_message(
            input="What is Q4 revenue for Pokemon?",
            output="Here is the Q4 revenue...",
        )
        orch_response.session_id = "session-123"
        orch_response.turn_id = "turn-456"

        agent_results = {
            "pokemon_finance": AgentResult(
                agent_id="pokemon_finance",
                agent_name="pokemon_finance",
                task="Q4 revenue",
                result="Q4 revenue is $1M",
                ai_message=specialist_msg,
                metadata={},
                execution_time=1.0,
            )
        }

        result = orchestrator._build_passthrough_response(orch_response, agent_results)

        assert result is specialist_msg
        assert result.data == {"revenue": [1000000]}
        assert result.code == "df['revenue'].sum()"
        assert result.session_id == "session-123"
        assert result.turn_id == "turn-456"
        assert result.input == "What is Q4 revenue for Pokemon?"
        assert result.metadata["orchestrated"] is True
        assert result.metadata["mode"] == "passthrough"
        assert result.metadata["routed_to"] == "pokemon_finance"

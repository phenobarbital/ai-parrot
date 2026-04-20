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
from parrot.tools.agent import AgentTool  # noqa: E402


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
        assert orchestrator._is_passthrough_eligible(dict(memory.results)) is True

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
        assert orchestrator._is_passthrough_eligible(dict(memory.results)) is True

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
        assert orchestrator._is_passthrough_eligible(dict(memory.results)) is True

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
        assert orchestrator._is_passthrough_eligible(dict(memory.results)) is False

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
        assert orchestrator._is_passthrough_eligible(dict(memory.results)) is False

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

        assert result is not specialist_msg  # model_copy creates a new object
        assert result.data == {"revenue": [1000000]}
        assert result.code == "df['revenue'].sum()"
        assert result.session_id == "session-123"
        assert result.turn_id == "turn-456"
        assert result.input == "What is Q4 revenue for Pokemon?"
        assert result.metadata["orchestrated"] is True
        assert result.metadata["mode"] == "passthrough"
        assert result.metadata["routed_to"] == "pokemon_finance"
        assert specialist_msg.session_id != "session-123"  # original not mutated


class TestSynthesisMode:

    def _make_orchestrator(self):
        orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)
        orchestrator.agent_tools = {}
        orchestrator.specialist_agents = {}
        orchestrator._llm = None
        orchestrator.tool_manager = MagicMock()
        orchestrator.logger = MagicMock()
        return orchestrator

    def test_build_synthesis_merges_data_per_agent(self):
        orchestrator = self._make_orchestrator()
        orch_response = _make_ai_message(
            output="Pokemon margin 32%, Epson margin 28%",
        )

        agent_results = {
            "pokemon_finance": AgentResult(
                agent_id="pokemon_finance",
                agent_name="pokemon_finance",
                task="margins",
                result="32%",
                ai_message=_make_ai_message(data={"margin": 0.32}),
                metadata={},
                execution_time=1.0,
            ),
            "epson_finance": AgentResult(
                agent_id="epson_finance",
                agent_name="epson_finance",
                task="margins",
                result="28%",
                ai_message=_make_ai_message(data={"margin": 0.28}),
                metadata={},
                execution_time=1.0,
            ),
        }

        result = orchestrator._build_synthesis_response(orch_response, agent_results)

        assert result is orch_response
        assert result.output == "Pokemon margin 32%, Epson margin 28%"
        assert result.data == {
            "pokemon_finance": {"margin": 0.32},
            "epson_finance": {"margin": 0.28},
        }
        assert result.metadata["orchestrated"] is True
        assert result.metadata["mode"] == "synthesis"
        assert set(result.metadata["agents_consulted"]) == {"pokemon_finance", "epson_finance"}

    def test_build_synthesis_merges_artifacts_with_attribution(self):
        orchestrator = self._make_orchestrator()
        orch_response = _make_ai_message()

        agent_results = {
            "agent_a": AgentResult(
                agent_id="agent_a",
                agent_name="agent_a",
                task="task",
                result="text",
                ai_message=_make_ai_message(
                    artifacts=[{"type": "sql", "content": "SELECT a"}]
                ),
                metadata={},
                execution_time=1.0,
            ),
            "agent_b": AgentResult(
                agent_id="agent_b",
                agent_name="agent_b",
                task="task",
                result="text",
                ai_message=_make_ai_message(
                    artifacts=[{"type": "sql", "content": "SELECT b"}]
                ),
                metadata={},
                execution_time=1.0,
            ),
        }

        result = orchestrator._build_synthesis_response(orch_response, agent_results)

        assert len(result.artifacts) == 2
        assert result.artifacts[0]["source_agent"] == "agent_a"
        assert result.artifacts[1]["source_agent"] == "agent_b"

    def test_build_synthesis_skips_agents_without_ai_message(self):
        orchestrator = self._make_orchestrator()
        orch_response = _make_ai_message()

        agent_results = {
            "agent_a": AgentResult(
                agent_id="agent_a",
                agent_name="agent_a",
                task="task",
                result="text",
                ai_message=_make_ai_message(data={"x": 1}),
                metadata={},
                execution_time=1.0,
            ),
            "agent_b": AgentResult(
                agent_id="agent_b",
                agent_name="agent_b",
                task="task",
                result="text only",
                ai_message=None,
                metadata={},
                execution_time=1.0,
            ),
        }

        result = orchestrator._build_synthesis_response(orch_response, agent_results)

        assert result.data == {"agent_a": {"x": 1}}

    def test_build_synthesis_no_data_leaves_response_data_unchanged(self):
        orchestrator = self._make_orchestrator()
        orch_response = _make_ai_message()

        agent_results = {
            "agent_a": AgentResult(
                agent_id="agent_a",
                agent_name="agent_a",
                task="task",
                result="text",
                ai_message=_make_ai_message(),  # no data
                metadata={},
                execution_time=1.0,
            ),
        }

        result = orchestrator._build_synthesis_response(orch_response, agent_results)

        assert result.data is None
        assert result.metadata["mode"] == "synthesis"

    def test_build_synthesis_merges_source_documents(self):
        orchestrator = self._make_orchestrator()
        orch_response = _make_ai_message()

        from parrot.models.responses import SourceDocument
        doc_a = SourceDocument(source="db_a", filename="report_a.csv")
        doc_b = SourceDocument(source="db_b", filename="report_b.csv")

        agent_results = {
            "agent_a": AgentResult(
                agent_id="agent_a",
                agent_name="agent_a",
                task="task",
                result="text",
                ai_message=_make_ai_message(source_documents=[doc_a]),
                metadata={},
                execution_time=1.0,
            ),
            "agent_b": AgentResult(
                agent_id="agent_b",
                agent_name="agent_b",
                task="task",
                result="text",
                ai_message=_make_ai_message(source_documents=[doc_b]),
                metadata={},
                execution_time=1.0,
            ),
        }

        result = orchestrator._build_synthesis_response(orch_response, agent_results)

        assert len(result.source_documents) == 2
        sources = [d.source for d in result.source_documents]
        assert "db_a" in sources
        assert "db_b" in sources


class TestOrchestratorAsk:

    def _make_orchestrator_with_tools(self):
        orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)
        orchestrator.agent_tools = {}
        orchestrator.specialist_agents = {}
        orchestrator._llm = None
        orchestrator.tool_manager = MagicMock()
        orchestrator.logger = MagicMock()
        return orchestrator

    @pytest.mark.asyncio
    async def test_ask_passthrough_single_agent_with_data(self):
        orchestrator = self._make_orchestrator_with_tools()

        specialist_msg = _make_ai_message(
            output="Revenue is $1M",
            data={"revenue": [1000000]},
        )

        orch_response = _make_ai_message(
            input="What is Pokemon revenue?",
            output="Here is the revenue data",
        )
        orch_response.session_id = "s1"
        orch_response.turn_id = "t1"

        async def fake_super_ask(question, **kwargs):
            orchestrator._execution_memory.results["pokemon_finance"] = AgentResult(
                agent_id="pokemon_finance",
                agent_name="pokemon_finance",
                task=question,
                result="Revenue is $1M",
                ai_message=specialist_msg,
                metadata={},
                execution_time=1.0,
            )
            return orch_response

        mock_agent = _make_mock_agent("pokemon_finance")
        mock_tool = AgentTool(agent=mock_agent)
        orchestrator.agent_tools["pokemon_finance"] = mock_tool

        with patch.object(
            OrchestratorAgent.__bases__[0], "ask",
            side_effect=fake_super_ask
        ):
            result = await orchestrator.ask("What is Pokemon revenue?")

        assert result is not specialist_msg  # model_copy creates a new object
        assert result.data == {"revenue": [1000000]}
        assert result.metadata["mode"] == "passthrough"
        assert result.session_id == "s1"

    @pytest.mark.asyncio
    async def test_ask_synthesis_multiple_agents(self):
        orchestrator = self._make_orchestrator_with_tools()

        pokemon_msg = _make_ai_message(data={"margin": 0.32})
        epson_msg = _make_ai_message(data={"margin": 0.28})

        orch_response = _make_ai_message(
            input="Compare margins",
            output="Pokemon 32% vs Epson 28%",
        )
        orch_response.session_id = "s1"
        orch_response.turn_id = "t1"

        async def fake_super_ask(question, **kwargs):
            orchestrator._execution_memory.results["pokemon_finance"] = AgentResult(
                agent_id="pokemon_finance",
                agent_name="pokemon_finance",
                task=question,
                result="32%",
                ai_message=pokemon_msg,
                metadata={},
                execution_time=1.0,
            )
            orchestrator._execution_memory.results["epson_finance"] = AgentResult(
                agent_id="epson_finance",
                agent_name="epson_finance",
                task=question,
                result="28%",
                ai_message=epson_msg,
                metadata={},
                execution_time=1.0,
            )
            return orch_response

        mock_agent_a = _make_mock_agent("pokemon_finance")
        mock_agent_b = _make_mock_agent("epson_finance")
        orchestrator.agent_tools["pokemon_finance"] = AgentTool(agent=mock_agent_a)
        orchestrator.agent_tools["epson_finance"] = AgentTool(agent=mock_agent_b)

        with patch.object(
            OrchestratorAgent.__bases__[0], "ask",
            side_effect=fake_super_ask
        ):
            result = await orchestrator.ask("Compare margins")

        assert result is orch_response
        assert result.output == "Pokemon 32% vs Epson 28%"
        assert result.data == {
            "pokemon_finance": {"margin": 0.32},
            "epson_finance": {"margin": 0.28},
        }
        assert result.metadata["mode"] == "synthesis"

    @pytest.mark.asyncio
    async def test_ask_no_agents_called_returns_base_response(self):
        orchestrator = self._make_orchestrator_with_tools()

        orch_response = _make_ai_message(output="I don't know")

        async def fake_super_ask(question, **kwargs):
            return orch_response

        with patch.object(
            OrchestratorAgent.__bases__[0], "ask",
            side_effect=fake_super_ask
        ):
            result = await orchestrator.ask("Something unrelated")

        assert result is orch_response
        assert result.data is None

    @pytest.mark.asyncio
    async def test_ask_init_execution_memory_wires_all_tools(self):
        orchestrator = self._make_orchestrator_with_tools()

        mock_agent_a = _make_mock_agent("agent_a")
        mock_agent_b = _make_mock_agent("agent_b")
        tool_a = AgentTool(agent=mock_agent_a)
        tool_b = AgentTool(agent=mock_agent_b)
        orchestrator.agent_tools["agent_a"] = tool_a
        orchestrator.agent_tools["agent_b"] = tool_b

        orchestrator._init_execution_memory("test query")

        assert tool_a.execution_memory is orchestrator._execution_memory
        assert tool_b.execution_memory is orchestrator._execution_memory
        assert orchestrator._execution_memory.original_query == "test query"

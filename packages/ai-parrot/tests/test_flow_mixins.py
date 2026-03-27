"""Tests for PersistenceMixin, SynthesisMixin, and AgentsFlow integration.

Validates that the shared mixins work correctly and that AgentsFlow
properly integrates on_agent_complete, synthesis, persistence, and ask().
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.bots.flow.fsm import (
    AgentsFlow,
    AgentTaskMachine,
    TransitionCondition,
)
from parrot.bots.flow.nodes import StartNode, EndNode
from parrot.bots.flow.storage.persistence import PersistenceMixin
from parrot.bots.flow.storage.synthesis import SynthesisMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeAgent:
    """Minimal duck-typed agent for testing."""

    is_configured: bool = True

    def __init__(self, name: str, response: str = "ok"):
        self._name = name
        self._response = response
        self.tool_manager = MagicMock()
        self.tool_manager.list_tools.return_value = []

    @property
    def name(self) -> str:
        return self._name

    async def ask(self, question: str = "", **ctx) -> str:
        return self._response

    async def configure(self) -> None:
        pass


class _PersistenceHost(PersistenceMixin):
    """Concrete host for PersistenceMixin tests."""

    def __init__(self, name: str = "test"):
        import logging

        self.name = name
        self.logger = logging.getLogger("test")


class _SynthesisHost(SynthesisMixin):
    """Concrete host for SynthesisMixin tests."""

    def __init__(self):
        import logging

        self.logger = logging.getLogger("test")


# ---------------------------------------------------------------------------
# PersistenceMixin tests
# ---------------------------------------------------------------------------


class TestPersistenceMixin:
    """Tests for the PersistenceMixin."""

    @pytest.mark.asyncio
    async def test_save_result_calls_documentdb(self):
        """_save_result writes to DocumentDB with correct collection and data."""
        host = _PersistenceHost(name="my_crew")
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "parrot.interfaces.documentdb.DocumentDb",
            return_value=mock_db,
        ):
            await host._save_result("result_str", "run_flow", user_id="u1")

        mock_db.write.assert_called_once()
        args = mock_db.write.call_args
        assert args[0][0] == "crew_executions"  # default collection
        data = args[0][1]
        assert data["crew_name"] == "my_crew"
        assert data["method"] == "run_flow"
        assert data["user_id"] == "u1"

    @pytest.mark.asyncio
    async def test_save_result_custom_collection(self):
        """_save_result uses the provided collection name."""
        host = _PersistenceHost()
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "parrot.interfaces.documentdb.DocumentDb",
            return_value=mock_db,
        ):
            await host._save_result(
                "result", "run_flow", collection="flow_executions"
            )

        mock_db.write.assert_called_once()
        assert mock_db.write.call_args[0][0] == "flow_executions"

    @pytest.mark.asyncio
    async def test_save_result_silences_exceptions(self):
        """_save_result logs a warning but doesn't raise on failure."""
        host = _PersistenceHost()

        with patch(
            "parrot.interfaces.documentdb.DocumentDb",
            side_effect=RuntimeError("connection lost"),
        ):
            # Should NOT raise
            await host._save_result("data", "run_flow")


# ---------------------------------------------------------------------------
# SynthesisMixin tests
# ---------------------------------------------------------------------------


class TestSynthesisMixin:
    """Tests for the SynthesisMixin."""

    @pytest.mark.asyncio
    async def test_synthesize_returns_none_without_llm(self):
        """Returns None when no LLM is provided."""
        host = _SynthesisHost()
        result = await host._synthesize_results(
            crew_result=MagicMock(),
            synthesis_prompt="Summarize",
            llm=None,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_synthesize_returns_none_without_prompt(self):
        """Returns None when no synthesis_prompt is provided."""
        host = _SynthesisHost()
        result = await host._synthesize_results(
            crew_result=MagicMock(),
            synthesis_prompt=None,
            llm=MagicMock(),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_synthesize_calls_llm_and_extracts_content(self):
        """Calls LLM and returns response.content."""
        host = _SynthesisHost()

        # Build a minimal CrewResult mock
        agent_info = MagicMock()
        agent_info.agent_name = "ResearchAgent"
        agent_info.agent_id = "research"

        crew_result = MagicMock()
        crew_result.agents = [agent_info]
        crew_result.responses = {"research": MagicMock(content="data")}

        # LLM mock
        llm_response = MagicMock()
        llm_response.content = "Synthesized summary"

        mock_client = AsyncMock()
        mock_client.ask = AsyncMock(return_value=llm_response)

        mock_llm = MagicMock()
        mock_llm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_llm.__aexit__ = AsyncMock(return_value=False)

        result = await host._synthesize_results(
            crew_result=crew_result,
            synthesis_prompt="Summarize",
            llm=mock_llm,
        )
        assert result == "Synthesized summary"
        mock_client.ask.assert_called_once()


# ---------------------------------------------------------------------------
# AgentsFlow on_agent_complete tests
# ---------------------------------------------------------------------------


class TestAgentsFlowOnAgentComplete:
    """Tests for on_agent_complete callback integration."""

    @pytest.mark.asyncio
    async def test_callback_called_after_agent_completes(self):
        """on_agent_complete is invoked with (agent_name, result, context)."""
        flow = AgentsFlow(name="test", enable_execution_memory=False)
        a = FakeAgent("A", response="hello")
        flow.add_agent(a)

        callback = AsyncMock()

        with patch(
            "parrot.interfaces.documentdb.DocumentDb",
            side_effect=RuntimeError("skip"),
        ):
            result = await flow.run_flow(
                "test task", on_agent_complete=callback
            )

        # Callback should have been called for agent A
        callback.assert_called_once()
        call_args = callback.call_args[0]
        assert call_args[0] == "A"  # agent_name
        assert call_args[1] == "hello"  # result

    @pytest.mark.asyncio
    async def test_callback_not_called_when_none(self):
        """No errors when on_agent_complete is None."""
        flow = AgentsFlow(name="test", enable_execution_memory=False)
        a = FakeAgent("A")
        flow.add_agent(a)

        with patch(
            "parrot.interfaces.documentdb.DocumentDb",
            side_effect=RuntimeError("skip"),
        ):
            result = await flow.run_flow("test task")

        assert result.status in ("completed", "partial")


# ---------------------------------------------------------------------------
# AgentsFlow synthesis integration
# ---------------------------------------------------------------------------


class TestAgentsFlowSynthesis:
    """Tests for synthesis integration in run_flow."""

    @pytest.mark.asyncio
    async def test_run_flow_with_synthesis(self):
        """run_flow populates result.summary when generate_summary=True."""
        # LLM mock
        llm_response = MagicMock()
        llm_response.content = "flow summary"

        mock_client = AsyncMock()
        mock_client.ask = AsyncMock(return_value=llm_response)

        mock_llm = MagicMock()
        mock_llm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_llm.__aexit__ = AsyncMock(return_value=False)

        flow = AgentsFlow(
            name="synth_test",
            enable_execution_memory=False,
            llm=mock_llm,
        )
        flow.add_agent(FakeAgent("worker", response="done"))

        with patch(
            "parrot.interfaces.documentdb.DocumentDb",
            side_effect=RuntimeError("skip"),
        ):
            result = await flow.run_flow(
                "test task", generate_summary=True
            )

        assert result.summary == "flow summary"
        assert result.metadata.get("synthesized") is True

    @pytest.mark.asyncio
    async def test_last_crew_result_is_set(self):
        """run_flow stores last_crew_result for use by ask()."""
        flow = AgentsFlow(name="test", enable_execution_memory=False)
        flow.add_agent(FakeAgent("A"))

        with patch(
            "parrot.interfaces.documentdb.DocumentDb",
            side_effect=RuntimeError("skip"),
        ):
            result = await flow.run_flow("task")

        assert flow.last_crew_result is result

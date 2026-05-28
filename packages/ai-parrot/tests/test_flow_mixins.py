"""Tests for PersistenceMixin, SynthesisMixin, and AgentsFlow integration.

Validates that the shared mixins work correctly and that AgentsFlow
properly integrates on_complete callbacks, persistence, and the new run_flow API.

Rewritten for FEAT-196 TASK-1314 to use the canonical APIs:
  - PersistenceMixin._save_result now delegates to ResultStorage.save() (not DocumentDb)
  - AgentsFlow.run_flow() takes an optional FlowContext; uses on_complete hooks
  - add_node(Node) replaces add_agent(agent)
"""
import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.bots.flows.flow.flow import AgentsFlow
from parrot.bots.flows.core.fsm import AgentTaskMachine, TransitionCondition
from parrot.bots.flows.core.node import StartNode, EndNode
from parrot.bots.flows.core.storage import PersistenceMixin
from parrot.bots.flows.core.storage.synthesis import SynthesisMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _PersistenceHost(PersistenceMixin):
    """Concrete host for PersistenceMixin tests."""

    def __init__(self, name: str = "test"):
        self.name = name
        self.logger = logging.getLogger("test")


class _SynthesisHost(SynthesisMixin):
    """Concrete host for SynthesisMixin tests."""

    def __init__(self):
        self.logger = logging.getLogger("test")


# ---------------------------------------------------------------------------
# PersistenceMixin tests
# ---------------------------------------------------------------------------


class TestPersistenceMixin:
    """Tests for the PersistenceMixin."""

    @pytest.mark.asyncio
    async def test_save_result_calls_backend(self):
        """_save_result writes to the ResultStorage backend with correct fields."""
        host = _PersistenceHost(name="my_crew")

        mock_storage = AsyncMock()
        mock_storage.save = AsyncMock()

        with patch(
            "parrot.bots.flows.core.storage.persistence.PersistenceMixin._ensure_result_storage",
            return_value=mock_storage,
        ):
            await host._save_result("result_str", "run_flow", user_id="u1")

        mock_storage.save.assert_called_once()
        call_args = mock_storage.save.call_args
        collection = call_args[0][0]
        data = call_args[0][1]
        assert collection == "crew_executions"  # default collection
        assert data["crew_name"] == "my_crew"
        assert data["method"] == "run_flow"
        assert data["user_id"] == "u1"

    @pytest.mark.asyncio
    async def test_save_result_custom_collection(self):
        """_save_result uses the provided collection name."""
        host = _PersistenceHost()

        mock_storage = AsyncMock()
        mock_storage.save = AsyncMock()

        with patch(
            "parrot.bots.flows.core.storage.persistence.PersistenceMixin._ensure_result_storage",
            return_value=mock_storage,
        ):
            await host._save_result(
                "result", "run_flow", collection="flow_executions"
            )

        mock_storage.save.assert_called_once()
        call_args = mock_storage.save.call_args
        assert call_args[0][0] == "flow_executions"

    @pytest.mark.asyncio
    async def test_save_result_silences_exceptions(self):
        """_save_result logs a warning but doesn't raise on failure."""
        host = _PersistenceHost()

        with patch(
            "parrot.bots.flows.core.storage.persistence.PersistenceMixin._ensure_result_storage",
            side_effect=RuntimeError("connection lost"),
        ):
            # Should NOT raise
            await host._save_result("data", "run_flow")

    @pytest.mark.asyncio
    async def test_save_result_skips_when_persist_disabled(self):
        """_save_result returns early when _persist_results is False."""
        host = _PersistenceHost()
        host._persist_results = False  # type: ignore[attr-defined]

        mock_storage = AsyncMock()
        mock_storage.save = AsyncMock()

        with patch(
            "parrot.bots.flows.core.storage.persistence.PersistenceMixin._ensure_result_storage",
            return_value=mock_storage,
        ):
            await host._save_result("data", "run_flow")

        mock_storage.save.assert_not_called()


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
# AgentsFlow integration tests (new DAG executor API)
# ---------------------------------------------------------------------------


class TestAgentsFlowNodeRegistration:
    """Tests for the new AgentsFlow.add_node() API."""

    def test_flow_starts_empty(self):
        """AgentsFlow initialises with no nodes."""
        flow = AgentsFlow(name="test")
        assert len(flow._nodes) == 0

    def test_add_node_registers_by_node_id(self):
        """add_node() registers a Node by its node_id."""
        flow = AgentsFlow(name="test")
        flow.add_node(StartNode(node_id="s1"))
        assert "s1" in flow._nodes

    def test_add_multiple_nodes(self):
        """add_node() handles multiple distinct nodes."""
        flow = AgentsFlow(name="test")
        flow.add_node(StartNode(node_id="s1"))
        flow.add_node(EndNode(node_id="e1"))
        assert len(flow._nodes) == 2

    def test_duplicate_node_raises(self):
        """add_node() raises ValueError for a duplicate node_id."""
        flow = AgentsFlow(name="test")
        flow.add_node(StartNode(node_id="dup"))
        with pytest.raises(ValueError, match="already added"):
            flow.add_node(StartNode(node_id="dup"))


class TestAgentsFlowRunFlow:
    """Tests for AgentsFlow.run_flow() with the new API."""

    @pytest.mark.asyncio
    async def test_run_empty_flow_returns_flowresult(self):
        """run_flow() returns a FlowResult even for an empty flow."""
        from parrot.bots.flows.core.result import FlowResult  # noqa: PLC0415
        flow = AgentsFlow(name="test")
        result = await flow.run_flow()
        assert isinstance(result, FlowResult)

    @pytest.mark.asyncio
    async def test_on_complete_callback_invoked(self):
        """on_complete callbacks are called after run_flow() finishes."""
        flow = AgentsFlow(name="test")
        called_with: list = []

        async def my_hook(ctx, result):
            called_with.append((ctx, result))

        result = await flow.run_flow(on_complete=(my_hook,))
        assert len(called_with) == 1
        assert called_with[0][1] is result

    @pytest.mark.asyncio
    async def test_on_complete_exception_does_not_propagate(self):
        """Exceptions in on_complete hooks are caught — run_flow still returns."""
        flow = AgentsFlow(name="test")

        async def bad_hook(ctx, result):
            raise RuntimeError("hook failure")

        # Should not raise
        result = await flow.run_flow(on_complete=(bad_hook,))
        from parrot.bots.flows.core.result import FlowResult  # noqa: PLC0415
        assert isinstance(result, FlowResult)

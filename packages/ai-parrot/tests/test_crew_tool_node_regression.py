"""Regression tests for deterministic ToolNode members in AgentCrew.

Verifies that a ToolNode (direct tool caller, no LLM) participates in all
four execution modes — sequential, parallel, flow, and loop — with its
result wrapped as a regular agent-execution result (FlowResult nodes,
context passing, FSM lifecycle).

The condition evaluation in loop mode (LLM-based) is monkeypatched to
avoid requiring real LLM access.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from _crew_test_helpers import DummyAgent, DummyTool  # shared test infrastructure
from parrot.bots.flows.crew import AgentCrew, ToolNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_crew(*agents: DummyAgent, **kwargs: Any) -> AgentCrew:
    """Create an AgentCrew with DummyAgents."""
    return AgentCrew(
        name="TestToolNodeCrew",
        agents=list(agents),
        auto_configure=False,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# add_tool_node basics
# ---------------------------------------------------------------------------


class TestAddToolNode:
    """Tests for AgentCrew.add_tool_node registration."""

    def test_registers_in_agents_and_workflow_graph(self) -> None:
        """The node must appear in both membership structures."""
        crew = _make_crew(DummyAgent("a"))
        tool = DummyTool("fetcher")
        node = crew.add_tool_node(tool, "fetch", kwargs={"q": "{input}"})
        assert isinstance(node, ToolNode)
        assert crew.agents["fetch"] is node
        assert crew.workflow_graph["fetch"] is node
        assert "fetch" in crew._agent_statuses

    def test_duplicate_node_id_raises(self) -> None:
        """Adding a member with an existing id must raise ValueError."""
        crew = _make_crew(DummyAgent("a"))
        crew.add_tool_node(DummyTool(), "fetch")
        with pytest.raises(ValueError):
            crew.add_tool_node(DummyTool(), "fetch")
        with pytest.raises(ValueError):
            crew.add_tool_node(DummyTool(), "a")  # collides with agent

    def test_add_shared_tool_after_tool_node_does_not_raise(self) -> None:
        """Shared-tool distribution must skip tool nodes (no tool_manager)."""
        crew = _make_crew(DummyAgent("a"))
        crew.add_tool_node(DummyTool(), "fetch")
        crew.add_shared_tool(DummyTool("shared"), "shared")

    def test_remove_agent_cleans_workflow_graph(self) -> None:
        """remove_agent must also drop graph and status entries."""
        crew = _make_crew(DummyAgent("a"))
        crew.add_tool_node(DummyTool(), "fetch")
        assert crew.remove_agent("fetch") is True
        assert "fetch" not in crew.agents
        assert "fetch" not in crew.workflow_graph
        assert "fetch" not in crew._agent_statuses


# ---------------------------------------------------------------------------
# Sequential mode
# ---------------------------------------------------------------------------


class TestSequentialToolNode:
    """run_sequential with a ToolNode in the pipeline."""

    async def test_agent_tool_agent_pipeline(self) -> None:
        """agent -> tool -> agent: tool output feeds the downstream agent."""
        a = DummyAgent("a", "alpha-result")
        b = DummyAgent("b", "beta-result")
        crew = _make_crew(a, b)
        tool = DummyTool("fetcher", result="TOOL-PAYLOAD")
        crew.add_tool_node(
            tool, "fetch", kwargs={"symbol": "{nodes.a.output}"}
        )
        result = await crew.run_sequential(
            "start",
            agent_sequence=["a", "fetch", "b"],
            generate_summary=False,
        )
        assert result.status == "completed"
        # Template resolved against the prior node's stored output
        assert len(tool.calls) == 1
        _, called_kwargs = tool.calls[0]
        assert "alpha-result" in called_kwargs["symbol"]
        # Downstream agent saw the tool output in its prompt
        assert any("TOOL-PAYLOAD" in p for p in b.prompts_received)
        # Tool node reported as a completed node in FlowResult
        info = {n.node_id: n for n in result.nodes}
        assert info["fetch"].status == "completed"

    async def test_input_placeholder_gets_previous_output(self) -> None:
        """{input} in sequential mode is the composed previous input."""
        a = DummyAgent("a", "alpha")
        crew = _make_crew(a)
        tool = DummyTool("fetcher")
        crew.add_tool_node(tool, "fetch", kwargs={"q": "{input}"})
        result = await crew.run_sequential(
            "start",
            agent_sequence=["a", "fetch"],
            generate_summary=False,
        )
        assert result.status == "completed"
        _, called_kwargs = tool.calls[0]
        assert "alpha" in called_kwargs["q"]

    async def test_failed_tool_marks_node_failed(self) -> None:
        """A failed ToolResult marks the node failed and the run partial."""
        a = DummyAgent("a", "alpha")
        crew = _make_crew(a)
        crew.add_tool_node(DummyTool("fetcher", fail=True), "fetch")
        result = await crew.run_sequential(
            "start",
            agent_sequence=["a", "fetch"],
            generate_summary=False,
        )
        assert result.status == "partial"
        assert "fetch" in result.errors
        info = {n.node_id: n for n in result.nodes}
        assert info["fetch"].status == "failed"
        node = crew.workflow_graph["fetch"]
        assert str(node.fsm.current_state.id) == "failed"

    async def test_fsm_completed_on_success(self) -> None:
        """The tool node FSM reaches completed on success."""
        crew = _make_crew(DummyAgent("a"))
        crew.add_tool_node(DummyTool(), "fetch")
        result = await crew.run_sequential(
            "start",
            agent_sequence=["a", "fetch"],
            generate_summary=False,
        )
        assert result.status == "completed"
        node = crew.workflow_graph["fetch"]
        assert str(node.fsm.current_state.id) == "completed"


# ---------------------------------------------------------------------------
# Flow mode
# ---------------------------------------------------------------------------


class TestFlowToolNode:
    """run_flow with ToolNode members in the DAG."""

    async def test_tool_node_between_agents(self) -> None:
        """a -> fetch(tool) -> b: template resolves the upstream output."""
        a = DummyAgent("a", "alpha-out")
        b = DummyAgent("b", "beta-out")
        crew = _make_crew(a, b)
        tool = DummyTool("fetcher", result="FLOW-PAYLOAD")
        node = crew.add_tool_node(
            tool, "fetch", kwargs={"symbol": "{nodes.a.output}"}
        )
        crew.task_flow(a, node)
        crew.task_flow(node, b)
        result = await crew.run_flow("start", generate_summary=False)
        assert result.status == "completed"
        _, called_kwargs = tool.calls[0]
        assert "alpha-out" in called_kwargs["symbol"]
        # Downstream agent consumed the tool output
        assert any("FLOW-PAYLOAD" in p for p in b.prompts_received)
        # FSM lifecycle handled by the scheduler
        assert str(crew.workflow_graph["fetch"].fsm.current_state.id) == "completed"

    async def test_tool_node_as_initial_node(self) -> None:
        """A tool node with no dependencies uses the initial task as input."""
        b = DummyAgent("b", "beta")
        crew = _make_crew(b)
        tool = DummyTool("fetcher", result="INITIAL-PAYLOAD")
        node = crew.add_tool_node(tool, "fetch", kwargs={"q": "{input}"})
        crew.task_flow(node, b)
        result = await crew.run_flow("the-initial-task", generate_summary=False)
        assert result.status == "completed"
        _, called_kwargs = tool.calls[0]
        assert called_kwargs["q"] == "the-initial-task"

    async def test_failed_tool_blocks_downstream(self) -> None:
        """A failing tool node prevents downstream agents from running."""
        b = DummyAgent("b", "beta")
        crew = _make_crew(b)
        node = crew.add_tool_node(DummyTool("fetcher", fail=True), "fetch")
        crew.task_flow(node, b)
        result = await crew.run_flow("start", generate_summary=False)
        assert result.status in ("partial", "failed")
        assert "fetch" in result.errors
        assert len(b.prompts_received) == 0
        assert str(crew.workflow_graph["fetch"].fsm.current_state.id) == "failed"

    async def test_native_type_passthrough(self) -> None:
        """A full-match placeholder inside kwargs keeps native types."""
        a = DummyAgent("a", "alpha")
        crew = _make_crew(a)
        tool = DummyTool("fetcher")
        node = crew.add_tool_node(
            tool,
            "fetch",
            kwargs={"query": "{nodes.a.output}", "top_k": 3},
        )
        crew.task_flow(a, node)
        result = await crew.run_flow("start", generate_summary=False)
        assert result.status == "completed"
        _, called_kwargs = tool.calls[0]
        assert called_kwargs["top_k"] == 3
        assert isinstance(called_kwargs["query"], str)


# ---------------------------------------------------------------------------
# Parallel mode
# ---------------------------------------------------------------------------


class TestParallelToolNode:
    """run_parallel with ToolNode tasks."""

    async def test_tool_node_task_uses_query_as_input(self) -> None:
        """{input} in parallel mode is the task's own query."""
        a = DummyAgent("a", "alpha")
        crew = _make_crew(a)
        tool = DummyTool("fetcher", result="PAR-PAYLOAD")
        crew.add_tool_node(tool, "fetch", kwargs={"symbol": "{input}"})
        result = await crew.run_parallel(
            tasks=[
                {"agent_id": "a", "query": "task-for-a"},
                {"agent_id": "fetch", "query": "AAPL"},
            ],
            generate_summary=False,
        )
        assert result.status == "completed"
        _, called_kwargs = tool.calls[0]
        assert called_kwargs["symbol"] == "AAPL"
        assert result.responses["fetch"] is not None

    async def test_failed_tool_node_partial_status(self) -> None:
        """A failing tool node yields partial status without killing others."""
        a = DummyAgent("a", "alpha")
        crew = _make_crew(a)
        crew.add_tool_node(DummyTool("fetcher", fail=True), "fetch")
        result = await crew.run_parallel(
            tasks=[
                {"agent_id": "a", "query": "task-for-a"},
                {"agent_id": "fetch", "query": "AAPL"},
            ],
            generate_summary=False,
        )
        assert result.status == "partial"
        assert "fetch" in result.errors


# ---------------------------------------------------------------------------
# Loop mode
# ---------------------------------------------------------------------------


class TestLoopToolNode:
    """run_loop with a ToolNode in the iterated sequence."""

    async def test_tool_node_runs_each_iteration(self) -> None:
        """The tool executes once per iteration with a fresh FSM."""
        a = DummyAgent("a", "alpha")
        crew = _make_crew(a)
        tool = DummyTool("fetcher", result="LOOP-PAYLOAD")
        crew.add_tool_node(tool, "fetch", kwargs={"q": "{input}"})
        with patch.object(
            crew,
            "_evaluate_loop_condition",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await crew.run_loop(
                initial_task="start",
                condition="never true",
                max_iterations=2,
                generate_summary=False,
            )
        assert result.metadata["iterations"] == 2
        assert result.status == "completed"
        assert len(tool.calls) == 2
        node = crew.workflow_graph["fetch"]
        assert str(node.fsm.current_state.id) == "completed"

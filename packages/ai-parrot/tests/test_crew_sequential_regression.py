"""Regression tests for AgentCrew.run_sequential() mode.

Tests verify execution order, output propagation, early-stop on failure,
and FSM state transitions after migration to flows.core primitives.
"""
from __future__ import annotations

from typing import Any

import pytest

from _crew_test_helpers import DummyAgent  # shared test infrastructure
from parrot.bots.orchestration.crew import AgentCrew


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_crew(*agents: DummyAgent, **kwargs: Any) -> AgentCrew:
    """Create an AgentCrew with DummyAgents, setting workflow_graph entries."""
    crew = AgentCrew(
        name="TestSeqCrew",
        agents=list(agents),
        auto_configure=False,
        **kwargs,
    )
    return crew


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSequentialRegression:
    """Regression tests for run_sequential after primitives migration."""

    async def test_execution_order_strict(self) -> None:
        """Agents execute in add_agent order."""
        a1 = DummyAgent("a1", "first")
        a2 = DummyAgent("a2", "second")
        a3 = DummyAgent("a3", "third")
        crew = _make_crew(a1, a2, a3)
        result = await crew.run_sequential(
            "start", generate_summary=False
        )
        assert result.status == "completed"
        # Check completion order via agents list
        agent_ids = [info.agent_id for info in result.agents]
        assert agent_ids == ["a1", "a2", "a3"]

    async def test_output_propagation(self) -> None:
        """Output of agent N feeds agent N+1."""
        a1 = DummyAgent("a1", "processed")
        a2 = DummyAgent("a2", "refined")
        crew = _make_crew(a1, a2)
        result = await crew.run_sequential(
            "start", generate_summary=False, pass_full_context=False,
        )
        assert result.status == "completed"
        # a2 should have received a1's output as input
        assert len(a2.prompts_received) == 1
        assert "processed" in a2.prompts_received[0]

    async def test_early_stop_on_failure(self) -> None:
        """If agent K fails, status is partial/failed."""
        a1 = DummyAgent("a1", "ok")
        a2 = DummyAgent("a2", "ok", fail=True)
        a3 = DummyAgent("a3", "ok")
        crew = _make_crew(a1, a2, a3)
        result = await crew.run_sequential(
            "start", generate_summary=False
        )
        assert result.status in ("partial", "failed")
        assert "a2" in result.errors

    async def test_fsm_states_after_sequential(self) -> None:
        """Nodes with FSMs transition correctly after successful run."""
        a1 = DummyAgent("a1", "first")
        a2 = DummyAgent("a2", "second")
        crew = _make_crew(a1, a2)
        result = await crew.run_sequential(
            "start", generate_summary=False
        )
        assert result.status == "completed"
        # Check FSM states on nodes
        node1 = crew.workflow_graph.get("a1")
        node2 = crew.workflow_graph.get("a2")
        assert node1 is not None
        assert node2 is not None
        assert str(node1.fsm.current_state.id) == "completed"
        assert str(node2.fsm.current_state.id) == "completed"

    async def test_fsm_states_after_failure(self) -> None:
        """Failed node FSM transitions to failed state."""
        a1 = DummyAgent("a1", "ok")
        a2 = DummyAgent("a2", "fail", fail=True)
        crew = _make_crew(a1, a2)
        result = await crew.run_sequential(
            "start", generate_summary=False
        )
        node1 = crew.workflow_graph.get("a1")
        node2 = crew.workflow_graph.get("a2")
        assert str(node1.fsm.current_state.id) == "completed"
        assert str(node2.fsm.current_state.id) == "failed"

    async def test_result_structure(self) -> None:
        """CrewResult has expected fields."""
        a1 = DummyAgent("a1")
        crew = _make_crew(a1)
        result = await crew.run_sequential(
            "start", generate_summary=False
        )
        assert hasattr(result, "output")
        assert hasattr(result, "status")
        assert hasattr(result, "agents")
        assert hasattr(result, "errors")
        assert hasattr(result, "total_time")
        assert hasattr(result, "metadata")
        assert result.metadata["mode"] == "sequential"

    async def test_pre_post_hooks_fire(self) -> None:
        """Pre/post action hooks fire for each agent in sequential mode."""
        hook_log: list = []

        def pre_hook(name, prompt, **ctx):
            hook_log.append(("pre", name))

        def post_hook(name, result, **ctx):
            hook_log.append(("post", name))

        a1 = DummyAgent("a1", "ok")
        a2 = DummyAgent("a2", "ok")
        crew = _make_crew(a1, a2)

        # Register hooks on nodes
        crew.workflow_graph["a1"].add_pre_action(pre_hook)
        crew.workflow_graph["a1"].add_post_action(post_hook)
        crew.workflow_graph["a2"].add_pre_action(pre_hook)
        crew.workflow_graph["a2"].add_post_action(post_hook)

        await crew.run_sequential("start", generate_summary=False)
        assert ("pre", "a1") in hook_log
        assert ("post", "a1") in hook_log
        assert ("pre", "a2") in hook_log
        assert ("post", "a2") in hook_log

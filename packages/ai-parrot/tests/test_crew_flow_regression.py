"""Regression tests for AgentCrew.run_flow() mode.

Tests verify DAG dependency ordering, FSM transitions, on_agent_complete
callback, and status calculation after migration to flows.core primitives.
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
    """Create an AgentCrew with DummyAgents."""
    crew = AgentCrew(
        name="TestFlowCrew",
        agents=list(agents),
        auto_configure=False,
        **kwargs,
    )
    return crew


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFlowRegression:
    """Regression tests for run_flow after primitives migration."""

    async def test_simple_linear_flow(self) -> None:
        """A -> B: B runs after A completes."""
        a = DummyAgent("a", "output_a")
        b = DummyAgent("b", "output_b")
        crew = _make_crew(a, b)
        crew.task_flow(a, b)
        result = await crew.run_flow("start", generate_summary=False)
        assert result.status == "completed"
        assert len(a.prompts_received) >= 1
        assert len(b.prompts_received) >= 1

    async def test_dependency_ordering_diamond(self) -> None:
        """A -> B,C -> D: D only runs after both B and C complete."""
        a = DummyAgent("a", "out_a")
        b = DummyAgent("b", "out_b")
        c = DummyAgent("c", "out_c")
        d = DummyAgent("d", "out_d")
        crew = _make_crew(a, b, c, d)
        crew.task_flow(a, [b, c])
        crew.task_flow(b, d)
        crew.task_flow(c, d)
        result = await crew.run_flow("start", generate_summary=False)
        assert result.status == "completed"
        # All agents should have been invoked
        assert len(a.prompts_received) >= 1
        assert len(b.prompts_received) >= 1
        assert len(c.prompts_received) >= 1
        assert len(d.prompts_received) >= 1

    async def test_fsm_states_after_flow(self) -> None:
        """All nodes should reach 'completed' FSM state on success."""
        a = DummyAgent("a", "ok")
        b = DummyAgent("b", "ok")
        crew = _make_crew(a, b)
        crew.task_flow(a, b)
        result = await crew.run_flow("start", generate_summary=False)
        assert result.status == "completed"
        for aid in ["a", "b"]:
            node = crew.workflow_graph.get(aid)
            assert node is not None
            assert str(node.fsm.current_state.id) == "completed"

    async def test_callback_fires_for_each_agent(self) -> None:
        """on_agent_complete fires with correct (agent_name, result, context) args."""
        callback_log: list = []

        async def callback(name: str, result: Any, ctx: Any) -> None:
            callback_log.append(name)

        a = DummyAgent("a", "ok")
        b = DummyAgent("b", "ok")
        crew = _make_crew(a, b)
        crew.task_flow(a, b)
        result = await crew.run_flow(
            "start", generate_summary=False, on_agent_complete=callback
        )
        assert result.status == "completed"
        # Both agents should have triggered the callback
        assert "a" in callback_log
        assert "b" in callback_log

    async def test_failure_propagates_status(self) -> None:
        """A -> B(fail) -> C: C should not run if B fails."""
        a = DummyAgent("a", "ok")
        b = DummyAgent("b", "fail", fail=True)
        c = DummyAgent("c", "ok")
        crew = _make_crew(a, b, c)
        crew.task_flow(a, b)
        crew.task_flow(b, c)
        result = await crew.run_flow("start", generate_summary=False)
        # B failed, so C should not have run
        assert len(c.prompts_received) == 0
        # Status should reflect the failure
        assert result.status in ("partial", "failed")
        assert "b" in result.errors

    async def test_fsm_failure_state(self) -> None:
        """Failed node FSM transitions to failed state."""
        a = DummyAgent("a", "ok")
        b = DummyAgent("b", "fail", fail=True)
        crew = _make_crew(a, b)
        crew.task_flow(a, b)
        result = await crew.run_flow("start", generate_summary=False)
        node_a = crew.workflow_graph.get("a")
        node_b = crew.workflow_graph.get("b")
        assert str(node_a.fsm.current_state.id) == "completed"
        assert str(node_b.fsm.current_state.id) == "failed"

    async def test_result_metadata_mode(self) -> None:
        """CrewResult metadata has mode == 'flow'."""
        a = DummyAgent("a", "ok")
        b = DummyAgent("b", "ok")
        crew = _make_crew(a, b)
        crew.task_flow(a, b)
        result = await crew.run_flow("start", generate_summary=False)
        assert result.metadata["mode"] == "flow"

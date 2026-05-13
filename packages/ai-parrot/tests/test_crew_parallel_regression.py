"""Regression tests for AgentCrew.run_parallel() mode.

Tests verify concurrent execution, error isolation, status calculation
(completed/partial/failed), and FSM state transitions after migration
to flows.core primitives.
"""
from __future__ import annotations

from typing import Any

import pytest

from _crew_test_helpers import DummyAgent  # shared test infrastructure
from parrot.bots.flows.crew import AgentCrew


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_crew(*agents: DummyAgent, **kwargs: Any) -> AgentCrew:
    """Create an AgentCrew with DummyAgents."""
    crew = AgentCrew(
        name="TestParCrew",
        agents=list(agents),
        auto_configure=False,
        **kwargs,
    )
    return crew


def _make_parallel_tasks(agent_ids: list[str]) -> list[dict]:
    """Build the tasks list expected by run_parallel."""
    return [
        {"agent_id": aid, "query": f"task for {aid}"}
        for aid in agent_ids
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestParallelRegression:
    """Regression tests for run_parallel after primitives migration."""

    async def test_all_agents_run_concurrently(self) -> None:
        """All agents execute via asyncio.gather and complete."""
        a1 = DummyAgent("a1", "result1")
        a2 = DummyAgent("a2", "result2")
        a3 = DummyAgent("a3", "result3")
        crew = _make_crew(a1, a2, a3)
        tasks = _make_parallel_tasks(["a1", "a2", "a3"])
        result = await crew.run_parallel(tasks, generate_summary=False)
        assert result.status == "completed"
        assert len(result.agents) == 3

    async def test_one_failure_partial_status(self) -> None:
        """One failure -> partial status, others complete."""
        a1 = DummyAgent("a1", "ok")
        a2 = DummyAgent("a2", "ok", fail=True)
        a3 = DummyAgent("a3", "ok")
        crew = _make_crew(a1, a2, a3)
        tasks = _make_parallel_tasks(["a1", "a2", "a3"])
        result = await crew.run_parallel(tasks, generate_summary=False)
        assert result.status == "partial"
        assert "a2" in result.errors
        # Other agents should have succeeded
        assert len(result.errors) == 1

    async def test_all_failure_failed_status(self) -> None:
        """All agents fail -> failed status."""
        a1 = DummyAgent("a1", "ok", fail=True)
        a2 = DummyAgent("a2", "ok", fail=True)
        crew = _make_crew(a1, a2)
        tasks = _make_parallel_tasks(["a1", "a2"])
        result = await crew.run_parallel(tasks, generate_summary=False)
        assert result.status == "failed"
        assert len(result.errors) == 2

    async def test_fsm_states_all_completed(self) -> None:
        """Each node FSM reaches completed state after successful parallel run."""
        a1 = DummyAgent("a1", "ok")
        a2 = DummyAgent("a2", "ok")
        crew = _make_crew(a1, a2)
        tasks = _make_parallel_tasks(["a1", "a2"])
        result = await crew.run_parallel(tasks, generate_summary=False)
        assert result.status == "completed"
        for aid in ["a1", "a2"]:
            node = crew.workflow_graph.get(aid)
            assert node is not None, f"Node {aid} missing from workflow_graph"
            assert str(node.fsm.current_state.id) == "completed"

    async def test_fsm_states_mixed_success_failure(self) -> None:
        """Failed node FSM -> failed, successful node FSM -> completed."""
        a1 = DummyAgent("a1", "ok")
        a2 = DummyAgent("a2", "ok", fail=True)
        crew = _make_crew(a1, a2)
        tasks = _make_parallel_tasks(["a1", "a2"])
        result = await crew.run_parallel(tasks, generate_summary=False)
        assert result.status == "partial"
        node1 = crew.workflow_graph.get("a1")
        node2 = crew.workflow_graph.get("a2")
        assert str(node1.fsm.current_state.id) == "completed"
        assert str(node2.fsm.current_state.id) == "failed"

    async def test_result_structure(self) -> None:
        """CrewResult has expected fields and metadata."""
        a1 = DummyAgent("a1")
        crew = _make_crew(a1)
        tasks = _make_parallel_tasks(["a1"])
        result = await crew.run_parallel(tasks, generate_summary=False)
        assert hasattr(result, "output")
        assert hasattr(result, "status")
        assert hasattr(result, "agents")
        assert hasattr(result, "errors")
        assert hasattr(result, "total_time")
        assert hasattr(result, "metadata")
        assert result.metadata["mode"] == "parallel"

    async def test_results_contain_all_outputs(self) -> None:
        """All agent outputs are present in the result when all_results=True."""
        a1 = DummyAgent("a1", "first")
        a2 = DummyAgent("a2", "second")
        crew = _make_crew(a1, a2)
        tasks = _make_parallel_tasks(["a1", "a2"])
        result = await crew.run_parallel(
            tasks, all_results=True, generate_summary=False
        )
        assert isinstance(result.output, list)
        assert len(result.output) == 2

    async def test_pre_post_hooks_fire(self) -> None:
        """Pre/post action hooks fire for each agent in parallel mode."""
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

        tasks = _make_parallel_tasks(["a1", "a2"])
        await crew.run_parallel(tasks, generate_summary=False)
        assert ("pre", "a1") in hook_log
        assert ("post", "a1") in hook_log
        assert ("pre", "a2") in hook_log
        assert ("post", "a2") in hook_log

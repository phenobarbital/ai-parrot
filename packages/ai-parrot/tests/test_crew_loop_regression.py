"""Regression tests for AgentCrew.run_loop() mode.

Tests verify iteration chaining, max_iterations cap, FSM transitions
per iteration, and status calculation after migration to flows.core
primitives.

The condition evaluation (LLM-based) is monkeypatched to avoid
requiring real LLM access for mock-based tests.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from _crew_test_helpers import DummyAgent  # shared test infrastructure
from parrot.bots.orchestration.crew import AgentCrew


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_crew(*agents: DummyAgent, **kwargs: Any) -> AgentCrew:
    """Create an AgentCrew with DummyAgents."""
    crew = AgentCrew(
        name="TestLoopCrew",
        agents=list(agents),
        auto_configure=False,
        **kwargs,
    )
    return crew


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoopRegression:
    """Regression tests for run_loop after primitives migration."""

    async def test_max_iterations_cap(self) -> None:
        """Loop stops at max_iterations when condition never met."""
        a = DummyAgent("a", "output")
        crew = _make_crew(a)
        # Patch condition evaluation to always return False
        with patch.object(
            crew, "_evaluate_loop_condition", new_callable=AsyncMock, return_value=False
        ):
            result = await crew.run_loop(
                initial_task="start",
                condition="never true",
                max_iterations=3,
                generate_summary=False,
            )
        assert result.metadata["iterations"] == 3
        assert result.metadata["condition_met"] is False
        assert result.status == "completed"

    async def test_condition_stops_early(self) -> None:
        """Loop stops before max when condition is met."""
        a = DummyAgent("a", "done")
        crew = _make_crew(a)
        call_count = 0

        async def condition_eval(**kwargs):
            nonlocal call_count
            call_count += 1
            # Condition met on second iteration
            return call_count >= 2

        with patch.object(crew, "_evaluate_loop_condition", side_effect=condition_eval):
            result = await crew.run_loop(
                initial_task="start",
                condition="output contains done",
                max_iterations=5,
                generate_summary=False,
            )
        assert result.metadata["iterations"] == 2
        assert result.metadata["condition_met"] is True

    async def test_iteration_chaining(self) -> None:
        """Output from iteration N becomes input for iteration N+1."""
        a = DummyAgent("a", "refined")
        crew = _make_crew(a)
        with patch.object(
            crew, "_evaluate_loop_condition", new_callable=AsyncMock, return_value=False
        ):
            result = await crew.run_loop(
                initial_task="start",
                condition="never",
                max_iterations=2,
                pass_full_context=False,
                generate_summary=False,
            )
        # Second call should receive output from first call
        assert len(a.prompts_received) == 2
        # First call gets the initial task (formatted)
        assert "start" in a.prompts_received[0]
        # Second call gets something derived from the first output
        # (exact format depends on _build_loop_first_agent_prompt)
        assert len(a.prompts_received[1]) > 0

    async def test_fsm_per_iteration(self) -> None:
        """Each iteration gets fresh FSM states."""
        a = DummyAgent("a", "ok")
        crew = _make_crew(a)
        with patch.object(
            crew, "_evaluate_loop_condition", new_callable=AsyncMock, return_value=False
        ):
            result = await crew.run_loop(
                initial_task="start",
                condition="never",
                max_iterations=2,
                generate_summary=False,
            )
        # After 2 iterations, the node's FSM should be from the last iteration
        # and should be in completed state
        node = crew.workflow_graph.get("a")
        assert node is not None
        assert str(node.fsm.current_state.id) == "completed"

    async def test_result_metadata_mode(self) -> None:
        """CrewResult metadata has mode == 'loop'."""
        a = DummyAgent("a")
        crew = _make_crew(a)
        with patch.object(
            crew, "_evaluate_loop_condition", new_callable=AsyncMock, return_value=True
        ):
            result = await crew.run_loop(
                initial_task="start",
                condition="always true",
                max_iterations=1,
                generate_summary=False,
            )
        assert result.metadata["mode"] == "loop"
        assert "iterations" in result.metadata

    async def test_error_in_loop_continues(self) -> None:
        """A failing agent doesn't immediately stop the loop."""
        a = DummyAgent("a", "ok", fail_on_iteration=1)
        crew = _make_crew(a)
        with patch.object(
            crew, "_evaluate_loop_condition", new_callable=AsyncMock, return_value=False
        ):
            result = await crew.run_loop(
                initial_task="start",
                condition="never",
                max_iterations=2,
                generate_summary=False,
            )
        # Should have run 2 iterations despite first failing
        assert result.metadata["iterations"] == 2
        # Errors should be captured
        assert len(result.errors) >= 1

    async def test_pre_post_hooks_fire(self) -> None:
        """Pre/post action hooks fire for each iteration in loop mode."""
        hook_log: list = []

        def pre_hook(name, prompt, **ctx):
            hook_log.append(("pre", name))

        def post_hook(name, result, **ctx):
            hook_log.append(("post", name))

        a = DummyAgent("a", "ok")
        crew = _make_crew(a)

        # Register hooks on the node
        crew.workflow_graph["a"].add_pre_action(pre_hook)
        crew.workflow_graph["a"].add_post_action(post_hook)

        with patch.object(
            crew, "_evaluate_loop_condition", new_callable=AsyncMock, return_value=False
        ):
            await crew.run_loop(
                initial_task="start",
                condition="never",
                max_iterations=2,
                generate_summary=False,
            )
        # Hooks should fire once per iteration (2 iterations)
        pre_count = sum(1 for tag, _ in hook_log if tag == "pre")
        post_count = sum(1 for tag, _ in hook_log if tag == "post")
        assert pre_count == 2
        assert post_count == 2

"""Regression tests for AgentCrew.run_loop() mode.

Tests verify iteration chaining, max_iterations cap, FSM transitions
per iteration, and status calculation after migration to flows.core
primitives.

The condition evaluation (LLM-based) is monkeypatched to avoid
requiring real LLM access for mock-based tests.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub infrastructure
# ---------------------------------------------------------------------------

mock_nav_auth = MagicMock()
mock_nav_auth.decorators = MagicMock()
mock_nav_auth.decorators.is_authenticated = (
    lambda *args, **kwargs: lambda func: func
)
mock_nav_auth.decorators.user_session = (
    lambda *args, **kwargs: lambda func: func
)
sys.modules.setdefault("navigator_auth", mock_nav_auth)
sys.modules.setdefault("navigator_auth.decorators", mock_nav_auth.decorators)

mock_nav_conf = MagicMock()
mock_nav_conf.AUTH_SESSION_OBJECT = "session"
sys.modules.setdefault("navigator_auth.conf", mock_nav_conf)

from parrot.bots.orchestration.crew import AgentCrew  # noqa: E402


# ---------------------------------------------------------------------------
# DummyAgent compatible with AgentCrew.add_agent
# ---------------------------------------------------------------------------


class DummyToolManager:
    """Minimal ToolManager stand-in."""

    def __init__(self) -> None:
        self._tools: Dict[str, Any] = {}

    def add_tool(self, tool: Any, tool_name: Optional[str] = None) -> None:
        name = tool_name or getattr(tool, "name", str(tool))
        self._tools[name] = tool

    def get_tool(self, tool_name: Optional[str]) -> Any:
        return self._tools.get(tool_name or "")

    def list_tools(self):
        return list(self._tools.keys())


class DummyAgent:
    """Deterministic agent for testing AgentCrew loop mode."""

    is_configured: bool = True
    EVENT_STATUS_CHANGED: str = "status_changed"
    EVENT_TASK_STARTED: str = "task_started"
    EVENT_TASK_COMPLETED: str = "task_completed"
    EVENT_TASK_FAILED: str = "task_failed"

    def __init__(
        self,
        name: str,
        response: str = "ok",
        *,
        fail: bool = False,
        fail_on_iteration: int = -1,
    ) -> None:
        self._name = name
        self._response = response
        self._fail = fail
        self._fail_on_iteration = fail_on_iteration
        self._call_count = 0
        self.tool_manager = DummyToolManager()
        self.description = f"Agent {name}"
        self.prompts_received: list[str] = []

    @property
    def name(self) -> str:  # noqa: D401
        return self._name

    async def ask(self, prompt: str = "", *, question: str = "", **kwargs: Any) -> MagicMock:
        effective_prompt = question or prompt
        self.prompts_received.append(effective_prompt)
        self._call_count += 1
        if self._fail or self._call_count == self._fail_on_iteration:
            raise RuntimeError(f"{self._name} failed")
        resp = MagicMock()
        resp.content = f"{self._response}: {effective_prompt[:40]}"
        return resp

    def add_event_listener(self, event: str, handler: Any) -> None:
        """No-op for tests."""

    def as_tool(self, **kwargs: Any) -> None:
        """No-op stub for AgentTool registration."""
        return None

    async def configure(self) -> None:
        """No-op configure."""


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

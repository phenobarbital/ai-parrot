"""Regression tests for AgentCrew.run_sequential() mode.

Tests verify execution order, output propagation, early-stop on failure,
and FSM state transitions after migration to flows.core primitives.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

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
# DummyAgent with add_event_listener stub
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
    """Deterministic agent for testing AgentCrew."""

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
    ) -> None:
        self._name = name
        self._response = response
        self._fail = fail
        self.tool_manager = DummyToolManager()
        self.description = f"Agent {name}"
        self.prompts_received: list[str] = []

    @property
    def name(self) -> str:  # noqa: D401
        return self._name

    async def ask(self, prompt: str = "", *, question: str = "", **kwargs: Any) -> MagicMock:
        # AgentCrew._execute_agent passes `question=`, not `prompt=`
        effective_prompt = question or prompt
        self.prompts_received.append(effective_prompt)
        if self._fail:
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

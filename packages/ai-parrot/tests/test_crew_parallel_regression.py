"""Regression tests for AgentCrew.run_parallel() mode.

Tests verify concurrent execution, error isolation, status calculation
(completed/partial/failed), and FSM state transitions after migration
to flows.core primitives.
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
    """Deterministic agent for testing AgentCrew parallel mode."""

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
        delay: float = 0.0,
    ) -> None:
        self._name = name
        self._response = response
        self._fail = fail
        self._delay = delay
        self.tool_manager = DummyToolManager()
        self.description = f"Agent {name}"
        self.prompts_received: list[str] = []

    @property
    def name(self) -> str:  # noqa: D401
        return self._name

    async def ask(self, prompt: str = "", *, question: str = "", **kwargs: Any) -> MagicMock:
        effective_prompt = question or prompt
        self.prompts_received.append(effective_prompt)
        if self._delay:
            await asyncio.sleep(self._delay)
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

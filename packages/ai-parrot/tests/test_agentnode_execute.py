"""Unit tests for core AgentNode.execute() and _CrewAgentNode subclass.

Tests cover:
- execute() returns the expected dict with keys: response, output, execution_time, prompt
- execute() with timeout raises TimeoutError and transitions FSM to failed
- execute() fires pre/post action hooks in correct order
- _CrewAgentNode is a subclass of core AgentNode (isinstance check)
- _format_prompt produces the expected string format
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub infrastructure — mirrors test_agent_crew_examples.py
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

from parrot.bots.flows.core.node import AgentNode  # noqa: E402
from parrot.bots.orchestration.crew import _CrewAgentNode  # noqa: E402


# ---------------------------------------------------------------------------
# Mock agent
# ---------------------------------------------------------------------------


class MockAgent:
    """Deterministic agent returning configured responses."""

    def __init__(
        self,
        name: str = "test-agent",
        response_text: str = "test output",
    ) -> None:
        self._name = name
        self._response_text = response_text

    @property
    def name(self) -> str:  # noqa: D401
        return self._name

    async def ask(self, prompt: str = "", **kwargs: Any) -> MagicMock:
        """Return a mock response with ``.content``."""
        resp = MagicMock()
        resp.content = self._response_text
        return resp


class SlowAgent(MockAgent):
    """Agent that sleeps longer than any reasonable timeout."""

    async def ask(self, prompt: str = "", **kwargs: Any) -> MagicMock:
        await asyncio.sleep(100)
        return MagicMock(content="never")


# ---------------------------------------------------------------------------
# Tests for core AgentNode.execute()
# ---------------------------------------------------------------------------


class TestAgentNodeExecute:
    """Tests for the core AgentNode.execute() method."""

    async def test_execute_returns_result_dict(self) -> None:
        agent = MockAgent()
        node = AgentNode(agent=agent, node_id="test")
        result = await node.execute("hello")

        assert set(result.keys()) == {
            "response",
            "output",
            "execution_time",
            "prompt",
        }
        assert result["output"] == "test output"
        assert result["prompt"] == "hello"
        assert isinstance(result["execution_time"], float)
        assert result["execution_time"] >= 0

    async def test_execute_timeout_raises(self) -> None:
        agent = SlowAgent()
        node = AgentNode(agent=agent, node_id="test")
        with pytest.raises(TimeoutError, match="timed out"):
            await node.execute("hello", timeout=0.01)
        # FSM should be in failed state
        assert str(node.fsm.current_state.id) == "failed"

    async def test_execute_calls_pre_post_hooks(self) -> None:
        agent = MockAgent()
        node = AgentNode(agent=agent, node_id="test")
        calls: list = []
        node.add_pre_action(
            lambda name, prompt, **ctx: calls.append(("pre", name))
        )
        node.add_post_action(
            lambda name, result, **ctx: calls.append(("post", name))
        )
        await node.execute("hello")
        assert calls == [("pre", "test-agent"), ("post", "test-agent")]

    async def test_execute_generic_exception_transitions_fsm(self) -> None:
        agent = MockAgent()
        agent.ask = MagicMock(side_effect=RuntimeError("boom"))
        node = AgentNode(agent=agent, node_id="test")
        with pytest.raises(RuntimeError, match="boom"):
            await node.execute("hello")
        assert str(node.fsm.current_state.id) == "failed"

    async def test_execute_output_from_content_attr(self) -> None:
        agent = MockAgent(response_text="content-value")
        node = AgentNode(agent=agent, node_id="test")
        result = await node.execute("hello")
        assert result["output"] == "content-value"

    async def test_execute_output_fallback_to_str(self) -> None:
        """When response has no .content, falls back to str()."""
        agent = MockAgent()

        async def ask_no_content(prompt="", **kwargs):
            return "plain-string-response"

        agent.ask = ask_no_content
        node = AgentNode(agent=agent, node_id="test")
        result = await node.execute("hello")
        assert result["output"] == "plain-string-response"


# ---------------------------------------------------------------------------
# Tests for _CrewAgentNode subclass
# ---------------------------------------------------------------------------


class TestCrewAgentNodeSubclass:
    """Tests for _CrewAgentNode as a subclass of core AgentNode."""

    def test_isinstance_agentnode(self) -> None:
        agent = MockAgent()
        node = _CrewAgentNode(agent=agent, node_id="test")
        assert isinstance(node, AgentNode)

    def test_format_prompt_task_only(self) -> None:
        agent = MockAgent()
        node = _CrewAgentNode(agent=agent, node_id="test")
        result = node._format_prompt({"task": "Analyze data"})
        assert result == "Analyze data"

    def test_format_prompt_empty_input(self) -> None:
        agent = MockAgent()
        node = _CrewAgentNode(agent=agent, node_id="test")
        assert node._format_prompt({}) == ""

    def test_format_prompt_with_dependencies(self) -> None:
        agent = MockAgent()
        node = _CrewAgentNode(agent=agent, node_id="test")
        input_data = {
            "task": "Analyze data",
            "dependencies": {
                "agent-a": "Result A",
                "agent-b": "Result B",
            },
        }
        result = node._format_prompt(input_data)
        # Verify the format is byte-identical to old implementation
        expected = (
            "Task: Analyze data\n"
            "\n"
            "\nContext from previous agents:\n"
            "\n"
            "\n--- From agent-a ---\n"
            "Result A\n"
            "\n"
            "\n--- From agent-b ---\n"
            "Result B\n"
        )
        assert result == expected

    async def test_execute_inherited_from_core(self) -> None:
        """_CrewAgentNode.execute() is inherited from core AgentNode."""
        agent = MockAgent()
        node = _CrewAgentNode(agent=agent, node_id="test")
        result = await node.execute("hello")
        assert result["output"] == "test output"
        assert result["prompt"] == "hello"

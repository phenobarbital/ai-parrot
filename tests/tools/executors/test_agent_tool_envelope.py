"""Tests for remote dispatch of Agents-as-Tools (AgentTool).

The wrapped agent is a live object that cannot cross the process
boundary; ``build_envelope_from_tool`` ships its registry name as an
``agent_ref`` init kwarg instead, and the worker-side runner
reconstructs the agent via ``parrot.registry.agent_registry``. Both
directions are exercised here with the registry mocked.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from parrot.tools.executors.abstract import (
    AbstractToolExecutor,
    ToolExecutionEnvelope,
    build_envelope_from_tool,
)
from parrot.tools.abstract import ToolResult


class _DummyAgent:
    """Minimal stand-in for an AbstractBot the AgentTool can drive."""

    name = "dummy_agent"
    description = "A dummy agent for tests"

    async def conversation(self, question: str, **kwargs) -> str:
        return f"answered:{question}"


def _agent_tool():
    from parrot.tools.agent import AgentTool

    return AgentTool(
        agent=_DummyAgent(),
        tool_name="dummy_agent_tool",
        tool_description="Ask the dummy agent",
    )


@pytest.fixture
def registered_agent(monkeypatch):
    """Pretend ``dummy_agent`` is registered in the agent registry."""
    from parrot.registry import agent_registry

    monkeypatch.setattr(
        agent_registry,
        "get_metadata",
        lambda name: object() if name == "dummy_agent" else None,
    )
    monkeypatch.setattr(
        agent_registry,
        "get_instance",
        AsyncMock(return_value=_DummyAgent()),
    )
    return agent_registry


def test_envelope_ships_agent_ref_not_live_agent(registered_agent):
    tool = _agent_tool()
    envelope = build_envelope_from_tool(tool, arguments={"question": "hi"})

    assert envelope.tool_import_path == "parrot.tools.agent:AgentTool"
    assert envelope.method_name is None
    assert envelope.tool_init_kwargs == {
        "agent_ref": "dummy_agent",
        "tool_name": "dummy_agent_tool",
        "tool_description": "Ask the dummy agent",
        "use_conversation_method": True,
    }
    # Nothing non-serializable leaks into the envelope.
    envelope.model_dump_json()


def test_unregistered_agent_raises_loudly(monkeypatch):
    from parrot.registry import agent_registry

    monkeypatch.setattr(agent_registry, "get_metadata", lambda name: None)
    tool = _agent_tool()
    with pytest.raises(ValueError, match="agent registry"):
        build_envelope_from_tool(tool, arguments={"question": "hi"})


@pytest.mark.asyncio
async def test_runner_reconstructs_agent_from_registry(registered_agent):
    from parrot.tools.executors.runner import run_envelope_inprocess

    envelope = ToolExecutionEnvelope(
        tool_import_path="parrot.tools.agent:AgentTool",
        tool_init_kwargs={
            "agent_ref": "dummy_agent",
            "tool_name": "dummy_agent_tool",
            "tool_description": "Ask the dummy agent",
            "use_conversation_method": True,
        },
        arguments={"question": "what is 6x7"},
    )
    result = await run_envelope_inprocess(envelope)

    assert result == "answered:what is 6x7"
    registered_agent.get_instance.assert_awaited_once_with("dummy_agent")


@pytest.mark.asyncio
async def test_runner_rejects_unknown_agent_ref(monkeypatch):
    from parrot.registry import agent_registry
    from parrot.tools.executors.runner import run_envelope_inprocess

    monkeypatch.setattr(
        agent_registry, "get_instance", AsyncMock(return_value=None)
    )
    envelope = ToolExecutionEnvelope(
        tool_import_path="parrot.tools.agent:AgentTool",
        tool_init_kwargs={"agent_ref": "ghost_agent"},
        arguments={"question": "hi"},
    )
    with pytest.raises(ValueError, match="ghost_agent"):
        await run_envelope_inprocess(envelope)


@pytest.mark.asyncio
async def test_agent_tool_dispatches_through_executor(registered_agent):
    """End-to-end caller side: AgentTool(executor=X) hands the executor
    an agent_ref envelope instead of running the agent in-process."""

    class _Recording(AbstractToolExecutor):
        def __init__(self):
            self.envelopes = []

        async def execute(self, envelope):
            self.envelopes.append(envelope)
            return ToolResult(status="success", result="remote-answer")

        async def close(self):
            return None

    ex = _Recording()
    tool = _agent_tool()
    tool.executor = ex

    result = await tool.execute(question="hello")
    assert result.result == "remote-answer"
    assert len(ex.envelopes) == 1
    assert ex.envelopes[0].tool_init_kwargs["agent_ref"] == "dummy_agent"

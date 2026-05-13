"""Shared fixtures for the AI-Parrot CLI agent REPL tests (FEAT-168).

These fixtures provide lightweight mocks for AbstractBot and AIMessage
so tests can run without a running server, LLM API keys, or database.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.models.outputs import OutputMode


# ---------------------------------------------------------------------------
# Helpers — build a minimal AIMessage-like mock
# ---------------------------------------------------------------------------


def _make_ai_message(output: str = "Test response") -> MagicMock:
    """Build a MagicMock that looks like an AIMessage.

    Args:
        output: The text output for the mock response.

    Returns:
        MagicMock with AIMessage-compatible attributes.
    """
    msg = MagicMock()
    msg.input = "test query"
    msg.output = output
    msg.response = output
    msg.data = None
    msg.tool_calls = []
    msg.usage = MagicMock()
    msg.usage.prompt_tokens = 10
    msg.usage.completion_tokens = 20
    msg.usage.total_tokens = 30
    msg.usage.total_time = None
    msg.usage.estimated_cost = None
    msg.model = "test-model"
    msg.provider = "test-provider"
    msg.output_mode = OutputMode.TERMINAL
    msg.metadata = {}
    msg.created_at = datetime.now()
    msg.response_time = 0.5
    return msg


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_agent():
    """A minimal AsyncMock bot for REPL testing.

    Returns:
        AsyncMock with AbstractBot-compatible interface.
    """
    agent = AsyncMock()
    agent.name = "test_agent"
    # These are synchronous methods on AbstractBot — use MagicMock, not AsyncMock
    agent.get_available_tools = MagicMock(return_value=["MathTool", "WebSearch"])
    agent.get_tools_count = MagicMock(return_value=2)
    agent.has_tools = MagicMock(return_value=True)
    agent.configure = AsyncMock(return_value=None)
    agent.ask = AsyncMock(return_value=_make_ai_message("Test response"))
    agent.ask_stream = MagicMock(side_effect=lambda **kw: _async_gen_response("Test streaming response"))
    return agent


async def _async_gen_response(text: str):
    """Async generator that yields text chunks for streaming tests.

    Args:
        text: Full text to yield in chunks.

    Yields:
        Text chunks.
    """
    chunk_size = 10
    for i in range(0, len(text), chunk_size):
        yield text[i : i + chunk_size]


@pytest.fixture
def repl_config():
    """A minimal REPLConfig for testing (streaming disabled).

    Returns:
        REPLConfig instance with test defaults.
    """
    from parrot.cli.repl import REPLConfig
    return REPLConfig(
        agent_name="test_agent",
        streaming=False,
        session_id="test-session-123",
        user_id="test-user",
    )


@pytest.fixture
def renderer():
    """A ResponseRenderer with a no-op console for testing.

    Yields:
        ResponseRenderer with a file=open(devnull) console to suppress output.
    """
    import os
    from rich.console import Console
    from parrot.cli.renderer import ResponseRenderer
    r = ResponseRenderer()
    fh = open(os.devnull, "w")  # noqa: SIM115
    r.console = Console(file=fh)
    yield r
    fh.close()


@pytest.fixture
def mock_agent_response():
    """A mock AIMessage with markdown content.

    Returns:
        MagicMock AIMessage with markdown output.
    """
    return _make_ai_message("# Hello\n\nThis is **markdown** content.")


@pytest.fixture
def response_with_tools():
    """A mock AIMessage with tool calls.

    Returns:
        MagicMock AIMessage with one tool call.
    """
    msg = _make_ai_message("Used a tool.")
    tool = MagicMock()
    tool.name = "MathTool"
    tool.arguments = {"expression": "2 + 2"}
    tool.result = "4"
    tool.error = None
    msg.tool_calls = [tool]
    return msg

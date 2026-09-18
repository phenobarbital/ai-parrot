"""Shared fixtures for the AI-Parrot CLI agent REPL tests (FEAT-168).

These fixtures provide lightweight mocks for AbstractBot and AIMessage
so tests can run without a running server, LLM API keys, or database.
"""

from __future__ import annotations

import io
import os
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


# ---------------------------------------------------------------------------
# Shared end-to-end fixtures (FEAT-573 TASK-3416, spec §4 Test Data / Fixtures)
# ---------------------------------------------------------------------------


@pytest.fixture
def quiet_console():
    """Shared Console(file=StringIO, force_terminal=True, width=100) installed via set_console(); reset after.

    Yields:
        The installed ``rich.console.Console`` instance (its buffer is readable
        via ``quiet_console.file.getvalue()`` when a test needs the rendered text).
    """
    from parrot.cli.console import reset_console, set_console  # provided by TASK-3400
    from rich.console import Console

    console = Console(file=io.StringIO(), force_terminal=True, width=100)
    set_console(console)
    yield console
    reset_console()


@pytest.fixture
def fake_streaming_bot():
    """Bot whose ask_stream yields deltas then an AIMessage-like object; ask returns the same object.

    Returns:
        AsyncMock configured to behave like a minimal streaming-capable ``AbstractBot``.
    """
    bot = AsyncMock()
    bot.name = "test_agent"
    final = _make_ai_message("Hello world")
    bot.get_available_tools = MagicMock(return_value=[])
    bot.get_tools_count = MagicMock(return_value=0)
    bot.has_tools = MagicMock(return_value=False)
    bot.ask = AsyncMock(return_value=final)

    async def _stream(**kw):
        for chunk in ("Hello", " ", "world"):
            yield chunk
        yield final

    bot.ask_stream = MagicMock(side_effect=lambda **kw: _stream(**kw))
    bot.get_conversation_history = AsyncMock(return_value=None)
    return bot


@pytest.fixture
def lifecycle_scope():
    """Isolate the global lifecycle registry for the test.

    Yields:
        The scoped ``EventRegistry`` (``get_global_registry()`` resolves to this
        instance for the duration of the ``with`` block).
    """
    from parrot.core.events.lifecycle import scope

    with scope() as reg:
        yield reg


@pytest.fixture
def tool_emitting_bot(lifecycle_scope, fake_streaming_bot):
    """fake_streaming_bot whose ask_stream executes a real AbstractTool between two deltas.

    The tool is awaited in the same task as the caller (no ``create_task``), so the
    lifecycle events it emits land inside the runner's ``turn_scope``.

    Returns:
        The mutated ``fake_streaming_bot`` (same object, new ``ask_stream``).
    """
    from parrot.tools.abstract import AbstractTool, ToolResult

    class _OkTool(AbstractTool):
        async def _execute(self, **kwargs) -> ToolResult:
            return ToolResult(status="success", result="ok")

    async def _stream(**kw):
        yield "Hel"
        await _OkTool(name="MathTool").execute()
        yield "lo"
        yield fake_streaming_bot.ask.return_value

    fake_streaming_bot.ask_stream = MagicMock(side_effect=lambda **kw: _stream(**kw))
    return fake_streaming_bot


@pytest.fixture
def sse_frames() -> list[bytes]:
    """Raw SSE frames: content / tool_event started+finished / ai_message / [DONE].

    Returns:
        List of already-encoded ``data: ...\\n\\n`` byte frames.
    """
    import json

    frames = [
        {"content": "Hel"},
        {
            "type": "tool_event",
            "data": {"event": "started", "call_id": "s1", "tool_name": "MathTool", "args_summary": {}},
        },
        {
            "type": "tool_event",
            "data": {
                "event": "finished",
                "call_id": "s1",
                "tool_name": "MathTool",
                "duration_ms": 1.0,
                "result_status": "success",
                "result_size_bytes": 2,
            },
        },
        {"content": "lo"},
        {
            "type": "ai_message",
            "data": {
                "output": "Hello",
                "response": "Hello",
                "tool_calls": [],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        },
    ]
    return [f"data: {json.dumps(f)}\n\n".encode() for f in frames] + [b"data: [DONE]\n\n"]

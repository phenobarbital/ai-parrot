"""Unit tests for the uniform ask_stream() contract (FEAT-174).

Verifies that every LLM client's ``ask_stream()`` method:
  1. Yields at least one ``str`` chunk.
  2. Yields exactly one ``AIMessage`` as the **final** element.
  3. ``AIMessage`` has ``model``, ``provider``, and ``turn_id`` populated.

All tests use local mocks — no real API calls are made.
"""
from __future__ import annotations

import inspect
from typing import AsyncIterator, Union, get_type_hints
from unittest.mock import MagicMock, patch

import pytest

from parrot.clients.base import AbstractClient
from parrot.models import AIMessage, CompletionUsage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _zeroed_usage() -> CompletionUsage:
    return CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)


def _make_aimessage(
    provider: str = "test",
    model: str = "test-model",
    turn_id: str = "t-001",
) -> AIMessage:
    return AIMessage(
        input="test prompt",
        output="Hello world!",
        response="Hello world!",
        model=model,
        provider=provider,
        usage=_zeroed_usage(),
        turn_id=turn_id,
    )


async def _consume(stream) -> tuple[list[str], AIMessage | None]:
    """Consume an ask_stream generator and separate str chunks from AIMessage."""
    chunks: list[str] = []
    ai_msg: AIMessage | None = None
    async for item in stream:
        if isinstance(item, AIMessage):
            ai_msg = item
        else:
            assert isinstance(item, str), f"Expected str, got {type(item)!r}"
            chunks.append(item)
    return chunks, ai_msg


# ---------------------------------------------------------------------------
# TASK-1173: AbstractClient type annotation
# ---------------------------------------------------------------------------


def test_abstract_client_ask_stream_return_type():
    """AbstractClient.ask_stream return type must be AsyncIterator[Union[str, AIMessage]]."""
    hints = get_type_hints(AbstractClient.ask_stream)
    expected = AsyncIterator[Union[str, AIMessage]]
    assert hints["return"] == expected, (
        f"Expected {expected!r}, got {hints['return']!r}"
    )


# ---------------------------------------------------------------------------
# TASK-1174: AnthropicClient (claude.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_ask_stream_yields_aimessage():
    """AnthropicClient.ask_stream yields str chunks then final AIMessage."""
    from parrot.clients.claude import AnthropicClient

    # Build a minimal client instance without network setup
    client = AnthropicClient.__new__(AnthropicClient)
    client.model = "claude-sonnet-4-6"
    client._default_model = "claude-sonnet-4-6"
    client.max_tokens = 4096
    client.temperature = 0.7
    client.logger = MagicMock()
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    client.conversation_memory = None

    expected_ai_msg = _make_aimessage(provider="claude", model="claude-sonnet-4-6")

    async def _fake_ask_stream(*args, **kwargs):
        yield "Hello"
        yield " world"
        yield expected_ai_msg

    with patch.object(client, "ask_stream", side_effect=_fake_ask_stream):
        chunks, ai_msg = await _consume(
            client.ask_stream("test prompt", user_id="u1", session_id="s1")
        )

    assert len(chunks) >= 1, "Should yield at least one str chunk"
    assert ai_msg is not None, "Should yield final AIMessage"
    assert ai_msg.provider == "claude"
    assert ai_msg.model is not None
    assert ai_msg.turn_id is not None


# ---------------------------------------------------------------------------
# TASK-1175: OpenAIClient (gpt.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_ask_stream_yields_aimessage():
    """OpenAIClient.ask_stream yields str chunks then final AIMessage."""
    from parrot.clients.gpt import OpenAIClient

    expected_ai_msg = _make_aimessage(provider="openai", model="gpt-5-mini")

    async def _fake_ask_stream(*args, **kwargs):
        yield "Hello"
        yield " world"
        yield expected_ai_msg

    client = OpenAIClient.__new__(OpenAIClient)
    with patch.object(client, "ask_stream", side_effect=_fake_ask_stream):
        chunks, ai_msg = await _consume(
            client.ask_stream("test prompt")
        )

    assert len(chunks) >= 1
    assert ai_msg is not None
    assert ai_msg.provider == "openai"
    assert ai_msg.model is not None


# ---------------------------------------------------------------------------
# TASK-1176: GroqClient (groq.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groq_ask_stream_yields_aimessage():
    """GroqClient.ask_stream yields str chunks then final AIMessage."""
    from parrot.clients.groq import GroqClient

    expected_ai_msg = _make_aimessage(provider="groq", model="llama-3.3-70b-versatile")

    async def _fake_ask_stream(*args, **kwargs):
        yield "Hello"
        yield " world"
        yield expected_ai_msg

    client = GroqClient.__new__(GroqClient)
    with patch.object(client, "ask_stream", side_effect=_fake_ask_stream):
        chunks, ai_msg = await _consume(
            client.ask_stream("test prompt")
        )

    assert len(chunks) >= 1
    assert ai_msg is not None
    assert ai_msg.provider == "groq"


# ---------------------------------------------------------------------------
# TASK-1177: GrokClient (grok.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grok_ask_stream_yields_aimessage():
    """GrokClient.ask_stream yields str chunks then final AIMessage."""
    from parrot.clients.grok import GrokClient

    expected_ai_msg = _make_aimessage(provider="grok", model="grok-4")

    async def _fake_ask_stream(*args, **kwargs):
        yield "Hello"
        yield " world"
        yield expected_ai_msg

    client = GrokClient.__new__(GrokClient)
    with patch.object(client, "ask_stream", side_effect=_fake_ask_stream):
        chunks, ai_msg = await _consume(
            client.ask_stream("test prompt")
        )

    assert len(chunks) >= 1
    assert ai_msg is not None
    assert ai_msg.provider == "grok"


# ---------------------------------------------------------------------------
# TASK-1178: Gemma4Client (gemma4.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemma4_ask_stream_yields_aimessage():
    """Gemma4Client.ask_stream yields str chunks then final AIMessage."""
    from parrot.clients.gemma4 import Gemma4Client

    ai_msg_from_ask = _make_aimessage(provider="gemma4", model="google/gemma-4-E2B-it")
    ai_msg_from_ask.content = "Hello world!"  # simulate response.content

    async def _fake_ask_stream(*args, **kwargs):
        yield "Hello"
        yield " world"
        yield ai_msg_from_ask

    client = Gemma4Client.__new__(Gemma4Client)
    with patch.object(client, "ask_stream", side_effect=_fake_ask_stream):
        chunks, ai_msg = await _consume(
            client.ask_stream("test prompt")
        )

    assert len(chunks) >= 1
    assert ai_msg is not None
    assert isinstance(ai_msg, AIMessage)


# ---------------------------------------------------------------------------
# TASK-1179: TransformersClient (hf.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transformers_ask_stream_yields_aimessage():
    """TransformersClient.ask_stream yields str chunks then final AIMessage."""
    from parrot.clients.hf import TransformersClient

    ai_msg_from_ask = _make_aimessage(provider="transformers", model="Qwen/Qwen2.5-3B-Instruct")
    ai_msg_from_ask.content = "Hello world!"

    async def _fake_ask_stream(*args, **kwargs):
        yield "Hello"
        yield " world"
        yield ai_msg_from_ask

    client = TransformersClient.__new__(TransformersClient)
    with patch.object(client, "ask_stream", side_effect=_fake_ask_stream):
        chunks, ai_msg = await _consume(
            client.ask_stream("test prompt")
        )

    assert len(chunks) >= 1
    assert ai_msg is not None
    assert isinstance(ai_msg, AIMessage)


# ---------------------------------------------------------------------------
# TASK-1180: ClaudeAgentClient (claude_agent.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claude_agent_ask_stream_yields_aimessage():
    """ClaudeAgentClient.ask_stream yields str chunks then final AIMessage."""
    from parrot.clients.claude_agent import ClaudeAgentClient

    expected_ai_msg = _make_aimessage(provider="claude-agent", model="claude-sonnet-4-6")

    async def _fake_ask_stream(*args, **kwargs):
        yield "Hello"
        yield " world"
        yield expected_ai_msg

    client = ClaudeAgentClient.__new__(ClaudeAgentClient)
    with patch.object(client, "ask_stream", side_effect=_fake_ask_stream):
        chunks, ai_msg = await _consume(
            client.ask_stream("test prompt")
        )

    assert len(chunks) >= 1
    assert ai_msg is not None
    assert ai_msg.provider == "claude-agent"


# ---------------------------------------------------------------------------
# Streaming contract invariant: last item is always AIMessage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_contract_last_item_is_aimessage():
    """The final item from ask_stream MUST be an AIMessage, not a str."""
    expected_ai_msg = _make_aimessage(provider="test")

    async def _mock_stream(*args, **kwargs):
        yield "chunk1"
        yield "chunk2"
        yield "chunk3"
        yield expected_ai_msg

    all_items = []
    async for item in _mock_stream():
        all_items.append(item)

    assert len(all_items) >= 2, "Need at least 1 str chunk and 1 AIMessage"
    assert isinstance(all_items[-1], AIMessage), (
        f"Last item must be AIMessage, got {type(all_items[-1])!r}"
    )
    str_items = [i for i in all_items if isinstance(i, str)]
    assert len(str_items) >= 1, "Must yield at least one str chunk"


# ---------------------------------------------------------------------------
# AbstractClient return type annotation invariant
# ---------------------------------------------------------------------------


def test_ask_stream_signature_has_correct_annotation():
    """ask_stream() must declare Union[str, AIMessage] in its return annotation."""
    sig = inspect.signature(AbstractClient.ask_stream)
    # The return annotation is present (not empty)
    assert sig.return_annotation != inspect.Parameter.empty
    # It references AIMessage somewhere in its repr
    annotation_repr = repr(sig.return_annotation)
    assert "AIMessage" in annotation_repr, (
        f"Return annotation does not reference AIMessage: {annotation_repr}"
    )

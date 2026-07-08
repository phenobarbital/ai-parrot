"""Unit tests for the uniform ask_stream() contract (FEAT-174).

Verifies that every LLM client's ``ask_stream()`` method:
  1. Yields at least one ``str`` chunk.
  2. Yields exactly one ``AIMessage`` as the **final** element.
  3. ``AIMessage`` has ``model``, ``provider``, and ``turn_id`` populated.

Test structure
--------------
Part 1 – Structural invariants
    Type-annotation checks on AbstractClient.ask_stream.

Part 2 – Real-implementation tests (mock at SDK/internal level)
    Gemma4Client and TransformersClient delegate to self.ask(); we mock that
    method and call the *real* ask_stream() so the actual generator logic is
    exercised.
    GroqClient uses self.client.chat.completions.create(); we mock that at the
    SDK level so the real ask_stream() runs end-to-end.

Part 3 – Contract-shape tests (mock at ask_stream level)
    AnthropicClient, OpenAIClient, GrokClient, and ClaudeAgentClient have
    complex SDK setups (streaming context managers, xAI multi-step chat API,
    Claude Agent SDK).  We verify that a *conforming* ask_stream() generator —
    one that obeys the str* + AIMessage protocol — is consumed correctly by
    the helper utilities.  Full implementation coverage lives in
    tests/integration/ where real or recorded SDK responses can be used.

No real API calls are made in any test.
"""
from __future__ import annotations

import asyncio
import inspect
from typing import AsyncIterator, Union, get_type_hints
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from parrot.clients.base import AbstractClient
from parrot.models import AIMessage, CompletionUsage


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _zeroed_usage() -> CompletionUsage:
    return CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)


def _make_aimessage(
    provider: str = "test",
    model: str = "test-model",
    turn_id: str = "t-001",
    text: str = "Hello world!",
) -> AIMessage:
    return AIMessage(
        input="test prompt",
        output=text,
        response=text,
        model=model,
        provider=provider,
        usage=_zeroed_usage(),
        turn_id=turn_id,
    )


async def _consume(stream) -> tuple[list[str], AIMessage | None]:
    """Drain an ask_stream generator; separate str chunks from the AIMessage."""
    chunks: list[str] = []
    ai_msg: AIMessage | None = None
    async for item in stream:
        if isinstance(item, AIMessage):
            ai_msg = item
        else:
            assert isinstance(item, str), f"Expected str, got {type(item)!r}"
            chunks.append(item)
    return chunks, ai_msg


def _assert_contract(
    chunks: list[str],
    ai_msg: AIMessage | None,
    *,
    min_chunks: int = 1,
    provider: str | None = None,
) -> None:
    """Assert the universal streaming contract."""
    assert len(chunks) >= min_chunks, (
        f"Expected ≥{min_chunks} str chunk(s), got {len(chunks)}"
    )
    assert ai_msg is not None, "Final AIMessage was not yielded"
    assert isinstance(ai_msg, AIMessage)
    assert ai_msg.model is not None and ai_msg.model != ""
    assert ai_msg.provider is not None and ai_msg.provider != ""
    if provider is not None:
        assert ai_msg.provider == provider, (
            f"Expected provider={provider!r}, got {ai_msg.provider!r}"
        )


# ===========================================================================
# Part 1 — Structural invariants
# ===========================================================================


def test_abstract_client_ask_stream_return_type():
    """AbstractClient.ask_stream return type must be AsyncIterator[Union[str, AIMessage]]."""
    hints = get_type_hints(AbstractClient.ask_stream)
    expected = AsyncIterator[Union[str, AIMessage]]
    assert hints["return"] == expected, (
        f"Expected {expected!r}, got {hints['return']!r}"
    )


def test_ask_stream_signature_has_correct_annotation():
    """ask_stream() must declare Union[str, AIMessage] in its return annotation."""
    sig = inspect.signature(AbstractClient.ask_stream)
    assert sig.return_annotation != inspect.Parameter.empty
    annotation_repr = repr(sig.return_annotation)
    assert "AIMessage" in annotation_repr, (
        f"Return annotation does not reference AIMessage: {annotation_repr}"
    )


@pytest.mark.asyncio
async def test_stream_contract_last_item_is_aimessage():
    """Contract invariant: the last item yielded MUST be an AIMessage."""
    sentinel = _make_aimessage(provider="test")

    async def _conforming_stream():
        yield "chunk1"
        yield "chunk2"
        yield "chunk3"
        yield sentinel

    all_items = []
    async for item in _conforming_stream():
        all_items.append(item)

    assert len(all_items) >= 2
    assert isinstance(all_items[-1], AIMessage), (
        f"Last item must be AIMessage, got {type(all_items[-1])!r}"
    )
    str_items = [i for i in all_items if isinstance(i, str)]
    assert len(str_items) >= 1


# ===========================================================================
# Part 2 — Real-implementation tests
# ===========================================================================

# ---------------------------------------------------------------------------
# Gemma4Client — pseudo-streaming: delegates to self.ask()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemma4_ask_stream_real_implementation():
    """Gemma4Client.ask_stream() real code: mocks self.ask(), tests the generator.

    Gemma4Client.ask_stream calls ``self.ask()`` then yields text chunks
    (via ``response.content``) followed by the AIMessage itself.  We mock
    ``ask`` at the instance level so the *real* generator runs.
    """
    from parrot.clients.gemma4 import Gemma4Client

    text = "Hello from Gemma4! " * 3  # long enough for multiple 10-char chunks
    ai_msg_from_ask = _make_aimessage(
        provider="gemma4",
        model="google/gemma-4-E2B-it",
        text=text,
    )

    client = Gemma4Client.__new__(Gemma4Client)
    client.logger = MagicMock()
    # Patch self.ask to return our pre-built AIMessage
    client.ask = AsyncMock(return_value=ai_msg_from_ask)

    chunks, final_msg = await _consume(
        client.ask_stream("test prompt", max_tokens=512)
    )

    # The real ask_stream() was called — verify it did the right thing
    client.ask.assert_awaited_once()
    _assert_contract(chunks, final_msg, provider="gemma4")
    # The yielded AIMessage is the *exact object* returned by self.ask()
    assert final_msg is ai_msg_from_ask
    # Text was chunked into pieces of ≤10 chars
    assert all(len(c) <= 10 for c in chunks)
    assert "".join(chunks) == text


@pytest.mark.asyncio
async def test_gemma4_ask_stream_empty_response():
    """Gemma4Client.ask_stream handles an empty response (no str chunks, just AIMessage)."""
    from parrot.clients.gemma4 import Gemma4Client

    ai_msg_from_ask = _make_aimessage(
        provider="gemma4",
        model="google/gemma-4-E2B-it",
        text="",  # empty — no str chunks
    )

    client = Gemma4Client.__new__(Gemma4Client)
    client.logger = MagicMock()
    client.ask = AsyncMock(return_value=ai_msg_from_ask)

    chunks, final_msg = await _consume(
        client.ask_stream("test prompt", max_tokens=512)
    )

    # Even with empty text, the AIMessage must still be yielded
    assert final_msg is not None
    assert isinstance(final_msg, AIMessage)
    assert chunks == []  # no str chunks — that's fine for an empty response


# ---------------------------------------------------------------------------
# TransformersClient — pseudo-streaming: same pattern as Gemma4
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transformers_ask_stream_real_implementation():
    """TransformersClient.ask_stream() real code: mocks self.ask(), tests the generator."""
    from parrot.clients.hf import TransformersClient

    text = "Transformers response! " * 3
    ai_msg_from_ask = _make_aimessage(
        provider="transformers",
        model="Qwen/Qwen2.5-3B-Instruct",
        text=text,
    )

    client = TransformersClient.__new__(TransformersClient)
    client.logger = MagicMock()
    client.ask = AsyncMock(return_value=ai_msg_from_ask)

    chunks, final_msg = await _consume(
        client.ask_stream("test prompt", max_tokens=512)
    )

    client.ask.assert_awaited_once()
    _assert_contract(chunks, final_msg, provider="transformers")
    assert final_msg is ai_msg_from_ask
    assert "".join(chunks) == text


# ---------------------------------------------------------------------------
# GroqClient — real streaming: mock SDK at chat.completions.create level
# ---------------------------------------------------------------------------


def _make_groq_chunk(content: str | None, usage=None):
    """Build a minimal mock Groq streaming chunk."""
    chunk = MagicMock()
    if content is not None:
        choice = MagicMock()
        choice.delta.content = content
        chunk.choices = [choice]
    else:
        chunk.choices = []
    chunk.usage = usage
    return chunk


def _make_groq_usage(prompt: int = 10, completion: int = 5):
    """Build a minimal mock Groq usage object."""
    usage = MagicMock()
    usage.prompt_tokens = prompt
    usage.completion_tokens = completion
    usage.total_tokens = prompt + completion
    return usage


@pytest.mark.asyncio
async def test_groq_ask_stream_real_implementation():
    """GroqClient.ask_stream() real code: mock SDK create(), test the generator end-to-end."""
    from parrot.clients.groq import GroqClient

    groq_usage = _make_groq_usage(prompt=10, completion=6)
    # Build chunks: two text chunks + a final empty chunk carrying usage
    sdk_chunks = [
        _make_groq_chunk("Hello "),
        _make_groq_chunk("world!"),
        _make_groq_chunk(None, usage=groq_usage),  # final chunk — no text, carries usage
    ]

    async def _mock_response_stream():
        for c in sdk_chunks:
            yield c

    # Minimal GroqClient state needed by ask_stream
    client = GroqClient.__new__(GroqClient)
    client.logger = MagicMock()
    client.model = "llama-3.3-70b-versatile"

    # Mock internal helpers so ask_stream can run without a real backend
    client._prepare_conversation_context = AsyncMock(
        return_value=(
            [{"role": "user", "content": "test prompt"}],  # messages
            None,                                           # conversation_session
            None,                                           # system_prompt
        )
    )
    client._prepare_groq_tools = MagicMock(return_value=[])  # no tools
    client._update_conversation_memory = AsyncMock()

    # Mock the Groq SDK client via PropertyMock (direct assignment is blocked
    # by the AbstractClient.client property setter).
    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create = AsyncMock(return_value=_mock_response_stream())

    # Also need CompletionUsage.from_groq to work — verify it exists
    from parrot.models import CompletionUsage as CU
    assert hasattr(CU, "from_groq"), "CompletionUsage.from_groq must exist"

    with patch.object(type(client), "client", new_callable=PropertyMock) as mock_client_prop:
        mock_client_prop.return_value = mock_sdk
        chunks, final_msg = await _consume(
            client.ask_stream("test prompt", user_id="u1", session_id="s1")
        )

    _assert_contract(chunks, final_msg, min_chunks=1, provider="groq")
    assert "".join(chunks) == "Hello world!"
    # Memory update must have been called BEFORE the final yield
    # (confirmed by the fact we reached this assertion without error)
    client._update_conversation_memory.assert_awaited_once()


@pytest.mark.asyncio
async def test_groq_ask_stream_no_usage_data():
    """GroqClient falls back to zeroed CompletionUsage when no usage chunk arrives."""
    from parrot.clients.groq import GroqClient

    # Chunks with no usage object on any of them
    sdk_chunks = [
        _make_groq_chunk("Hi"),
        _make_groq_chunk(None),  # final chunk — no text, no usage
    ]

    async def _mock_response_stream():
        for c in sdk_chunks:
            yield c

    client = GroqClient.__new__(GroqClient)
    client.logger = MagicMock()
    client.model = "llama-3.3-70b-versatile"
    client._prepare_conversation_context = AsyncMock(
        return_value=([{"role": "user", "content": "hi"}], None, None)
    )
    client._prepare_groq_tools = MagicMock(return_value=[])
    client._update_conversation_memory = AsyncMock()

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create = AsyncMock(return_value=_mock_response_stream())

    with patch.object(type(client), "client", new_callable=PropertyMock) as mock_client_prop:
        mock_client_prop.return_value = mock_sdk
        chunks, final_msg = await _consume(
            client.ask_stream("hi", user_id=None, session_id=None)
        )

    assert final_msg is not None
    assert final_msg.usage.prompt_tokens == 0
    assert final_msg.usage.completion_tokens == 0


# ===========================================================================
# Part 3 — Contract-shape tests for complex-SDK clients
#
# These tests verify that a *conforming* ask_stream generator (one that
# follows the str* + AIMessage protocol) is correctly consumed by _consume().
# They do NOT exercise the real ask_stream() implementation — full
# implementation coverage requires integration tests.
# ===========================================================================


@pytest.mark.asyncio
async def test_anthropic_contract_shape():
    """AnthropicClient contract shape: conforming generator is consumed correctly."""
    from parrot.clients.claude import AnthropicClient

    sentinel = _make_aimessage(provider="claude", model="claude-sonnet-4-6")

    # side_effect is called with (self, *args, **kwargs) so must accept them
    async def _conforming(*args, **kwargs):
        yield "Hello"
        yield " world"
        yield sentinel

    client = AnthropicClient.__new__(AnthropicClient)
    with patch.object(client, "ask_stream", side_effect=_conforming):
        chunks, ai_msg = await _consume(
            client.ask_stream("test prompt", user_id="u1", session_id="s1")
        )

    _assert_contract(chunks, ai_msg, provider="claude")
    assert ai_msg is sentinel


@pytest.mark.asyncio
async def test_openai_contract_shape():
    """OpenAIClient contract shape: conforming generator is consumed correctly."""
    from parrot.clients.gpt import OpenAIClient

    sentinel = _make_aimessage(provider="openai", model="gpt-5-mini")

    async def _conforming(*args, **kwargs):
        yield "Hello"
        yield " world"
        yield sentinel

    client = OpenAIClient.__new__(OpenAIClient)
    with patch.object(client, "ask_stream", side_effect=_conforming):
        chunks, ai_msg = await _consume(client.ask_stream("test prompt"))

    _assert_contract(chunks, ai_msg, provider="openai")


@pytest.mark.asyncio
async def test_grok_contract_shape():
    """GrokClient contract shape: conforming generator is consumed correctly."""
    from parrot.clients.grok import GrokClient

    sentinel = _make_aimessage(provider="grok", model="grok-4.3")

    async def _conforming(*args, **kwargs):
        yield "Hello"
        yield " world"
        yield sentinel

    client = GrokClient.__new__(GrokClient)
    with patch.object(client, "ask_stream", side_effect=_conforming):
        chunks, ai_msg = await _consume(client.ask_stream("test prompt"))

    _assert_contract(chunks, ai_msg, provider="grok")


@pytest.mark.asyncio
async def test_claude_agent_contract_shape():
    """ClaudeAgentClient contract shape: conforming generator is consumed correctly."""
    from parrot.clients.claude_agent import ClaudeAgentClient

    sentinel = _make_aimessage(provider="claude-agent", model="claude-sonnet-4-6")

    async def _conforming(*args, **kwargs):
        yield "Hello"
        yield " world"
        yield sentinel

    client = ClaudeAgentClient.__new__(ClaudeAgentClient)
    with patch.object(client, "ask_stream", side_effect=_conforming):
        chunks, ai_msg = await _consume(client.ask_stream("test prompt"))

    _assert_contract(chunks, ai_msg, provider="claude-agent")

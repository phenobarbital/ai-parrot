"""Unit tests for Gemini client per-round usage accumulation + the
first-response usage bug fix (FEAT-397).

Drives `_handle_multiturn_function_calls()` via a mocked `chat.send_message`
and asserts that AIMessage.usage carries the accumulated total across the
initial call AND every loop round (not just the initial response's usage —
the pre-existing bug), that ClientRoundEvent fires once per tool round, and
that AfterClientCallEvent carries the accumulated totals too.
"""

from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.clients.google import GoogleGenAIClient
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    ClientRoundEvent,
)


def _mock_usage_metadata(prompt: int, candidates: int, total: int):
    um = MagicMock()
    um.prompt_token_count = prompt
    um.candidates_token_count = candidates
    um.total_token_count = total
    return um


def _mock_function_call(name: str, args=None):
    fc = MagicMock()
    fc.name = name
    fc.args = args or {}
    fc.id = f"call_{name}"
    return fc


def _mock_part(function_call=None, text=None):
    part = MagicMock()
    part.function_call = function_call
    part.text = text
    part.executable_code = None
    part.code_execution_result = None
    part.thought = False
    return part


def _mock_response(*, function_call_name=None, text=None, usage=None):
    """Build a mock Gemini response.

    Args:
        function_call_name: If set, the response requests this tool.
        text: Final text answer (used when function_call_name is None).
        usage: (prompt_token_count, candidates_token_count, total_token_count)
            tuple, or None to simulate a round with no usage_metadata.
    """
    candidate = MagicMock()
    candidate.finish_reason = None
    if function_call_name:
        candidate.content.parts = [_mock_part(function_call=_mock_function_call(function_call_name))]
    else:
        candidate.content.parts = [_mock_part(text=text)]
    resp = MagicMock()
    resp.candidates = [candidate]
    resp.usage_metadata = _mock_usage_metadata(*usage) if usage else None
    return resp


def _capture(client, event_cls):
    captured: list = []

    async def cb(event):
        captured.append(event)

    client.events.subscribe(event_cls, cb)
    return captured


async def _make_client(sdk_responses):
    client = GoogleGenAIClient(api_key="fake_key")
    client.logger = MagicMock()
    client._execute_tool = AsyncMock(return_value="tool result")

    mock_client_instance = MagicMock()
    mock_chat = MagicMock()
    mock_chat.send_message = AsyncMock(side_effect=sdk_responses)
    mock_client_instance.aio.chats.create = MagicMock(return_value=mock_chat)
    client.get_client = AsyncMock(return_value=mock_client_instance)
    return client


class TestGeminiMultiroundUsage:
    @pytest.mark.asyncio
    async def test_multiround_accumulates_usage(self) -> None:
        """3-round loop (initial + 2 multiturn rounds) → AIMessage.usage = sum of 3 rounds."""
        responses = [
            _mock_response(function_call_name="get_weather", usage=(100, 10, 110)),
            _mock_response(function_call_name="search", usage=(150, 20, 170)),
            _mock_response(text="Final answer", usage=(200, 30, 230)),
        ]
        client = await _make_client(responses)
        round_events = _capture(client, ClientRoundEvent)
        after_events = _capture(client, AfterClientCallEvent)

        msg = await client.ask("What's the weather and latest news?")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert msg.usage.prompt_tokens == 450
        assert msg.usage.completion_tokens == 60
        assert msg.usage.extra_usage["rounds"] == 3
        # Regression guard: NOT just the initial response's usage (the bug).
        assert msg.usage.prompt_tokens != 100

        assert len(round_events) == 2  # one per tool round, not the final round
        assert [e.round_number for e in round_events] == [1, 2]
        assert round_events[0].tool_calls == ("get_weather",)
        assert round_events[1].tool_calls == ("search",)
        assert round_events[0].input_tokens == 100
        assert round_events[1].input_tokens == 150

        assert len(after_events) == 1
        assert after_events[0].input_tokens == 450
        assert after_events[0].output_tokens == 60

    @pytest.mark.asyncio
    async def test_singleround_no_event(self) -> None:
        """No function calls → no ClientRoundEvent; usage identical to pre-feature behavior."""
        responses = [
            _mock_response(text="Hi there", usage=(10, 5, 15)),
        ]
        client = await _make_client(responses)
        round_events = _capture(client, ClientRoundEvent)

        msg = await client.ask("Hi")
        await asyncio.sleep(0)

        assert len(round_events) == 0
        assert msg.usage.prompt_tokens == 10
        assert msg.usage.completion_tokens == 5
        assert "rounds" not in msg.usage.extra_usage

    @pytest.mark.asyncio
    async def test_after_call_totals(self) -> None:
        """AfterClientCallEvent totals equal the accumulated sums."""
        responses = [
            _mock_response(function_call_name="get_weather", usage=(100, 10, 110)),
            _mock_response(text="Done", usage=(50, 15, 65)),
        ]
        client = await _make_client(responses)
        after_events = _capture(client, AfterClientCallEvent)

        await client.ask("weather?")
        await asyncio.sleep(0)

        assert after_events[0].input_tokens == 150
        assert after_events[0].output_tokens == 25

    @pytest.mark.asyncio
    async def test_round_missing_usage_fires_none(self) -> None:
        """A round with no usage_metadata: event fires with None tokens; total unaffected."""
        responses = [
            _mock_response(function_call_name="get_weather", usage=None),
            _mock_response(text="Done", usage=(50, 15, 65)),
        ]
        client = await _make_client(responses)
        round_events = _capture(client, ClientRoundEvent)

        msg = await client.ask("weather?")
        await asyncio.sleep(0)

        assert len(round_events) == 1
        assert round_events[0].input_tokens is None
        assert round_events[0].output_tokens is None
        assert msg.usage.prompt_tokens == 50
        assert msg.usage.completion_tokens == 15

"""Unit tests for Grok client per-round usage accumulation (FEAT-397).

Drives the tool-calling loop with a mocked xai_sdk chat and asserts that
AIMessage.usage carries the accumulated total (not just the last round's
usage), that ClientRoundEvent fires once per tool round with a JSON-safe
raw_usage dict (built from the protobuf-like usage object via
CompletionUsage.from_grok's extra_usage, never the raw protobuf), and
that AfterClientCallEvent carries the accumulated totals too.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.clients.grok import GrokClient
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    ClientRoundEvent,
)


def _mock_usage(prompt: int, completion: int, total: int):
    """Stub usage object exposing attributes like the xai_sdk protobuf does."""
    usage = MagicMock(spec=[
        "prompt_tokens", "completion_tokens", "total_tokens",
        "reasoning_tokens", "cached_prompt_text_tokens", "prompt_image_tokens",
    ])
    usage.prompt_tokens = prompt
    usage.completion_tokens = completion
    usage.total_tokens = total
    usage.reasoning_tokens = 0
    usage.cached_prompt_text_tokens = 0
    usage.prompt_image_tokens = 0
    return usage


def _mock_tool_call(tool_id: str, name: str, arguments: dict = None):
    tc = MagicMock()
    tc.id = tool_id
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments or {})
    return tc


def _mock_response(content, tool_calls, usage):
    resp = MagicMock(spec=["content", "tool_calls", "usage"])
    resp.content = content
    resp.tool_calls = tool_calls
    resp.usage = usage
    return resp


def _capture(client, event_cls):
    captured: list = []

    async def cb(event):
        captured.append(event)

    client.events.subscribe(event_cls, cb)
    return captured


async def _make_client(sdk_responses):
    client = GrokClient(api_key="fake_key")
    client.logger = MagicMock()
    client._execute_tool = AsyncMock(return_value="tool result")

    mock_chat = MagicMock()
    mock_chat.sample = AsyncMock(side_effect=sdk_responses)
    mock_chat.append = MagicMock()

    mock_client_instance = MagicMock()
    mock_client_instance.chat.create = MagicMock(return_value=mock_chat)
    # GrokClient.ask() calls `client = await self.get_client()` directly
    # (no per-loop cache / _ensure_client() indirection for this client).
    client.get_client = AsyncMock(return_value=mock_client_instance)
    return client


class TestGrokMultiroundUsage:
    @pytest.mark.asyncio
    async def test_multiround_accumulates_usage(self) -> None:
        """3-round loop (2 tool rounds + final) → AIMessage.usage = sum of 3 rounds."""
        responses = [
            _mock_response(None, [_mock_tool_call("tu_1", "get_weather")], _mock_usage(100, 10, 110)),
            _mock_response(None, [_mock_tool_call("tu_2", "search")], _mock_usage(150, 20, 170)),
            _mock_response("Final answer", None, _mock_usage(200, 30, 230)),
        ]
        client = await _make_client(responses)
        round_events = _capture(client, ClientRoundEvent)
        after_events = _capture(client, AfterClientCallEvent)

        msg = await client.ask("What's the weather and latest news?", use_tools=True)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert msg.usage.prompt_tokens == 450
        assert msg.usage.completion_tokens == 60
        assert msg.usage.extra_usage["rounds"] == 3

        assert len(round_events) == 2  # one per tool round, not the final round
        assert [e.round_number for e in round_events] == [1, 2]
        assert round_events[0].tool_calls == ("get_weather",)
        assert round_events[1].tool_calls == ("search",)
        assert round_events[0].input_tokens == 100
        assert round_events[1].input_tokens == 150

        # raw_usage must be JSON-safe — never the raw protobuf-like object.
        for event in round_events:
            assert isinstance(event.raw_usage, dict)
            json.dumps(event.raw_usage)  # must not raise
            json.dumps(event.to_dict())  # full event must pass the strict check

        assert len(after_events) == 1
        assert after_events[0].input_tokens == 450
        assert after_events[0].output_tokens == 60

    @pytest.mark.asyncio
    async def test_singleround_no_event(self) -> None:
        """No tool use → no ClientRoundEvent; usage identical to pre-feature behavior."""
        responses = [
            _mock_response("Hi there", None, _mock_usage(10, 5, 15)),
        ]
        client = await _make_client(responses)
        round_events = _capture(client, ClientRoundEvent)

        msg = await client.ask("Hi", use_tools=True)
        await asyncio.sleep(0)

        assert len(round_events) == 0
        assert msg.usage.prompt_tokens == 10
        assert msg.usage.completion_tokens == 5
        assert "rounds" not in msg.usage.extra_usage

    @pytest.mark.asyncio
    async def test_after_call_totals(self) -> None:
        """AfterClientCallEvent totals equal the accumulated sums."""
        responses = [
            _mock_response(None, [_mock_tool_call("tu_1", "get_weather")], _mock_usage(100, 10, 110)),
            _mock_response("Done", None, _mock_usage(50, 15, 65)),
        ]
        client = await _make_client(responses)
        after_events = _capture(client, AfterClientCallEvent)

        await client.ask("weather?", use_tools=True)
        await asyncio.sleep(0)

        assert after_events[0].input_tokens == 150
        assert after_events[0].output_tokens == 25

    @pytest.mark.asyncio
    async def test_round_missing_usage_fires_none(self) -> None:
        """A round with no usage reported: event fires with None tokens; total unaffected."""
        responses = [
            _mock_response(None, [_mock_tool_call("tu_1", "get_weather")], None),
            _mock_response("Done", None, _mock_usage(50, 15, 65)),
        ]
        client = await _make_client(responses)
        round_events = _capture(client, ClientRoundEvent)

        msg = await client.ask("weather?", use_tools=True)
        await asyncio.sleep(0)

        assert len(round_events) == 1
        assert round_events[0].input_tokens is None
        assert round_events[0].output_tokens is None
        assert msg.usage.prompt_tokens == 50
        assert msg.usage.completion_tokens == 15

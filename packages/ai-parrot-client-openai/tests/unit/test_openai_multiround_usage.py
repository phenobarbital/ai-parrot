"""Unit tests for OpenAI client per-round usage accumulation (FEAT-397).

Drives the chat-completions path with a mocked SDK client and asserts
that AIMessage.usage carries the accumulated total (not just the last
round's usage), that ClientRoundEvent fires once per tool round, and
that AfterClientCallEvent carries the accumulated totals too.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.clients.openai import OpenAIClient
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    ClientRoundEvent,
)


def _mock_tool_call(tool_id: str, name: str, arguments: dict):
    tc = MagicMock()
    tc.id = tool_id
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    tc.model_dump.return_value = {
        "id": tool_id,
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }
    return tc


def _mock_usage(prompt: int, completion: int, total: int):
    usage = MagicMock()
    usage.prompt_tokens = prompt
    usage.completion_tokens = completion
    usage.total_tokens = total
    usage.model_dump.return_value = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }
    return usage


def _mock_response(content, tool_calls, usage):
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = tool_calls
    choice.finish_reason = "tool_calls" if tool_calls else "stop"
    choice.stop_reason = None
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    resp.model = "gpt-4.1"
    # AIMessageFactory.from_openai() builds raw_response from
    # response.model_dump() first (checked before .dict()/__dict__) — a bare
    # MagicMock auto-creates .model_dump too, but calling it returns another
    # MagicMock rather than a dict, which fails AIMessage's raw_response
    # dict_type validation. Give it a real, JSON-safe dict return value.
    resp.model_dump.return_value = {
        "model": "gpt-4.1",
        "choices": [{"message": {"content": content}, "finish_reason": choice.finish_reason}],
    }
    return resp


def _capture(client, event_cls):
    captured: list = []

    async def cb(event):
        captured.append(event)

    client.events.subscribe(event_cls, cb)
    return captured


async def _make_client(sdk_responses):
    client = OpenAIClient(api_key="fake_key")
    client.logger = MagicMock()
    client._execute_tool = AsyncMock(return_value="tool result")

    mock_client_instance = MagicMock()
    mock_client_instance.chat.completions.create = AsyncMock(side_effect=sdk_responses)
    # AbstractClient.client is a loop-local property (direct assignment is
    # rejected) — populate the per-loop cache via get_client()/_ensure_client(),
    # the supported mechanism, instead of assigning client.client directly.
    client.get_client = AsyncMock(return_value=mock_client_instance)
    await client._ensure_client()
    return client


class TestOpenAIMultiroundUsage:
    @pytest.mark.asyncio
    async def test_multiround_accumulates_usage(self) -> None:
        """3-round loop (2 tool rounds + final) → AIMessage.usage = sum of 3 rounds."""
        responses = [
            _mock_response(
                None,
                [_mock_tool_call("tu_1", "get_weather", {})],
                _mock_usage(100, 10, 110),
            ),
            _mock_response(
                None,
                [_mock_tool_call("tu_2", "search", {})],
                _mock_usage(150, 20, 170),
            ),
            _mock_response(
                "Final answer",
                None,
                _mock_usage(200, 30, 230),
            ),
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
        assert round_events[0].raw_usage == {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "total_tokens": 110,
        }

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
            _mock_response(None, [_mock_tool_call("tu_1", "get_weather", {})], _mock_usage(100, 10, 110)),
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
            _mock_response(None, [_mock_tool_call("tu_1", "get_weather", {})], None),
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


class _RespItem:
    """Minimal stand-in for a Responses-API output item (needs .content)."""

    def __init__(self, content):
        self.content = content


def _mock_raw_responses_api(output_text, tool_calls, usage):
    """Build a raw Responses-API-shaped mock consumed by _responses_completion()."""
    raw = MagicMock()
    raw.output_text = output_text
    raw.usage = usage
    if tool_calls:
        parts = [{"type": "tool_call", "id": tid, "name": name, "arguments": {}} for tid, name in tool_calls]
        raw.output = [_RespItem(parts)]
    else:
        raw.output = []
    return raw


async def _make_responses_client(raw_responses):
    client = OpenAIClient(api_key="fake_key")
    client.logger = MagicMock()
    client._execute_tool = AsyncMock(return_value="tool result")

    mock_client_instance = MagicMock()
    mock_client_instance.responses.create = AsyncMock(side_effect=raw_responses)
    client.get_client = AsyncMock(return_value=mock_client_instance)
    await client._ensure_client()
    return client


class TestOpenAIResponsesPathAccumulation:
    @pytest.mark.asyncio
    async def test_responses_path_accumulates_usage(self) -> None:
        """Responses API path: 2-round loop (1 tool round + final) accumulates usage."""
        raw_responses = [
            _mock_raw_responses_api(None, [("tu_1", "get_weather")], _mock_usage(100, 10, 110)),
            _mock_raw_responses_api("Final answer", None, _mock_usage(50, 15, 65)),
        ]
        client = await _make_responses_client(raw_responses)
        round_events = _capture(client, ClientRoundEvent)

        # "o3" is in RESPONSES_ONLY_MODELS, routing ask() through _responses_completion.
        msg = await client.ask("weather?", model="o3", use_tools=True)
        await asyncio.sleep(0)

        assert msg.usage.prompt_tokens == 150
        assert msg.usage.completion_tokens == 25
        assert msg.usage.extra_usage["rounds"] == 2
        assert len(round_events) == 1
        assert round_events[0].tool_calls == ("get_weather",)
        assert round_events[0].input_tokens == 100

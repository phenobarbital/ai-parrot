"""Unit tests for Claude client per-round usage accumulation (FEAT-397).

Mocks the Anthropic SDK's messages.create() to drive a multi-round
tool-use loop and asserts that AIMessage.usage carries the accumulated
total (not just the last round's usage), that ClientRoundEvent fires once
per tool round, and that AfterClientCallEvent carries the accumulated
totals too.
"""
from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.clients.anthropic import AnthropicClient
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    ClientRoundEvent,
)


def _mock_response(stop_reason: str, content: list, usage: dict):
    resp = MagicMock()
    resp.model_dump.return_value = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "content": content,
        "model": "claude-sonnet-4-5",
        "stop_reason": stop_reason,
        "usage": usage,
    }
    return resp


def _capture(client, event_cls):
    captured: list = []

    async def cb(event):
        captured.append(event)

    client.events.subscribe(event_cls, cb)
    return captured


def _make_client(sdk_responses):
    client = AnthropicClient(api_key="fake_key")
    client.logger = MagicMock()
    client._execute_tool = AsyncMock(return_value="tool result")

    mock_sdk_client = MagicMock()
    mock_sdk_client.messages.create = AsyncMock(side_effect=sdk_responses)

    client._backend = MagicMock()
    client._backend.build_client = AsyncMock(return_value=mock_sdk_client)
    client._backend.translate_model = lambda m: m
    return client


class TestClaudeMultiroundUsage:
    @pytest.mark.asyncio
    async def test_multiround_accumulates_usage(self) -> None:
        """3-round loop (2 tool rounds + final) → AIMessage.usage = sum of 3 rounds."""
        responses = [
            _mock_response(
                "tool_use",
                [{"type": "tool_use", "id": "tu_1", "name": "get_weather", "input": {}}],
                {"input_tokens": 100, "output_tokens": 10},
            ),
            _mock_response(
                "tool_use",
                [{"type": "tool_use", "id": "tu_2", "name": "search", "input": {}}],
                {"input_tokens": 150, "output_tokens": 20},
            ),
            _mock_response(
                "end_turn",
                [{"type": "text", "text": "Final answer"}],
                {"input_tokens": 200, "output_tokens": 30},
            ),
        ]
        client = _make_client(responses)
        round_events = _capture(client, ClientRoundEvent)
        after_events = _capture(client, AfterClientCallEvent)

        msg = await client.ask("What's the weather and latest news?")
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

        assert len(after_events) == 1
        assert after_events[0].input_tokens == 450
        assert after_events[0].output_tokens == 60

    @pytest.mark.asyncio
    async def test_singleround_no_event(self) -> None:
        """No tool use → no ClientRoundEvent; usage identical to pre-feature behavior."""
        responses = [
            _mock_response(
                "end_turn",
                [{"type": "text", "text": "Hi there"}],
                {"input_tokens": 10, "output_tokens": 5},
            ),
        ]
        client = _make_client(responses)
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
            _mock_response(
                "tool_use",
                [{"type": "tool_use", "id": "tu_1", "name": "get_weather", "input": {}}],
                {"input_tokens": 100, "output_tokens": 10},
            ),
            _mock_response(
                "end_turn",
                [{"type": "text", "text": "Done"}],
                {"input_tokens": 50, "output_tokens": 15},
            ),
        ]
        client = _make_client(responses)
        after_events = _capture(client, AfterClientCallEvent)

        await client.ask("weather?")
        await asyncio.sleep(0)

        assert after_events[0].input_tokens == 150
        assert after_events[0].output_tokens == 25

    @pytest.mark.asyncio
    async def test_round_missing_usage_fires_none(self) -> None:
        """A round with no usage reported: event fires with None tokens; total unaffected."""
        responses = [
            _mock_response(
                "tool_use",
                [{"type": "tool_use", "id": "tu_1", "name": "get_weather", "input": {}}],
                {},  # no usage reported this round
            ),
            _mock_response(
                "end_turn",
                [{"type": "text", "text": "Done"}],
                {"input_tokens": 50, "output_tokens": 15},
            ),
        ]
        client = _make_client(responses)
        round_events = _capture(client, ClientRoundEvent)

        msg = await client.ask("weather?")
        await asyncio.sleep(0)

        assert len(round_events) == 1
        assert round_events[0].input_tokens is None
        assert round_events[0].output_tokens is None
        # Total only reflects the round that did report usage.
        assert msg.usage.prompt_tokens == 50
        assert msg.usage.completion_tokens == 15

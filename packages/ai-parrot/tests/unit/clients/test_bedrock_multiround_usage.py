"""Unit tests for Bedrock/Nova per-round usage accumulation (FEAT-404).

Mocks the ``_sdk_create`` seam (Bedrock's Converse API call site) to drive
multi-round ``ask()``/``resume()`` tool-use loops and asserts that:

- ``AIMessage.usage`` carries the accumulated total across rounds (not just
  the last round's usage);
- ``cacheReadInputTokens``/``cacheWriteInputTokens`` are SUMMED across
  rounds (U1), not last-round-wins (the trap ``CompletionUsage.__add__``'s
  shallow-merge would otherwise fall into);
- ``ClientRoundEvent`` fires once per tool round (not the final round);
- ``resume()`` gains a full call-level lifecycle span
  (``BeforeClientCallEvent``/``AfterClientCallEvent``) plus the same
  per-round instrumentation (U2/U4);
- ``NovaClient`` and ``BedrockConverseClient`` both receive the fix by
  inheritance, with ``client_name`` correctly attributed on each.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from parrot.clients.bedrock import BedrockConverseClient
from parrot.clients.nova import NovaClient
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    BeforeClientCallEvent,
    ClientRoundEvent,
)


def _tool_round(tool_use_id: str, usage: dict, tool_name: str = "t") -> dict:
    return {
        "stopReason": "tool_use",
        "output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": tool_use_id, "name": tool_name, "input": {}}}
        ]}},
        "usage": usage,
    }


def _final_round(usage: dict, text: str = "done") -> dict:
    return {
        "stopReason": "end_turn",
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "usage": usage,
    }


def _capture(client, event_cls):
    captured: list = []

    async def cb(event):
        captured.append(event)

    client.events.subscribe(event_cls, cb)
    return captured


class TestBedrockAskMultiroundUsage:
    @pytest.mark.asyncio
    async def test_ask_multiround_accumulates_usage(self) -> None:
        """3-round loop (2 tool rounds + final) -> AIMessage.usage is the SUM."""
        responses = [
            _tool_round("tu_1", {"inputTokens": 100, "outputTokens": 10}, "get_weather"),
            _tool_round("tu_2", {"inputTokens": 150, "outputTokens": 20}, "search"),
            _final_round({"inputTokens": 200, "outputTokens": 30}),
        ]
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        _capture(client, ClientRoundEvent)

        with patch.object(client, "_sdk_create", side_effect=responses), \
            patch.object(client, "_execute_tool", return_value="ok"):
            msg = await client.ask("weather and news?", use_tools=True)

        assert msg.usage.prompt_tokens == 450
        assert msg.usage.completion_tokens == 60
        assert msg.usage.extra_usage["rounds"] == 3

    @pytest.mark.asyncio
    async def test_ask_emits_round_event_per_tool_round(self) -> None:
        """Exactly N-1 events for N rounds; 1-indexed; tool names captured."""
        responses = [
            _tool_round("tu_1", {"inputTokens": 100, "outputTokens": 10}, "get_weather"),
            _tool_round("tu_2", {"inputTokens": 150, "outputTokens": 20}, "search"),
            _final_round({"inputTokens": 200, "outputTokens": 30}),
        ]
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        round_events = _capture(client, ClientRoundEvent)

        with patch.object(client, "_sdk_create", side_effect=responses), \
            patch.object(client, "_execute_tool", return_value="ok"):
            await client.ask("weather and news?", use_tools=True)
        await asyncio.sleep(0)

        assert len(round_events) == 2
        assert [e.round_number for e in round_events] == [1, 2]
        assert round_events[0].tool_calls == ("get_weather",)
        assert round_events[1].tool_calls == ("search",)
        assert round_events[0].input_tokens == 100
        assert round_events[1].input_tokens == 150
        assert round_events[0].client_name == "bedrock-converse"

    @pytest.mark.asyncio
    async def test_ask_stamps_rounds_only_when_multiround(self) -> None:
        """extra_usage["rounds"] present iff rounds > 1."""
        # Multi-round.
        responses = [
            _tool_round("tu_1", {"inputTokens": 100, "outputTokens": 10}),
            _final_round({"inputTokens": 200, "outputTokens": 30}),
        ]
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, "_sdk_create", side_effect=responses), \
            patch.object(client, "_execute_tool", return_value="ok"):
            msg = await client.ask("q", use_tools=True)
        assert msg.usage.extra_usage["rounds"] == 2

        # Single-round.
        client2 = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(
            client2, "_sdk_create",
            return_value=_final_round({"inputTokens": 10, "outputTokens": 5}),
        ):
            msg2 = await client2.ask("hi")
        assert "rounds" not in msg2.usage.extra_usage

    @pytest.mark.asyncio
    async def test_ask_sums_cache_tokens_across_rounds(self) -> None:
        """cacheRead/cacheWriteInputTokens are SUMS, not last-round (U1)."""
        responses = [
            _tool_round("tu_1", {
                "inputTokens": 100, "outputTokens": 10,
                "cacheReadInputTokens": 10, "cacheWriteInputTokens": 5,
            }),
            _tool_round("tu_2", {
                "inputTokens": 150, "outputTokens": 20,
                "cacheReadInputTokens": 20, "cacheWriteInputTokens": 8,
            }),
            _final_round({
                "inputTokens": 200, "outputTokens": 30,
                "cacheReadInputTokens": 30, "cacheWriteInputTokens": 12,
            }),
        ]
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, "_sdk_create", side_effect=responses), \
            patch.object(client, "_execute_tool", return_value="ok"):
            msg = await client.ask("q", use_tools=True)

        # Sum, not last-round-wins (which would be 30/12).
        assert msg.usage.extra_usage["cacheReadInputTokens"] == 60
        assert msg.usage.extra_usage["cacheWriteInputTokens"] == 25

    @pytest.mark.asyncio
    async def test_ask_single_round_is_noop(self) -> None:
        """No tool use -> no round event, no rounds key, usage unchanged."""
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        round_events = _capture(client, ClientRoundEvent)

        with patch.object(
            client, "_sdk_create",
            return_value=_final_round({"inputTokens": 10, "outputTokens": 5}),
        ):
            msg = await client.ask("hi")
        await asyncio.sleep(0)

        assert len(round_events) == 0
        assert msg.usage.prompt_tokens == 10
        assert msg.usage.completion_tokens == 5
        assert "rounds" not in msg.usage.extra_usage

    @pytest.mark.asyncio
    async def test_ask_round_without_usage_emits_none(self) -> None:
        """Missing usage -> event fires with None tokens; accumulator untouched."""
        responses = [
            _tool_round("tu_1", {}),  # no usage reported this round
            _final_round({"inputTokens": 50, "outputTokens": 15}),
        ]
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        round_events = _capture(client, ClientRoundEvent)

        with patch.object(client, "_sdk_create", side_effect=responses), \
            patch.object(client, "_execute_tool", return_value="ok"):
            msg = await client.ask("q", use_tools=True)
        await asyncio.sleep(0)

        assert len(round_events) == 1
        assert round_events[0].input_tokens is None
        assert round_events[0].output_tokens is None
        assert msg.usage.prompt_tokens == 50
        assert msg.usage.completion_tokens == 15

    @pytest.mark.asyncio
    async def test_ask_fallback_retry_attribution(self) -> None:
        """Fallback retry: usage/timing attributed to the successful call."""

        class ThrottlingException(Exception):
            pass

        final_response = _final_round({"inputTokens": 10, "outputTokens": 5})
        client = BedrockConverseClient(
            model="claude-sonnet-4-5", fallback_model="claude-haiku-4-5"
        )
        round_events = _capture(client, ClientRoundEvent)

        with patch.object(
            client, "_sdk_create",
            side_effect=[ThrottlingException("slow down"), final_response],
        ):
            msg = await client.ask("hi")
        await asyncio.sleep(0)

        # Single (non-tool) round -> no round event, but usage/timing must
        # reflect the successful (fallback) call, not the failed one.
        assert len(round_events) == 0
        assert msg.usage.prompt_tokens == 10
        assert msg.usage.completion_tokens == 5
        assert msg.metadata.get("used_fallback_model") is True

    @pytest.mark.asyncio
    async def test_ask_fallback_retry_round_event(self) -> None:
        """Fallback retry combined with a subsequent tool round: one round
        event per loop iteration, usage from the successful call."""

        class ThrottlingException(Exception):
            pass

        responses = [
            ThrottlingException("slow down"),
            _tool_round("tu_1", {"inputTokens": 20, "outputTokens": 5}),
            _final_round({"inputTokens": 30, "outputTokens": 10}),
        ]
        client = BedrockConverseClient(
            model="claude-sonnet-4-5", fallback_model="claude-haiku-4-5"
        )
        round_events = _capture(client, ClientRoundEvent)

        with patch.object(client, "_sdk_create", side_effect=responses), \
            patch.object(client, "_execute_tool", return_value="ok"):
            await client.ask("hi", use_tools=True)
        await asyncio.sleep(0)

        assert len(round_events) == 1
        assert round_events[0].round_number == 1
        assert round_events[0].input_tokens == 20

    @pytest.mark.asyncio
    async def test_ask_no_subscribers_short_circuits(self) -> None:
        """No registry subscribers -> multi-round ask() completes without error."""
        responses = [
            _tool_round("tu_1", {"inputTokens": 10, "outputTokens": 5}),
            _final_round({"inputTokens": 20, "outputTokens": 10}),
        ]
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, "_sdk_create", side_effect=responses), \
            patch.object(client, "_execute_tool", return_value="ok"):
            msg = await client.ask("q", use_tools=True)
        assert msg.usage.extra_usage["rounds"] == 2


class TestBedrockResumeMultiroundUsage:
    @pytest.mark.asyncio
    async def test_resume_has_lifecycle_span(self) -> None:
        """BeforeClientCallEvent/AfterClientCallEvent fire around resume()."""
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        before_events = _capture(client, BeforeClientCallEvent)
        after_events = _capture(client, AfterClientCallEvent)

        state = {
            "messages": [{"role": "user", "content": [{"text": "What's the weather?"}]}],
            "tool_call_id": "tu_1",
        }
        with patch.object(
            client, "_sdk_create",
            return_value=_final_round({"inputTokens": 15, "outputTokens": 5}),
        ):
            await client.resume("session-1", "Sunny, 25C", state)
        await asyncio.sleep(0)

        assert len(before_events) == 1
        assert len(after_events) == 1
        assert after_events[0].input_tokens == 15
        assert after_events[0].output_tokens == 5

    @pytest.mark.asyncio
    async def test_resume_multiround_accumulates_and_emits(self) -> None:
        """resume(): accumulated usage, per-round events, rounds stamp,
        summed cache counters — same four assertions as ask()."""
        responses = [
            _tool_round("tu_2", {
                "inputTokens": 40, "outputTokens": 10,
                "cacheReadInputTokens": 4, "cacheWriteInputTokens": 2,
            }, "search"),
            _final_round({
                "inputTokens": 60, "outputTokens": 20,
                "cacheReadInputTokens": 6, "cacheWriteInputTokens": 3,
            }),
        ]
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        round_events = _capture(client, ClientRoundEvent)

        state = {
            "messages": [{"role": "user", "content": [{"text": "What's the weather?"}]}],
            "tool_call_id": "tu_1",
        }
        with patch.object(client, "_sdk_create", side_effect=responses), \
            patch.object(client, "_execute_tool", return_value="ok"):
            msg = await client.resume("session-1", "Sunny, 25C", state)
        await asyncio.sleep(0)

        assert msg.usage.prompt_tokens == 100
        assert msg.usage.completion_tokens == 30
        assert msg.usage.extra_usage["rounds"] == 2
        assert msg.usage.extra_usage["cacheReadInputTokens"] == 10
        assert msg.usage.extra_usage["cacheWriteInputTokens"] == 5
        assert len(round_events) == 1
        assert round_events[0].round_number == 1
        assert round_events[0].tool_calls == ("search",)

    @pytest.mark.asyncio
    async def test_resume_sums_cache_tokens_across_3plus_rounds(self) -> None:
        """resume() cache-counter summation over 3+ rounds (code-review
        follow-up: the 2-round test above cannot distinguish correct
        carry-forward summation from a bug that only manifests on the
        3rd+ accumulation step, mirroring ask()'s dedicated 3-round
        cache-sum test)."""
        responses = [
            _tool_round("tu_1", {
                "inputTokens": 10, "outputTokens": 5,
                "cacheReadInputTokens": 1, "cacheWriteInputTokens": 1,
            }, "step_one"),
            _tool_round("tu_2", {
                "inputTokens": 20, "outputTokens": 10,
                "cacheReadInputTokens": 2, "cacheWriteInputTokens": 2,
            }, "step_two"),
            _final_round({
                "inputTokens": 30, "outputTokens": 15,
                "cacheReadInputTokens": 3, "cacheWriteInputTokens": 3,
            }),
        ]
        client = BedrockConverseClient(model="claude-sonnet-4-5")

        state = {
            "messages": [{"role": "user", "content": [{"text": "What's the weather?"}]}],
            "tool_call_id": "tu_0",
        }
        with patch.object(client, "_sdk_create", side_effect=responses), \
            patch.object(client, "_execute_tool", return_value="ok"):
            msg = await client.resume("session-1", "go", state)

        assert msg.usage.extra_usage["rounds"] == 3
        # Sum across all 3 rounds (1+2+3), not last-round-wins (which
        # would be 3/3).
        assert msg.usage.extra_usage["cacheReadInputTokens"] == 6
        assert msg.usage.extra_usage["cacheWriteInputTokens"] == 6

    @pytest.mark.asyncio
    async def test_resume_single_round_is_noop(self) -> None:
        """resume() with an immediate non-tool stop: no round event, no
        rounds key — matching ask()'s single-round no-op."""
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        round_events = _capture(client, ClientRoundEvent)

        state = {
            "messages": [{"role": "user", "content": [{"text": "hi"}]}],
            "tool_call_id": "tu_1",
        }
        with patch.object(
            client, "_sdk_create",
            return_value=_final_round({"inputTokens": 10, "outputTokens": 5}),
        ):
            msg = await client.resume("session-1", "ok", state)
        await asyncio.sleep(0)

        assert len(round_events) == 0
        assert "rounds" not in msg.usage.extra_usage
        assert msg.usage.prompt_tokens == 10
        assert msg.usage.completion_tokens == 5


class TestNovaInheritsInstrumentation:
    @pytest.mark.asyncio
    async def test_nova_inherits_instrumentation(self) -> None:
        """Same mocked loop through a NovaClient instance -> client_name == 'nova'."""
        responses = [
            _tool_round("tu_1", {"inputTokens": 10, "outputTokens": 5}, "search"),
            _final_round({"inputTokens": 20, "outputTokens": 10}),
        ]
        client = NovaClient()
        round_events = _capture(client, ClientRoundEvent)

        with patch.object(client, "_sdk_create", side_effect=responses), \
            patch.object(client, "_execute_tool", return_value="ok"):
            msg = await client.ask("q", use_tools=True)
        await asyncio.sleep(0)

        assert len(round_events) == 1
        assert round_events[0].client_name == "nova"
        assert msg.usage.extra_usage["rounds"] == 2

    @pytest.mark.asyncio
    async def test_bedrock_converse_client_name_on_events(self) -> None:
        """BedrockConverseClient path -> client_name == 'bedrock-converse'."""
        responses = [
            _tool_round("tu_1", {"inputTokens": 10, "outputTokens": 5}, "search"),
            _final_round({"inputTokens": 20, "outputTokens": 10}),
        ]
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        round_events = _capture(client, ClientRoundEvent)

        with patch.object(client, "_sdk_create", side_effect=responses), \
            patch.object(client, "_execute_tool", return_value="ok"):
            await client.ask("q", use_tools=True)
        await asyncio.sleep(0)

        assert len(round_events) == 1
        assert round_events[0].client_name == "bedrock-converse"

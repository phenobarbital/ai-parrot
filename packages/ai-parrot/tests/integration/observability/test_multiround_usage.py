"""End-to-end multi-round token usage observability tests (FEAT-397).

Drives a real client (AnthropicClient, mocked SDK) through the REAL event
registry and an in-memory OTel metric reader, validating the whole
pipeline: client loop accumulation -> ClientRoundEvent/AfterClientCallEvent
-> MetricsSubscriber -> OTel metrics. Also covers the FEAT-228 per-agent
attribution regression guard on round-level metrics.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource

from navigator_eventbus.lifecycle.global_registry import scope

from parrot.clients.claude import AnthropicClient
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    ClientRoundEvent,
)
from parrot.observability.context import agent_identity
from parrot.observability.subscribers.metrics import MetricsSubscriber


# ---------------------------------------------------------------------------
# Shared helpers (mirrors tests/integration/observability/test_poc.py)
# ---------------------------------------------------------------------------

def _make_meter_provider(reader: InMemoryMetricReader) -> MeterProvider:
    """Build a MeterProvider that exposes metrics via *reader*."""
    resource = Resource.create({"service.name": "parrot-feat397"})
    return MeterProvider(resource=resource, metric_readers=[reader])


def _collect_metric_points(reader: InMemoryMetricReader, metric_name: str):
    """Collect all data points from the named metric."""
    points = []
    for rm in reader.get_metrics_data().resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == metric_name:
                    points.extend(m.data.data_points)
    return points


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


def _make_three_round_responses():
    """(100/10), (150/20) with tool_use, (200/30) final — totals (450, 60)."""
    return [
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


def _make_claude_client(sdk_responses):
    client = AnthropicClient(api_key="fake_key")
    client.logger = MagicMock()
    client._execute_tool = AsyncMock(return_value="tool result")

    mock_sdk_client = MagicMock()
    mock_sdk_client.messages.create = AsyncMock(side_effect=sdk_responses)

    client._backend = MagicMock()
    client._backend.build_client = AsyncMock(return_value=mock_sdk_client)
    client._backend.translate_model = lambda m: m
    return client


class TestMultiRoundEndToEnd:
    @pytest.mark.asyncio
    async def test_multiround_end_to_end(self) -> None:
        """Full pipeline: client loop -> events -> metrics, through the
        REAL event registry + in-memory metric reader."""
        reader = InMemoryMetricReader()
        mp = _make_meter_provider(reader)
        client = _make_claude_client(_make_three_round_responses())

        round_events: list = []
        after_events: list = []

        async def _capture_round(event):
            round_events.append(event)

        async def _capture_after(event):
            after_events.append(event)

        with scope() as registry:
            metrics_sub = MetricsSubscriber(meter_provider=mp, service_name="parrot-feat397")
            metrics_sub.register(registry)
            # Subscribing only on the GLOBAL registry mirrors real production
            # usage (MetricsSubscriber.register(global_registry) at app
            # bootstrap) — the client's own registry is isolated
            # (forward_to_global=False) and normally has zero direct
            # subscribers. _emit_round_event()'s short-circuit checks both
            # the local AND the global registry (TASK-2040 fix — see
            # Completion Note), so this is enough to prove the round events
            # actually reach a global-only observer, not just a test that
            # artificially subscribes on the client instance.
            registry.subscribe(ClientRoundEvent, _capture_round)
            registry.subscribe(AfterClientCallEvent, _capture_after)

            msg = await client.ask("What's the weather and latest news?")
            # emit_nowait schedules fire-and-forget tasks — drain them while
            # this scope's registry is still the active global one (per
            # scope()'s docstring warning).
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        # --- Client-side assertions ---
        assert msg.usage.prompt_tokens == 450
        assert msg.usage.completion_tokens == 60
        assert msg.usage.extra_usage["rounds"] == 3

        assert len(round_events) == 2  # one per tool round, not the final round
        assert [e.round_number for e in round_events] == [1, 2]
        assert round_events[0].tool_calls == ("get_weather",)
        assert round_events[1].tool_calls == ("search",)

        assert len(after_events) == 1
        assert after_events[0].input_tokens == 450
        assert after_events[0].output_tokens == 60

        # --- Metrics assertions ---
        # Per-round histogram: 2 rounds x (input + output) = 4 data points,
        # dimensioned by parrot.round.number.
        round_token_pts = _collect_metric_points(reader, "parrot.client.round.token.usage")
        assert len(round_token_pts) == 4
        by_round_and_type = {
            (pt.attributes.get("parrot.round.number"), pt.attributes.get("gen_ai.token.type")): pt.sum
            for pt in round_token_pts
        }
        assert by_round_and_type == {
            (1, "input"): 100.0,
            (1, "output"): 10.0,
            (2, "input"): 150.0,
            (2, "output"): 20.0,
        }

        # parrot.client.rounds — one increment per ClientRoundEvent (2 events).
        rounds_pts = _collect_metric_points(reader, "parrot.client.rounds")
        assert sum(pt.value for pt in rounds_pts) == 2

        # gen_ai.client.token.usage — recorded ONLY from AfterClientCallEvent,
        # reflecting the ACCUMULATED totals (450/60), never the per-round
        # values (100/150/200, 10/20/30) and never double-counted.
        total_token_pts = _collect_metric_points(reader, "gen_ai.client.token.usage")
        assert len(total_token_pts) == 2  # exactly input + output, once each
        by_type = {pt.attributes.get("gen_ai.token.type"): pt.sum for pt in total_token_pts}
        assert by_type == {"input": 450.0, "output": 60.0}

    @pytest.mark.asyncio
    async def test_per_agent_round_attribution(self) -> None:
        """FEAT-228 regression guard: round metrics carry parrot.agent.name."""
        reader = InMemoryMetricReader()
        mp = _make_meter_provider(reader)
        client = _make_claude_client(_make_three_round_responses())

        with scope() as registry:
            metrics_sub = MetricsSubscriber(meter_provider=mp, service_name="parrot-feat397")
            metrics_sub.register(registry)

            with agent_identity("bot-a"):
                await client.ask("What's the weather and latest news?")
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        round_token_pts = _collect_metric_points(reader, "parrot.client.round.token.usage")
        assert round_token_pts, "No per-round token usage recorded"
        assert all(pt.attributes.get("parrot.agent.name") == "bot-a" for pt in round_token_pts)

        rounds_pts = _collect_metric_points(reader, "parrot.client.rounds")
        assert rounds_pts, "No parrot.client.rounds recorded"
        assert all(pt.attributes.get("parrot.agent.name") == "bot-a" for pt in rounds_pts)

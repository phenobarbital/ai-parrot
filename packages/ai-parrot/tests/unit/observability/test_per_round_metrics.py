"""Unit tests for MetricsSubscriber per-round OTel instruments (FEAT-397).

Reuses the InMemoryMetricReader fixture pattern from
test_metrics_subscriber.py.
"""

from __future__ import annotations

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    ClientRoundEvent,
)
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.observability.subscribers.metrics import MetricsSubscriber


@pytest.fixture
def metrics_setup():
    """Return (registry, reader) wired with InMemoryMetricReader."""
    reader = InMemoryMetricReader()
    mp = MeterProvider(metric_readers=[reader])
    sub = MetricsSubscriber(meter_provider=mp)
    reg = EventRegistry(forward_to_global=False)
    reg.add_provider(sub)
    return reg, reader


def _all_data_points(reader: InMemoryMetricReader):
    """Extract (metric_name, attributes_dict) pairs from reader snapshot."""
    data = reader.get_metrics_data()
    points = []
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                for dp in m.data.data_points:
                    points.append((m.name, dict(dp.attributes)))
    return points


class TestPerRoundMetrics:
    @pytest.mark.asyncio
    async def test_round_histogram_records(self, metrics_setup) -> None:
        """ClientRoundEvent → parrot.client.round.token.usage records with
        parrot.round.number dimension."""
        reg, reader = metrics_setup
        tc = TraceContext.new_root()

        await reg.emit(ClientRoundEvent(
            trace_context=tc, client_name="openai", model="gpt-4o",
            round_number=1, input_tokens=100, output_tokens=20, total_tokens=120,
            tool_calls=("get_weather",),
        ))

        points = _all_data_points(reader)
        round_points = [
            (n, a) for n, a in points if n == "parrot.client.round.token.usage"
        ]
        assert len(round_points) == 2  # input + output
        for _, attrs in round_points:
            assert attrs["parrot.round.number"] == 1
        types = {a["gen_ai.token.type"] for _, a in round_points}
        assert types == {"input", "output"}

    @pytest.mark.asyncio
    async def test_rounds_counter_increments(self, metrics_setup) -> None:
        """parrot.client.rounds increments once per ClientRoundEvent."""
        reg, reader = metrics_setup
        tc = TraceContext.new_root()

        for round_number in (1, 2, 3):
            await reg.emit(ClientRoundEvent(
                trace_context=tc, client_name="openai", model="gpt-4o",
                round_number=round_number, input_tokens=10, output_tokens=5,
                total_tokens=15,
            ))

        points = _all_data_points(reader)
        rounds_points = [(n, a) for n, a in points if n == "parrot.client.rounds"]
        # Each distinct round_number creates its own attribute-set data point;
        # the counter total across them should equal the number of events.
        assert len(rounds_points) == 3

    @pytest.mark.asyncio
    async def test_no_double_count_on_total_histogram(self, metrics_setup) -> None:
        """ClientRoundEvent NEVER records onto gen_ai.client.token.usage."""
        reg, reader = metrics_setup
        tc = TraceContext.new_root()

        await reg.emit(ClientRoundEvent(
            trace_context=tc, client_name="openai", model="gpt-4o",
            round_number=1, input_tokens=100, output_tokens=20, total_tokens=120,
        ))
        # Also emit the accumulated-total AfterClientCallEvent, as a real
        # multi-round ask() call would.
        await reg.emit(AfterClientCallEvent(
            trace_context=tc, client_name="openai", model="gpt-4o",
            duration_ms=500.0, input_tokens=250, output_tokens=60,
        ))

        points = _all_data_points(reader)
        total_points = [(n, a) for n, a in points if n == "gen_ai.client.token.usage"]
        # Only the AfterClientCallEvent's 2 records (input + output) should
        # land here — the round event above must contribute ZERO.
        assert len(total_points) == 2
        recorded_values_by_type = {a["gen_ai.token.type"]: True for _, a in total_points}
        assert recorded_values_by_type == {"input": True, "output": True}

    @pytest.mark.asyncio
    async def test_none_tokens_skip_histogram(self, metrics_setup) -> None:
        """Token fields None → no token histogram records, counter still increments."""
        reg, reader = metrics_setup
        tc = TraceContext.new_root()

        await reg.emit(ClientRoundEvent(
            trace_context=tc, client_name="openai", model="gpt-4o",
            round_number=1, input_tokens=None, output_tokens=None, total_tokens=None,
        ))

        points = _all_data_points(reader)
        round_points = [
            (n, a) for n, a in points if n == "parrot.client.round.token.usage"
        ]
        assert round_points == []
        rounds_points = [(n, a) for n, a in points if n == "parrot.client.rounds"]
        assert len(rounds_points) == 1

    @pytest.mark.asyncio
    async def test_agent_name_unknown_fallback(self, metrics_setup) -> None:
        """agent_name=None falls back to 'unknown' on round metrics (FEAT-228 parity)."""
        reg, reader = metrics_setup
        tc = TraceContext.new_root()

        await reg.emit(ClientRoundEvent(
            trace_context=tc, client_name="openai", model="gpt-4o",
            round_number=1, input_tokens=10, output_tokens=5, total_tokens=15,
            agent_name=None,
        ))

        points = _all_data_points(reader)
        round_points = [
            (n, a) for n, a in points
            if n in {"parrot.client.round.token.usage", "parrot.client.rounds"}
        ]
        assert round_points
        for _, attrs in round_points:
            assert attrs["parrot.agent.name"] == "unknown"

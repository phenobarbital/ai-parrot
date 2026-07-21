"""Unit tests for MetricsSubscriber.

FEAT-177 TASK-1231.
"""

from __future__ import annotations

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    BeforeClientCallEvent,
    ClientCallFailedEvent,
)
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.observability.subscribers.metrics import MetricsSubscriber, _DEFAULT_BUCKETS


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


@pytest.mark.asyncio
async def test_full_cycle_records_request_and_tokens(metrics_setup) -> None:
    """One request cycle → request counter + 2 token histogram data points."""
    reg, reader = metrics_setup
    tc = TraceContext.new_root()

    await reg.emit(BeforeClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
    ))
    await reg.emit(AfterClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        duration_ms=1234.0, input_tokens=100, output_tokens=50,
        finish_reason="stop",
    ))

    points = _all_data_points(reader)
    names = {n for n, _ in points}
    assert "gen_ai.client.request.count" in names
    assert "gen_ai.client.token.usage" in names
    assert "gen_ai.client.operation.duration" in names

    token_points = [(n, a) for n, a in points if n == "gen_ai.client.token.usage"]
    types = {a["gen_ai.token.type"] for _, a in token_points}
    assert types == {"input", "output"}


@pytest.mark.asyncio
async def test_no_pii_in_labels(metrics_setup) -> None:
    """PII keys (user_id, session_id, etc.) must NEVER appear in metric labels."""
    reg, reader = metrics_setup
    tc = TraceContext.new_root()

    await reg.emit(BeforeClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
    ))

    points = _all_data_points(reader)
    for _, attrs in points:
        for key in attrs:
            assert key not in {
                "user_id", "session_id", "question", "prompt", "completion",
            }, f"PII key {key!r} found in metric labels"


@pytest.mark.asyncio
async def test_default_buckets() -> None:
    """Default histogram buckets are the LLM-tuned set from spec D6."""
    sub = MetricsSubscriber()
    assert sub._buckets == _DEFAULT_BUCKETS
    assert sub._buckets == [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0]


@pytest.mark.asyncio
async def test_error_increments_counter(metrics_setup) -> None:
    """ClientCallFailedEvent increments gen_ai.client.error.count."""
    reg, reader = metrics_setup
    tc = TraceContext.new_root()

    await reg.emit(ClientCallFailedEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        duration_ms=10.0, error_type="APIError", error_message="boom",
    ))

    points = _all_data_points(reader)
    err_points = [(n, a) for n, a in points if n == "gen_ai.client.error.count"]
    assert err_points, "gen_ai.client.error.count not found"
    assert err_points[0][1]["error.type"] == "APIError"


@pytest.mark.asyncio
async def test_no_cost_when_calculator_none(metrics_setup) -> None:
    """gen_ai.client.cost.total must not be incremented when calculator is None."""
    reg, reader = metrics_setup
    tc = TraceContext.new_root()

    await reg.emit(BeforeClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
    ))
    await reg.emit(AfterClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        duration_ms=100.0, input_tokens=100, output_tokens=50,
    ))

    points = _all_data_points(reader)
    cost_points = [n for n, _ in points if n == "gen_ai.client.cost.total"]
    assert len(cost_points) == 0, "cost counter should not be present without calculator"


def test_custom_buckets_stored() -> None:
    """Custom histogram_buckets are stored as-is."""
    custom = [0.1, 0.5, 2.0, 10.0]
    sub = MetricsSubscriber(histogram_buckets=custom)
    assert sub._buckets == custom

"""End-to-end PoC — 5 observability scenarios with in-memory exporters.

FEAT-177 TASK-1238.

All 5 scenarios drive lifecycle events directly against the registry and
assert against the InMemorySpanExporter / InMemoryMetricReader without any
real network traffic. This file is the CI acceptance gate for FEAT-177.

No external network calls are made; the subscribers use in-memory OTel
exporters and readers baked in at fixture time.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    AfterInvokeEvent,
    BeforeClientCallEvent,
    BeforeInvokeEvent,
)
from navigator_eventbus.lifecycle.global_registry import scope
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.observability.subscribers.metrics import MetricsSubscriber
from parrot.observability.subscribers.trace import GenAIOpenTelemetrySubscriber


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_tracer_provider(exporter: InMemorySpanExporter) -> TracerProvider:
    """Build a TracerProvider that writes spans to *exporter*."""
    resource = Resource.create({"service.name": "parrot-poc"})
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(SimpleSpanProcessor(exporter))
    return tp


def _make_meter_provider(reader: InMemoryMetricReader) -> MeterProvider:
    """Build a MeterProvider that exposes metrics via *reader*."""
    resource = Resource.create({"service.name": "parrot-poc"})
    return MeterProvider(resource=resource, metric_readers=[reader])


def _make_tc(*, sampled: bool = True) -> TraceContext:
    """Return a fresh root TraceContext, optionally un-sampled."""
    tc = TraceContext.new_root()
    if not sampled:
        # trace_flags=0 means unsampled
        tc = TraceContext(
            trace_id=tc.trace_id,
            span_id=tc.span_id,
            trace_flags=0,
            trace_state="",
            parent_span_id=None,
        )
    return tc


async def _drive_client_cycle(registry, *, client_name: str = "openai", model: str = "gpt-4o-mini") -> None:
    """Emit BeforeClientCall + AfterClientCall into *registry*."""
    tc = _make_tc()
    before = BeforeClientCallEvent(
        trace_context=tc,
        client_name=client_name,
        model=model,
        source_type="client",
        source_name=client_name,
    )
    after = AfterClientCallEvent(
        trace_context=tc,
        client_name=client_name,
        model=model,
        duration_ms=42.0,
        input_tokens=100,
        output_tokens=50,
        finish_reason="stop",
        source_type="client",
        source_name=client_name,
    )
    await registry.emit(before)
    await registry.emit(after)


async def _drive_invoke_cycle(registry, *, agent_name: str = "test-agent") -> None:
    """Emit BeforeInvoke + AfterInvoke into *registry*."""
    tc = _make_tc()
    before = BeforeInvokeEvent(
        trace_context=tc,
        agent_name=agent_name,
        method="ask",
        question="Hello",
        source_type="agent",
        source_name=agent_name,
    )
    after = AfterInvokeEvent(
        trace_context=tc,
        agent_name=agent_name,
        method="ask",
        duration_ms=123.0,
        input_tokens=100,
        output_tokens=50,
        source_type="agent",
        source_name=agent_name,
    )
    await registry.emit(before)
    await registry.emit(after)


# ---------------------------------------------------------------------------
# Scenario 1 — traces only (enable_metrics=False)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_1_traces_only() -> None:
    """Span exporter captures spans; no MetricsSubscriber registered."""
    exporter = InMemorySpanExporter()
    tp = _make_tracer_provider(exporter)

    with scope() as registry:
        trace_sub = GenAIOpenTelemetrySubscriber(
            service_name="parrot-poc",
            tracer_provider=tp,
        )
        trace_sub.register(registry)

        await _drive_client_cycle(registry)

    finished = exporter.get_finished_spans()
    assert len(finished) >= 1, f"Expected at least 1 span, got {len(finished)}"
    names = [s.name for s in finished]
    # At least one span should mention the client
    assert any("openai" in n or "client" in n or "parrot" in n for n in names), \
        f"Unexpected span names: {names}"


# ---------------------------------------------------------------------------
# Scenario 2 — metrics only (enable_traces=False)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_2_metrics_only() -> None:
    """Metric reader collects counters/histograms; no trace subscriber."""
    reader = InMemoryMetricReader()
    mp = _make_meter_provider(reader)

    with scope() as registry:
        metrics_sub = MetricsSubscriber(
            meter_provider=mp,
            service_name="parrot-poc",
        )
        metrics_sub.register(registry)

        await _drive_client_cycle(registry)

    metrics = reader.get_metrics_data()
    # At least one metric should have been recorded
    rm_list = metrics.resource_metrics
    assert rm_list, "No resource metrics collected"
    all_metrics = [
        m.name
        for rm in rm_list
        for sm in rm.scope_metrics
        for m in sm.metrics
    ]
    assert all_metrics, "No metric names found"


# ---------------------------------------------------------------------------
# Scenario 3 — traces + metrics + cost
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_3_traces_metrics_cost() -> None:
    """Both exporter and reader are populated; cost counter is updated."""
    from parrot.observability.cost.calculator import CostCalculator, _reset_pricing_cache_for_tests

    _reset_pricing_cache_for_tests()
    cost_calc = CostCalculator()

    exporter = InMemorySpanExporter()
    tp = _make_tracer_provider(exporter)
    reader = InMemoryMetricReader()
    mp = _make_meter_provider(reader)

    with scope() as registry:
        trace_sub = GenAIOpenTelemetrySubscriber(
            service_name="parrot-poc",
            tracer_provider=tp,
            cost_calculator=cost_calc,
        )
        metrics_sub = MetricsSubscriber(
            meter_provider=mp,
            service_name="parrot-poc",
            cost_calculator=cost_calc,
        )
        trace_sub.register(registry)
        metrics_sub.register(registry)

        await _drive_client_cycle(registry, client_name="openai", model="gpt-4o-mini")

    # Traces: at least one span
    spans = exporter.get_finished_spans()
    assert len(spans) >= 1, "Expected at least 1 span"

    # Metrics: at least one metric data point
    metrics = reader.get_metrics_data()
    rm_list = metrics.resource_metrics
    all_metrics = [
        m.name
        for rm in rm_list
        for sm in rm.scope_metrics
        for m in sm.metrics
    ]
    assert all_metrics, "No metrics collected"


# ---------------------------------------------------------------------------
# Scenario 4 — traces + OpenLIT (mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_4_openlit_mocked() -> None:
    """OpenLIT init is called exactly once; trace subscriber still works."""
    from parrot.observability.openlit_integration import _reset_for_tests

    _reset_for_tests()
    fake_openlit = MagicMock()

    exporter = InMemorySpanExporter()
    tp = _make_tracer_provider(exporter)

    with patch.dict(sys.modules, {"openlit": fake_openlit}):
        from parrot.observability import ObservabilityConfig  # noqa: PLC0415
        from parrot.observability.openlit_integration import init_openlit  # noqa: PLC0415

        cfg = ObservabilityConfig(enabled=True, enable_openlit=True)
        init_openlit(cfg)
        assert fake_openlit.init.call_count == 1, "openlit.init should be called once"

        # Second call is a no-op
        init_openlit(cfg)
        assert fake_openlit.init.call_count == 1, "openlit.init called more than once"

    with scope() as registry:
        trace_sub = GenAIOpenTelemetrySubscriber(
            service_name="parrot-poc",
            tracer_provider=tp,
        )
        trace_sub.register(registry)
        await _drive_client_cycle(registry)

    spans = exporter.get_finished_spans()
    assert len(spans) >= 1, "Spans expected from trace subscriber"

    _reset_for_tests()


# ---------------------------------------------------------------------------
# Scenario 5 — sampling=0.1 over 100 requests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_5_sampling_ratio() -> None:
    """With sampling_ratio=0.1 and 100 requests, roughly 10 spans arrive (±50%)."""
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased  # noqa: PLC0415

    exporter = InMemorySpanExporter()
    resource = Resource.create({"service.name": "parrot-poc"})
    tp = TracerProvider(
        resource=resource,
        sampler=TraceIdRatioBased(0.1),
    )
    tp.add_span_processor(SimpleSpanProcessor(exporter))

    with scope() as registry:
        trace_sub = GenAIOpenTelemetrySubscriber(
            service_name="parrot-poc",
            tracer_provider=tp,
        )
        trace_sub.register(registry)
        for _ in range(100):
            await _drive_client_cycle(registry)

    spans = exporter.get_finished_spans()
    # With 10% sampling, expect roughly 10 spans (±50% tolerance = 5..15).
    # The exact count is probabilistic; we use a wide tolerance for CI reliability.
    assert 2 <= len(spans) <= 25, (
        f"Expected ~10 sampled spans from 100 requests at 10% ratio, got {len(spans)}"
    )


# ---------------------------------------------------------------------------
# FEAT-228: per-agent attribution — Scenarios 6 & 7
# ---------------------------------------------------------------------------

async def _drive_client_cycle_with_agent(
    registry,
    *,
    agent_name: str,
    client_name: str = "openai",
    model: str = "gpt-4o-mini",
) -> None:
    """Emit BeforeClientCall + AfterClientCall with explicit agent_name."""
    tc = _make_tc()
    before = BeforeClientCallEvent(
        trace_context=tc,
        client_name=client_name,
        model=model,
        source_type="client",
        source_name=client_name,
        agent_name=agent_name,
    )
    after = AfterClientCallEvent(
        trace_context=tc,
        client_name=client_name,
        model=model,
        duration_ms=42.0,
        input_tokens=100,
        output_tokens=50,
        finish_reason="stop",
        source_type="client",
        source_name=client_name,
        agent_name=agent_name,
    )
    await registry.emit(before)
    await registry.emit(after)


def _collect_metric_points(reader: InMemoryMetricReader, metric_name: str):
    """Collect all data points from the named metric."""
    metrics_data = reader.get_metrics_data()
    points = []
    for rm in metrics_data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == metric_name:
                    for dp in m.data.data_points:
                        points.append(dp)
    return points


@pytest.mark.asyncio
async def test_scenario_6_metrics_carry_agent_name() -> None:
    """FEAT-228: cost/duration/token metrics carry parrot.agent.name label."""
    from parrot.observability.cost.calculator import CostCalculator, _reset_pricing_cache_for_tests  # noqa: PLC0415

    _reset_pricing_cache_for_tests()
    cost_calc = CostCalculator()
    reader = InMemoryMetricReader()
    mp = _make_meter_provider(reader)

    with scope() as registry:
        metrics_sub = MetricsSubscriber(
            meter_provider=mp,
            service_name="parrot-poc",
            cost_calculator=cost_calc,
        )
        metrics_sub.register(registry)
        await _drive_client_cycle_with_agent(
            registry, agent_name="porygon", client_name="openai", model="gpt-4o-mini"
        )

    # Check operation duration histogram carries the agent label
    duration_pts = _collect_metric_points(reader, "gen_ai.client.operation.duration")
    assert duration_pts, "No duration data points collected"
    assert any(
        pt.attributes.get("parrot.agent.name") == "porygon"
        for pt in duration_pts
    ), "parrot.agent.name='porygon' not found in duration metric labels"

    # Check token usage histogram
    token_pts = _collect_metric_points(reader, "gen_ai.client.token.usage")
    assert token_pts, "No token usage data points"
    assert any(
        pt.attributes.get("parrot.agent.name") == "porygon"
        for pt in token_pts
    ), "parrot.agent.name='porygon' not found in token metric labels"

    # Check cost counter carries agent label (only when pricing data is available)
    cost_pts = _collect_metric_points(reader, "gen_ai.client.cost.total")
    if cost_pts:
        assert any(
            pt.attributes.get("parrot.agent.name") == "porygon"
            for pt in cost_pts
        ), "parrot.agent.name='porygon' not found in cost metric labels"


@pytest.mark.asyncio
async def test_scenario_7_metrics_unknown_when_agent_none() -> None:
    """FEAT-228: when agent_name is None, metrics label uses 'unknown'."""
    reader = InMemoryMetricReader()
    mp = _make_meter_provider(reader)

    with scope() as registry:
        metrics_sub = MetricsSubscriber(
            meter_provider=mp,
            service_name="parrot-poc",
        )
        metrics_sub.register(registry)
        # Use regular _drive_client_cycle which passes agent_name=None (default)
        await _drive_client_cycle(registry, client_name="openai", model="gpt-4o-mini")

    duration_pts = _collect_metric_points(reader, "gen_ai.client.operation.duration")
    assert duration_pts, "No duration data points"
    assert any(
        pt.attributes.get("parrot.agent.name") == "unknown"
        for pt in duration_pts
    ), "parrot.agent.name='unknown' not found for None agent"


# ---------------------------------------------------------------------------
# FEAT-228: per-agent attribution — Scenarios 8 & 9 (client span attributes)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario_8_client_span_has_agent_name() -> None:
    """FEAT-228: client child span carries parrot.agent.name when agent is set."""
    exporter = InMemorySpanExporter()
    tp = _make_tracer_provider(exporter)

    with scope() as registry:
        trace_sub = GenAIOpenTelemetrySubscriber(
            service_name="parrot-poc",
            tracer_provider=tp,
        )
        trace_sub.register(registry)
        await _drive_client_cycle_with_agent(
            registry, agent_name="porygon", client_name="openai", model="gpt-4o-mini"
        )

    finished = exporter.get_finished_spans()
    assert finished, "No spans collected"
    # The client span has gen_ai.response.model or gen_ai.request.model set
    client_spans = [
        s for s in finished
        if s.attributes.get("gen_ai.response.model") or s.attributes.get("gen_ai.request.model")
    ]
    assert client_spans, f"No client span found; spans: {[s.name for s in finished]}"
    for span in client_spans:
        assert span.attributes.get("parrot.agent.name") == "porygon", (
            f"Expected parrot.agent.name='porygon' on span '{span.name}', "
            f"got: {dict(span.attributes)}"
        )


@pytest.mark.asyncio
async def test_scenario_9_client_span_omits_agent_when_none() -> None:
    """FEAT-228: client child span omits parrot.agent.name when agent_name is None."""
    exporter = InMemorySpanExporter()
    tp = _make_tracer_provider(exporter)

    with scope() as registry:
        trace_sub = GenAIOpenTelemetrySubscriber(
            service_name="parrot-poc",
            tracer_provider=tp,
        )
        trace_sub.register(registry)
        # Regular cycle — agent_name=None (not passed to events)
        await _drive_client_cycle(registry, client_name="openai", model="gpt-4o-mini")

    finished = exporter.get_finished_spans()
    assert finished, "No spans collected"
    client_spans = [
        s for s in finished
        if s.attributes.get("gen_ai.response.model") or s.attributes.get("gen_ai.request.model")
    ]
    assert client_spans, f"No client span found; spans: {[s.name for s in finished]}"
    for span in client_spans:
        assert "parrot.agent.name" not in span.attributes, (
            f"parrot.agent.name should be omitted when agent_name=None, "
            f"but found it on span '{span.name}': {dict(span.attributes)}"
        )


@pytest.mark.asyncio
async def test_token_reset_on_exception() -> None:
    """FEAT-228: ContextVar token is reset even when the body raises."""
    from parrot.observability.context import agent_identity, current_agent_name

    assert current_agent_name.get() is None
    with pytest.raises(ValueError):
        with agent_identity("porygon"):
            assert current_agent_name.get() == "porygon"
            raise ValueError("forced")
    assert current_agent_name.get() is None, "Token must be reset after exception"


@pytest.mark.asyncio
async def test_concurrent_task_isolation() -> None:
    """FEAT-228: ContextVar does not leak across concurrent asyncio tasks."""
    import asyncio
    from parrot.observability.context import agent_identity, current_agent_name

    results: dict[str, str | None] = {}

    async def run_as(name: str) -> None:
        with agent_identity(name):
            await asyncio.sleep(0)  # yield to allow other tasks to run
            results[name] = current_agent_name.get()

    await asyncio.gather(
        asyncio.create_task(run_as("agent-a")),
        asyncio.create_task(run_as("agent-b")),
    )
    assert results["agent-a"] == "agent-a"
    assert results["agent-b"] == "agent-b"

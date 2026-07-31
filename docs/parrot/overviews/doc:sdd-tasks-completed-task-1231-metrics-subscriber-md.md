---
type: Wiki Overview
title: 'TASK-1231: MetricsSubscriber'
id: doc:sdd-tasks-completed-task-1231-metrics-subscriber-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §3 Module 4 and §2 (Event → Metric mapping). Separate subscriber (not
  the trace subscriber) that emits OTel counters and histograms for tokens, latency,
  errors, and cost. Decision Q2 from the brainstorm: separate subscriber allows Prometheus-only
  deployments without spans.'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
- concept: mod:parrot.observability.attributes
  rel: mentions
- concept: mod:parrot.observability.cost.calculator
  rel: mentions
- concept: mod:parrot.observability.subscribers.metrics
  rel: mentions
---

# TASK-1231: MetricsSubscriber

**Feature**: FEAT-177 — OpenTelemetry + Cost Observability
**Spec**: `sdd/specs/otel-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1229
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 and §2 (Event → Metric mapping). Separate subscriber (not the trace subscriber) that emits OTel counters and histograms for tokens, latency, errors, and cost. Decision Q2 from the brainstorm: separate subscriber allows Prometheus-only deployments without spans.

---

## Scope

- Create `parrot/observability/subscribers/metrics.py` with `MetricsSubscriber`.
- Implement `register(registry)` subscribing to 5 event classes (`BeforeClientCallEvent`, `AfterClientCallEvent`, `ClientCallFailedEvent`, `AfterToolCallEvent`, `ToolCallFailedEvent`, `AfterInvokeEvent`, `InvokeFailedEvent`).
- Construct counters and histograms at init time via the OTel meter.
- Enforce cardinality whitelist per metric (spec §2 table).
- Default histogram buckets `[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0]` seconds (per D6 resolution); overridable via constructor param.
- `ClientStreamChunkEvent` is NEVER subscribed — chunks must not update metrics.
- Unit tests with `InMemoryMetricReader`.

**NOT in scope**: span creation (TASK-1230), cost calculation logic (TASK-1232 supplies `CostCalculator`; this subscriber accepts `Optional[CostCalculator] = None`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py` | CREATE | `MetricsSubscriber`. |
| `packages/ai-parrot/tests/unit/observability/test_metrics_subscriber.py` | CREATE | Counter/histogram + cardinality tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
from typing import TYPE_CHECKING, Any, Optional

from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent, AfterInvokeEvent, AfterToolCallEvent,
    BeforeClientCallEvent, ClientCallFailedEvent,
    InvokeFailedEvent, ToolCallFailedEvent,
)
from parrot.observability.attributes import resolve_gen_ai_system

if TYPE_CHECKING:
    from parrot.core.events.lifecycle.registry import EventRegistry
    from parrot.observability.cost.calculator import CostCalculator

# Lazy-imported inside __init__:
#   from opentelemetry import metrics
```

### Metric definitions per spec §2 Event → Metric mapping

| Event | Metric | Type | Labels (whitelist) |
|---|---|---|---|
| `BeforeClientCallEvent` | `gen_ai.client.request.count` | Counter | `gen_ai.system`, `gen_ai.request.model` |
| `AfterClientCallEvent` | `gen_ai.client.operation.duration` | Histogram | `gen_ai.system`, `gen_ai.operation.name` |
| `AfterClientCallEvent` | `gen_ai.client.token.usage` | Histogram (record twice: input + output) | `gen_ai.system`, `gen_ai.response.model`, `gen_ai.token.type` |
| `AfterClientCallEvent` | `gen_ai.client.cost.total` | Counter (USD) | `gen_ai.system`, `gen_ai.response.model` |
| `ClientCallFailedEvent` | `gen_ai.client.error.count` | Counter | `gen_ai.system`, `error.type` |
| `AfterToolCallEvent` | `parrot.tool.execution.duration` | Histogram | `parrot.tool.name` |
| `ToolCallFailedEvent` | `parrot.tool.failure.count` | Counter | `parrot.tool.name`, `error.type` |
| `AfterInvokeEvent` | `parrot.agent.invoke.duration` | Histogram | `parrot.agent.name`, `parrot.invoke.method` |
| `InvokeFailedEvent` | `parrot.agent.invoke.failure.count` | Counter | `parrot.agent.name`, `error.type` |

### Does NOT Exist

- ~~`ClientStreamChunkEvent` metric subscription~~ — chunks NEVER update metrics. Do not subscribe.
- ~~`session_id` / `user_id` labels~~ — high-cardinality. Belong on spans only.

---

## Implementation Notes

### Constructor

```python
class MetricsSubscriber:
    def __init__(
        self,
        *,
        meter_provider: Optional[Any] = None,
        service_name: str = "ai-parrot",
        histogram_buckets: Optional[list[float]] = None,
        cost_calculator: Optional["CostCalculator"] = None,
    ) -> None:
        try:
            from opentelemetry import metrics
        except ImportError as exc:
            raise ImportError(
                "MetricsSubscriber requires the 'observability' extra."
            ) from exc

        meter = (meter_provider or metrics.get_meter_provider()).get_meter(service_name)
        buckets = histogram_buckets or [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0]
        self._cost = cost_calculator

        # Counters
        self._client_request_count = meter.create_counter("gen_ai.client.request.count")
        self._client_error_count = meter.create_counter("gen_ai.client.error.count")
        self._client_cost_total = meter.create_counter(
            "gen_ai.client.cost.total", unit="USD",
        )
        self._tool_failure_count = meter.create_counter("parrot.tool.failure.count")
        self._invoke_failure_count = meter.create_counter("parrot.agent.invoke.failure.count")

        # Histograms (buckets via Views in setup_telemetry; default applies if Views absent)
        self._client_op_duration = meter.create_histogram(
            "gen_ai.client.operation.duration", unit="s",
        )
        self._client_token_usage = meter.create_histogram(
            "gen_ai.client.token.usage", unit="tokens",
        )
        self._tool_exec_duration = meter.create_histogram(
            "parrot.tool.execution.duration", unit="s",
        )
        self._invoke_duration = meter.create_histogram(
            "parrot.agent.invoke.duration", unit="s",
        )
        self._buckets = buckets   # exposed for setup_telemetry to wire Views
```

### Recording pattern

```python
async def _on_client_after(self, event: AfterClientCallEvent) -> None:
    system = resolve_gen_ai_system(event.client_name)
    base_labels = {"gen_ai.system": system, "gen_ai.response.model": event.model}
    self._client_op_duration.record(
        event.duration_ms / 1000.0,
        attributes={**base_labels, "gen_ai.operation.name": "chat"},
    )
    if event.input_tokens is not None:
        self._client_token_usage.record(
            event.input_tokens,
            attributes={**base_labels, "gen_ai.token.type": "input"},
        )
    if event.output_tokens is not None:
        self._client_token_usage.record(
            event.output_tokens,
            attributes={**base_labels, "gen_ai.token.type": "output"},
        )
    if self._cost is not None:
        cost = self._cost.cost_usd(
            provider=system, model=event.model,
            input_tokens=event.input_tokens or 0,
            output_tokens=event.output_tokens or 0,
        )
        if cost is not None:
            self._client_cost_total.add(cost, attributes=base_labels)
```

### Key Constraints

- Labels are STRICTLY the whitelist from the table above. Do NOT pass `**vars(event)` or similar.
- Histogram values for durations are in **seconds** (convert from `duration_ms`).
- `_client_token_usage.record(...)` called TWICE per `AfterClientCallEvent` (once with `gen_ai.token.type="input"`, once with `="output"`), skipping if the token count is None.
- Cost counter is added only when calculator returns non-None.
- Histogram bucket configuration is done via OTel Views in `setup_telemetry` (TASK-1235); store `self._buckets` and expose via a property/getter so TASK-1235 can wire it.

---

## Acceptance Criteria

- [ ] `from parrot.observability.subscribers.metrics import MetricsSubscriber` resolves.
- [ ] `register(registry)` subscribes 7 callbacks (one per applicable event; `ClientStreamChunkEvent` NOT subscribed).
- [ ] With `InMemoryMetricReader`: one full request cycle → `gen_ai.client.request.count == 1`, `gen_ai.client.token.usage` has 2 data points (input + output), `gen_ai.client.operation.duration` has 1 data point.
- [ ] Extra non-whitelisted fields (`user_id`, `session_id`, `question`) NEVER appear in metric label sets.
- [ ] Default buckets attribute is `[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0]`.
- [ ] When `cost_calculator=None`, `gen_ai.client.cost.total` is never incremented.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/observability/test_metrics_subscriber.py
import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from parrot.core.events.lifecycle.registry import EventRegistry
from parrot.core.events.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.events import (
    BeforeClientCallEvent, AfterClientCallEvent, ClientCallFailedEvent,
)
from parrot.observability.subscribers.metrics import MetricsSubscriber


@pytest.fixture
def metrics_setup():
    reader = InMemoryMetricReader()
    mp = MeterProvider(metric_readers=[reader])
    sub = MetricsSubscriber(meter_provider=mp)
    reg = EventRegistry(forward_to_global=False)
    reg.add_provider(sub)
    return reg, reader


def _all_data_points(reader):
    data = reader.get_metrics_data()
    points = []
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                for dp in m.data.data_points:
                    points.append((m.name, dict(dp.attributes)))
    return points


@pytest.mark.asyncio
async def test_full_cycle_records_request_and_tokens(metrics_setup):
    reg, reader = metrics_setup
    tc = TraceContext.new_root()
    await reg.emit(BeforeClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o"))
    await reg.emit(AfterClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        duration_ms=1234.0, input_tokens=100, output_tokens=50,
        finish_reason="stop"))
    points = _all_data_points(reader)
    names = {n for n, _ in points}
    assert "gen_ai.client.request.count" in names
    assert "gen_ai.client.token.usage" in names
    assert "gen_ai.client.operation.duration" in names

    token_points = [(n, a) for n, a in points if n == "gen_ai.client.token.usage"]
    types = {a["gen_ai.token.type"] for _, a in token_points}
    assert types == {"input", "output"}


@pytest.mark.asyncio
async def test_no_pii_in_labels(metrics_setup):
    reg, reader = metrics_setup
    tc = TraceContext.new_root()
    await reg.emit(BeforeClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o"))
    points = _all_data_points(reader)
    for _, attrs in points:
        for key in attrs:
            assert key not in {"user_id", "session_id", "question",
                               "prompt", "completion"}


@pytest.mark.asyncio
async def test_default_buckets():
    sub = MetricsSubscriber()
    assert sub._buckets == [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0]


@pytest.mark.asyncio
async def test_error_increments_counter(metrics_setup):
    reg, reader = metrics_setup
    tc = TraceContext.new_root()
    await reg.emit(ClientCallFailedEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        duration_ms=10.0, error_type="APIError", error_message="boom"))
    points = _all_data_points(reader)
    err_points = [(n, a) for n, a in points if n == "gen_ai.client.error.count"]
    assert err_points
    assert err_points[0][1]["error.type"] == "APIError"
```

---

## Agent Instructions

1. Confirm TASK-1229 complete.
2. Implement metrics.py + tests.
3. Run `pytest packages/ai-parrot/tests/unit/observability/test_metrics_subscriber.py -v`.

---

## Completion Note

*(Agent fills this in when done)*

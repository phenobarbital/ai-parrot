---
type: Wiki Overview
title: 'TASK-1230: GenAIOpenTelemetrySubscriber'
id: doc:sdd-tasks-completed-task-1230-genai-opentelemetry-subscriber-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 3 and §2 (Event → Span mapping). The rich subscriber that
  maps 12 of FEAT-176's lifecycle events to OTel spans with full GenAI SemConv attributes.
  Coexists with FEAT-176's `OpenTelemetrySubscriber` stub via name disambiguation
  (different class name).
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.base
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
- concept: mod:parrot.observability.subscribers.trace
  rel: mentions
---

# TASK-1230: GenAIOpenTelemetrySubscriber

**Feature**: FEAT-177 — OpenTelemetry + Cost Observability
**Spec**: `sdd/specs/otel-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1229
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 and §2 (Event → Span mapping). The rich subscriber that maps 12 of FEAT-176's lifecycle events to OTel spans with full GenAI SemConv attributes. Coexists with FEAT-176's `OpenTelemetrySubscriber` stub via name disambiguation (different class name).

---

## Scope

- Create `parrot/observability/subscribers/trace.py` with `GenAIOpenTelemetrySubscriber` class.
- Implement `register(registry)` per `EventProvider` Protocol — subscribe to 12 event classes.
- Open spans on `Before*Event`, close on `After*Event` / `*FailedEvent` using `trace_context.span_id` as key in `_active_spans: dict[str, Span]`.
- Use `_otel_parent_context()` helper (mirror FEAT-176 stub pattern at `subscribers/opentelemetry.py:120-142`).
- `asyncio.Lock` around `_active_spans` for concurrent safety.
- `MessageAddedEvent` and `AgentStatusChangedEvent` add span events to the currently-active span instead of creating new spans.
- `ClientStreamChunkEvent` is a no-op unless `capture_completions=True` (config flag passed at construction).
- Unit tests using `InMemorySpanExporter`.

**NOT in scope**: cost calculation (uses `CostCalculator` injected at construction; that class lands in TASK-1232 — for now accept `Optional[CostCalculator] = None`), metrics emission (TASK-1231), the bundling provider (TASK-1233), `setup_telemetry` (TASK-1235).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/subscribers/trace.py` | CREATE | `GenAIOpenTelemetrySubscriber`. |
| `packages/ai-parrot/tests/unit/observability/test_trace_subscriber.py` | CREATE | Span tree + status + streaming tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
import asyncio
from typing import TYPE_CHECKING, Any, Dict, Optional

from parrot.core.events.lifecycle.base import LifecycleEvent
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent, AfterInvokeEvent, AfterToolCallEvent,
    BeforeClientCallEvent, BeforeInvokeEvent, BeforeToolCallEvent,
    ClientCallFailedEvent, ClientStreamChunkEvent,
    InvokeFailedEvent, ToolCallFailedEvent,
    MessageAddedEvent, AgentStatusChangedEvent,
)
from parrot.observability.attributes import (
    PROVIDER_TO_GEN_AI_SYSTEM, resolve_gen_ai_system,
    build_after_client_attrs, build_after_invoke_attrs,
    build_after_tool_attrs, build_before_client_attrs,
    build_before_invoke_attrs, build_before_tool_attrs,
    build_client_failed_attrs, build_message_event_attrs,
    build_tool_failed_attrs,
)

if TYPE_CHECKING:
    from parrot.core.events.lifecycle.registry import EventRegistry
    from parrot.observability.cost.calculator import CostCalculator

# Lazy-imported inside __init__ and helpers:
#   from opentelemetry import trace
#   from opentelemetry.trace import (
#       NonRecordingSpan, SpanContext, Status, StatusCode, TraceFlags,
#       set_span_in_context,
#   )
```

### Existing Signatures to Use

```python
# parrot/core/events/lifecycle/subscribers/opentelemetry.py (FEAT-176 stub — pattern to mirror)
# Line 39-262 — full reference for parent-context derivation, asyncio.Lock usage,
# span lifecycle, register() shape. DO NOT MODIFY this file.

# Pattern excerpt (lines 120-142) — reuse verbatim, replacing class name:
def _otel_parent_context(self, tc: Any) -> Any:
    if tc is None or tc.parent_span_id is None:
        return None
    from opentelemetry.trace import (
        NonRecordingSpan, SpanContext, TraceFlags, set_span_in_context,
    )
    parent_sc = SpanContext(
        trace_id=int(tc.trace_id, 16),
        span_id=int(tc.parent_span_id, 16),
        is_remote=False,
        trace_flags=TraceFlags(tc.trace_flags),
    )
    return set_span_in_context(NonRecordingSpan(parent_sc))

# EventProvider Protocol — provider.py:45
def register(self, registry: "EventRegistry") -> None: ...
```

### Does NOT Exist

- ~~`OpenTelemetrySubscriber` as our class name~~ — name is taken by FEAT-176 stub. Use `GenAIOpenTelemetrySubscriber`.
- ~~`event.source_name`~~ — bug in FEAT-176 stub line 237. Use `event.client_name`.
- ~~A way to share `_active_spans` across event loops~~ — instances are loop-scoped; documented in FEAT-176 stub docstring.

---

## Implementation Notes

### Constructor

```python
class GenAIOpenTelemetrySubscriber:
    def __init__(
        self,
        *,
        service_name: str = "ai-parrot",
        tracer_provider: Optional[Any] = None,
        cost_calculator: Optional["CostCalculator"] = None,
        capture_completions: bool = False,
    ) -> None:
        try:
            from opentelemetry import trace  # noqa
        except ImportError as exc:
            raise ImportError(
                "GenAIOpenTelemetrySubscriber requires the 'observability' extra. "
                "Install with: pip install 'ai-parrot[observability]'"
            ) from exc
        if tracer_provider is not None:
            self._tracer = tracer_provider.get_tracer(service_name)
        else:
            from opentelemetry import trace as otel_trace
            self._tracer = otel_trace.get_tracer(service_name)
        self._cost = cost_calculator
        self._capture_completions = capture_completions
        self._active_spans: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
```

### Span naming (per spec §2 Event → Span mapping)

| Event | Span name template |
|---|---|
| `BeforeInvokeEvent` | `"parrot.agent.invoke"` |
| `BeforeClientCallEvent` | `f"parrot.client.{resolve_gen_ai_system(client_name)}.chat"` |
| `BeforeToolCallEvent` | `f"parrot.tool.{event.tool_name or 'unknown'}"` |

### After/Failed pattern

```python
async def _on_client_end(self, event: AfterClientCallEvent) -> None:
    cost = None
    if self._cost is not None:
        cost = self._cost.cost_usd(
            provider=resolve_gen_ai_system(event.client_name),
            model=event.model,
            input_tokens=event.input_tokens or 0,
            output_tokens=event.output_tokens or 0,
        )
    attrs = build_after_client_attrs(event, cost_usd=cost)
    await self._end_span_ok(event, extra_attrs=attrs)
```

`_end_span_ok` / `_end_span_error` mirror FEAT-176 stub shape but accept `extra_attrs` to attach final usage data before closing.

### MessageAddedEvent / AgentStatusChangedEvent

These attach span events (not spans) to the currently-active span:

```python
async def _on_message(self, event: MessageAddedEvent) -> None:
    span_key = event.trace_context.span_id if event.trace_context else None
    if not span_key:
        return
    async with self._lock:
        span = self._active_spans.get(span_key)
    if span is None:
        return
    attrs = build_message_event_attrs(event)
    span.add_event("parrot.message_added", attributes=attrs)
```

### ClientStreamChunkEvent

```python
async def _on_chunk(self, event: ClientStreamChunkEvent) -> None:
    if not self._capture_completions:
        return    # default: NEVER touch the span on chunks
    span_key = event.trace_context.span_id if event.trace_context else None
    # ... attach span event with chunk index + size only (never content)
```

### Key Constraints

- All callbacks `async def`.
- Never log at INFO inside callbacks (hot path) — DEBUG only.
- Never raise from callbacks; FEAT-176's registry catches but a clean callback is preferred.
- Never reference `event.prompt`, `event.completion`, `event.question` — they're not on these events.

---

## Acceptance Criteria

- [ ] `from parrot.observability.subscribers.trace import GenAIOpenTelemetrySubscriber` resolves.
- [ ] `register(registry)` subscribes 12 callbacks (one per applicable event class).
- [ ] With `InMemorySpanExporter`: one full request cycle (BeforeInvoke + BeforeClient + AfterClient + AfterInvoke) produces 2 spans (root + child) with `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` attrs.
- [ ] Failed call (`ClientCallFailedEvent`) ends span with `Status(StatusCode.ERROR)` and records `error.type` / `error.message`.
- [ ] `ClientStreamChunkEvent` with `capture_completions=False` (default) attaches NO span event.
- [ ] `ClientStreamChunkEvent` with `capture_completions=True` attaches ONE span event per chunk.
- [ ] When `cost_calculator` is `None`, `parrot.cost.usd` attr is absent (not zero).
- [ ] `MessageAddedEvent` adds a span event to the active span — does NOT create a new span.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/observability/test_trace_subscriber.py
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from parrot.core.events.lifecycle.registry import EventRegistry
from parrot.core.events.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.events import (
    BeforeInvokeEvent, AfterInvokeEvent,
    BeforeClientCallEvent, AfterClientCallEvent, ClientCallFailedEvent,
    ClientStreamChunkEvent, MessageAddedEvent,
)
from parrot.observability.subscribers.trace import GenAIOpenTelemetrySubscriber


@pytest.fixture
def telemetry():
    exporter = InMemorySpanExporter()
    tp = TracerProvider()
    tp.add_span_processor(SimpleSpanProcessor(exporter))
    sub = GenAIOpenTelemetrySubscriber(tracer_provider=tp)
    reg = EventRegistry(forward_to_global=False)
    reg.add_provider(sub)
    return reg, exporter, sub


@pytest.mark.asyncio
async def test_full_cycle_produces_parent_child(telemetry):
    reg, exporter, _ = telemetry
    root = TraceContext.new_root()
    child = root.child()

    await reg.emit(BeforeInvokeEvent(
        trace_context=root, agent_name="bot", method="ask"))
    await reg.emit(BeforeClientCallEvent(
        trace_context=child, client_name="openai", model="gpt-4o",
        temperature=0.7, has_tools=False))
    await reg.emit(AfterClientCallEvent(
        trace_context=child, client_name="openai", model="gpt-4o",
        duration_ms=1234.0, input_tokens=100, output_tokens=50,
        finish_reason="stop"))
    await reg.emit(AfterInvokeEvent(
        trace_context=root, agent_name="bot", method="ask",
        duration_ms=2345.0))

    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    client_span = next(s for s in spans if "client" in s.name)
    assert client_span.attributes["gen_ai.system"] == "openai"
    assert client_span.attributes["gen_ai.usage.input_tokens"] == 100


@pytest.mark.asyncio
async def test_failed_client_sets_error_status(telemetry):
    reg, exporter, _ = telemetry
    tc = TraceContext.new_root()
    await reg.emit(BeforeClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o"))
    await reg.emit(ClientCallFailedEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        duration_ms=10.0, error_type="APIError", error_message="boom"))
    span = exporter.get_finished_spans()[0]
    assert span.status.is_ok is False
    assert span.attributes["error.type"] == "APIError"


@pytest.mark.asyncio
async def test_chunk_default_skipped(telemetry):
    reg, exporter, _ = telemetry
    tc = TraceContext.new_root()
    await reg.emit(BeforeClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o"))
    await reg.emit(ClientStreamChunkEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        chunk_index=0, chunk_size_bytes=42))
    await reg.emit(AfterClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        duration_ms=1.0, input_tokens=1, output_tokens=1))
    span = exporter.get_finished_spans()[0]
    assert all("chunk" not in e.name for e in span.events)


@pytest.mark.asyncio
async def test_chunk_opt_in_adds_span_event():
    exporter = InMemorySpanExporter()
    tp = TracerProvider()
    tp.add_span_processor(SimpleSpanProcessor(exporter))
    sub = GenAIOpenTelemetrySubscriber(tracer_provider=tp, capture_completions=True)
    reg = EventRegistry(forward_to_global=False)
    reg.add_provider(sub)
    tc = TraceContext.new_root()
    await reg.emit(BeforeClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o"))
    await reg.emit(ClientStreamChunkEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        chunk_index=0, chunk_size_bytes=42))
    await reg.emit(AfterClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o",
        duration_ms=1.0))
    span = exporter.get_finished_spans()[0]
    assert any("chunk" in e.name for e in span.events)
```

---

## Agent Instructions

1. Confirm TASK-1229 (`attributes.py`) is complete.
2. Read `subscribers/opentelemetry.py` (FEAT-176 stub) before implementing — it is the structural pattern. Replicate the `asyncio.Lock` + `_active_spans` dict approach; do NOT modify it.
3. Implement `trace.py` + tests.
4. Run `pytest packages/ai-parrot/tests/unit/observability/test_trace_subscriber.py -v`.

---

## Completion Note

*(Agent fills this in when done)*

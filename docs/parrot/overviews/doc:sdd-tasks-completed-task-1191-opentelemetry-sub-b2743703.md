---
type: Wiki Overview
title: 'TASK-1191: Implement OpenTelemetrySubscriber + extras_require[''otel'']'
id: doc:sdd-tasks-completed-task-1191-opentelemetry-subscriber-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 10 of the spec. `OpenTelemetrySubscriber` maps `LifecycleEvent`s to
  OTel spans, so that any project running an OTel collector (Jaeger, Zipkin, Datadog
  APM, Honeycomb, etc.) gets distributed tracing across agent → client → tool boundaries
  for free. This is the headline payo
relates_to:
- concept: mod:parrot.core.events.lifecycle.base
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.subscribers.opentelemetry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
---

# TASK-1191: Implement OpenTelemetrySubscriber + extras_require['otel']

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-1184
**Assigned-to**: unassigned

---

## Context

Module 10 of the spec. `OpenTelemetrySubscriber` maps `LifecycleEvent`s to OTel spans, so that any project running an OTel collector (Jaeger, Zipkin, Datadog APM, Honeycomb, etc.) gets distributed tracing across agent → client → tool boundaries for free. This is the headline payoff of FEAT-176's W3C Trace Context design.

`opentelemetry-api` and `opentelemetry-sdk` are NOT core dependencies — they live under `extras_require['otel']`. Importing the subscriber without the extra installed must raise a clear `ImportError`, never a cryptic missing-module error at first use.

Spec section: §3 Module 10 and §7 (Lazy imports for OTel).

**Parallel-safe** with TASK-1190 / 1192 / 1186 / 1187 / 1188 / 1189 (different file).

---

## Scope

- Implement `OpenTelemetrySubscriber` with lazy OTel imports inside the class body / methods only (NEVER at module top-level).
- Map events to spans:
  - `BeforeInvokeEvent` → opens a span (name: `agent.{agent_name}.{method}`).
  - `AfterInvokeEvent` → closes the matching span with OK status.
  - `InvokeFailedEvent` → closes with ERROR status + exception attrs.
  - Same pattern for `BeforeClientCallEvent` / `AfterClientCallEvent` / `ClientCallFailedEvent`.
  - Same pattern for `BeforeToolCallEvent` / `AfterToolCallEvent` / `ToolCallFailedEvent`.
- Add `extras_require['otel']` to `packages/ai-parrot/pyproject.toml`.
- If `opentelemetry-api` is not installed, calling `OpenTelemetrySubscriber()` (the constructor — not just `import`) must raise `ImportError` with a message like: "OpenTelemetrySubscriber requires the 'otel' extra: pip install 'ai-parrot[otel]'".
- Add unit tests using `opentelemetry.sdk.trace.export.in_memory_span_exporter.InMemorySpanExporter` to verify span creation, parent/child relationships from `trace_context.parent_span_id`, and error status on failed events.

**NOT in scope**: integration with YAML loader (TASK-1196), webhook subscriber (TASK-1192).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/opentelemetry.py` | CREATE | `OpenTelemetrySubscriber` provider with lazy imports. |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Add `extras_require['otel']` (or `[project.optional-dependencies]` equivalent in PEP 621 format). |
| `packages/ai-parrot/tests/unit/events/lifecycle/test_opentelemetry_subscriber.py` | CREATE | Span creation + parent/child + error-status tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# At module top-level — NO opentelemetry imports here.
from typing import TYPE_CHECKING, Optional, Any, Dict

from parrot.core.events.lifecycle.base import LifecycleEvent     # TASK-1183
from parrot.core.events.lifecycle.trace import TraceContext      # TASK-1182
from parrot.core.events.lifecycle.events import (
    BeforeInvokeEvent, AfterInvokeEvent, InvokeFailedEvent,
    BeforeClientCallEvent, AfterClientCallEvent, ClientCallFailedEvent,
    BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent,
)

if TYPE_CHECKING:
    from parrot.core.events.lifecycle.registry import EventRegistry
    from opentelemetry.trace import Tracer
```

### Existing pyproject.toml structure

```bash
# Verify the current pyproject.toml uses PEP 621 [project.optional-dependencies]
grep -nA5 'optional-dependencies\|extras_require' packages/ai-parrot/pyproject.toml
```

Use whichever form is already present (PEP 621 prefers `[project.optional-dependencies]`).

### Does NOT Exist

- ~~`opentelemetry` as a core dep~~ — it's optional, lives under the `otel` extra.
- ~~Auto-detection of an existing tracer~~ — for now, the subscriber gets its own `TracerProvider` if none is configured globally. Document that users who already configured an `OTLPSpanExporter` will share the same TracerProvider automatically.

---

## Implementation Notes

### Lazy import + clear error message

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/opentelemetry.py
class OpenTelemetrySubscriber:
    def __init__(self, *, service_name: str = "parrot", endpoint: Optional[str] = None) -> None:
        try:
            from opentelemetry import trace
            from opentelemetry.trace import Tracer, Status, StatusCode
        except ImportError as exc:
            raise ImportError(
                "OpenTelemetrySubscriber requires the 'otel' extra. "
                "Install with: pip install 'ai-parrot[otel]'"
            ) from exc
        self._service_name = service_name
        self._tracer: "Tracer" = trace.get_tracer(__name__)
        # Map span_id (hex) → live span context manager for cleanup symmetry
        self._active_spans: Dict[str, Any] = {}
```

### Mapping rules

For each `Before*` event:
- Build an OTel `SpanContext` from `event.trace_context` (use the `trace_id` and `parent_span_id` to set a parent context if present).
- Open a span named after the event's domain: `agent.invoke`, `client.{client_name}.call`, `tool.{tool_name}.execute`.
- Set attributes from the event's fields (`agent_name`, `method`, `model`, `tool_name`, etc.).
- Store the span keyed by `event.trace_context.span_id`.

For each matching `After*` event:
- Pop the span by `event.trace_context.span_id`.
- Set OK status.
- Call `.end()`.

For each `*Failed` event:
- Pop the span by `event.trace_context.span_id`.
- Set ERROR status with the error_type/error_message attributes.
- Call `.end()`.

### `register()` method

```python
def register(self, registry: "EventRegistry") -> None:
    registry.subscribe(BeforeInvokeEvent, self._on_invoke_start)
    registry.subscribe(AfterInvokeEvent, self._on_invoke_end)
    registry.subscribe(InvokeFailedEvent, self._on_invoke_fail)
    registry.subscribe(BeforeClientCallEvent, self._on_client_start)
    registry.subscribe(AfterClientCallEvent, self._on_client_end)
    registry.subscribe(ClientCallFailedEvent, self._on_client_fail)
    registry.subscribe(BeforeToolCallEvent, self._on_tool_start)
    registry.subscribe(AfterToolCallEvent, self._on_tool_end)
    registry.subscribe(ToolCallFailedEvent, self._on_tool_fail)
```

### Parent context wiring

OTel's API to set a parent context from a remote `trace_id`/`span_id` pair:

```python
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, set_span_in_context

def _otel_parent_context(self, tc):
    if tc.parent_span_id is None:
        return None  # root span
    parent_sc = SpanContext(
        trace_id=int(tc.trace_id, 16),
        span_id=int(tc.parent_span_id, 16),
        is_remote=False,
        trace_flags=TraceFlags(tc.trace_flags),
    )
    return set_span_in_context(NonRecordingSpan(parent_sc))
```

### pyproject.toml addition

Inspect current format first. For PEP 621:

```toml
[project.optional-dependencies]
otel = [
  "opentelemetry-api>=1.25",
  "opentelemetry-sdk>=1.25",
]
```

For legacy setuptools format:

```toml
extras_require = {
  "otel": ["opentelemetry-api>=1.25", "opentelemetry-sdk>=1.25"],
}
```

The implementer should use whichever pattern matches the existing pyproject.toml's other extras.

### Key Constraints

- NO `opentelemetry` imports at module top-level — defer inside `__init__` and methods.
- The subscriber must work standalone without a globally configured TracerProvider (creates its own if none exists).
- `register()` is sync.
- Don't pin a max version (Q10 in spec §8 is still open — leave room to tighten later).

---

## Acceptance Criteria

- [ ] `OpenTelemetrySubscriber` defined; conforms to `EventProvider` Protocol.
- [ ] `pip install -e ".[otel]"` installs `opentelemetry-api>=1.25` and `opentelemetry-sdk>=1.25`.
- [ ] Importing the subscriber WITHOUT the extra works; calling `OpenTelemetrySubscriber()` raises `ImportError` with the exact-form message.
- [ ] With the extra installed, `BeforeInvokeEvent` opens an OTel span; `AfterInvokeEvent` closes it.
- [ ] `InvokeFailedEvent` closes the span with ERROR status and `error_type` / `error_message` attributes.
- [ ] An event whose `trace_context.parent_span_id` is set produces a child span in the export.
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_opentelemetry_subscriber.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/opentelemetry.py` is clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/events/lifecycle/test_opentelemetry_subscriber.py
import pytest

otel = pytest.importorskip("opentelemetry.sdk.trace")
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from parrot.core.events.lifecycle.registry import EventRegistry
from parrot.core.events.lifecycle.events import (
    BeforeInvokeEvent, AfterInvokeEvent, InvokeFailedEvent,
)
from parrot.core.events.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.subscribers.opentelemetry import OpenTelemetrySubscriber


@pytest.fixture
def exporter():
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    otel_trace.set_tracer_provider(provider)
    yield exp
    exp.clear()


class TestOpenTelemetrySubscriber:
    @pytest.mark.asyncio
    async def test_before_after_creates_span(self, exporter):
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(OpenTelemetrySubscriber(service_name="test"))
        ctx = TraceContext.new_root()
        await reg.emit(BeforeInvokeEvent(trace_context=ctx, agent_name="a", method="ask"))
        await reg.emit(AfterInvokeEvent(trace_context=ctx, agent_name="a", method="ask"))
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.status_code == StatusCode.OK

    @pytest.mark.asyncio
    async def test_failed_sets_error_status(self, exporter):
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(OpenTelemetrySubscriber())
        ctx = TraceContext.new_root()
        await reg.emit(BeforeInvokeEvent(trace_context=ctx, agent_name="a"))
        await reg.emit(InvokeFailedEvent(
            trace_context=ctx, agent_name="a",
            error_type="ValueError", error_message="bad",
        ))
        spans = exporter.get_finished_spans()
        assert spans[0].status.status_code == StatusCode.ERROR

    def test_no_otel_raises_clear_importerror(self, monkeypatch):
        # Simulate the extra not installed by stubbing the import.
        import sys
        monkeypatch.setitem(sys.modules, "opentelemetry", None)
        with pytest.raises(ImportError, match="ai-parrot\\[otel\\]"):
            OpenTelemetrySubscriber()
```

---

## Agent Instructions

1. Read spec §3 Module 10 and §7 Lazy imports.
2. Confirm TASK-1184 is in `sdd/tasks/completed/`.
3. Inspect `packages/ai-parrot/pyproject.toml` to learn the extras format.
4. Implement, run tests with `pip install -e ".[otel]"` first (or the equivalent uv command), update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-15
**Notes**: OpenTelemetrySubscriber with lazy imports, registers 9 subscriptions, tracer_provider kwarg added for test isolation (OTel only allows one global TracerProvider per process). pyproject.toml otel extra added. 9/9 tests pass. Ruff clean.

**Deviations from spec**: Added optional `tracer_provider` kwarg to `__init__` for test isolation (OTel's `set_tracer_provider` can only be called once; the spec doesn't mention this constraint but it's necessary for unit test isolation without global state conflicts).

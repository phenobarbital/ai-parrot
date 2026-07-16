---
type: Wiki Entity
title: TraceContext
id: class:parrot.core.events.lifecycle.trace.TraceContext
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: W3C Trace Context for OpenTelemetry-compatible distributed tracing.
---

# TraceContext

Defined in [`parrot.core.events.lifecycle.trace`](../summaries/mod:parrot.core.events.lifecycle.trace.md).

```python
class TraceContext
```

W3C Trace Context for OpenTelemetry-compatible distributed tracing.

Carries trace identity across agent → client → tool → sub-agent (A2A)
boundaries. All fields are immutable (frozen=True); mutation raises
FrozenInstanceError.

Attributes:
    trace_id: 32 hex chars (16 bytes) uniquely identifying the trace.
    span_id: 16 hex chars (8 bytes) identifying this span.
    trace_flags: Bit field. Bit 0 = sampled (default 1 = sampled).
    trace_state: Vendor extension string (W3C tracestate header value).
    parent_span_id: span_id of the parent span, or None for root spans.

Example:
    >>> root = TraceContext.new_root()
    >>> child = root.child()
    >>> child.trace_id == root.trace_id
    True
    >>> child.parent_span_id == root.span_id
    True

## Methods

- `def new_root(cls) -> 'TraceContext'` — Create a new root TraceContext (no parent).
- `def child(self) -> 'TraceContext'` — Return a new child context derived from this span.
- `def from_traceparent_header(cls, header: str) -> 'TraceContext'` — Parse a W3C traceparent header string into a TraceContext.
- `def to_traceparent_header(self) -> str` — Serialize to a W3C traceparent header string.
- `def to_dict(self) -> dict` — Serialize all fields to a JSON-compatible dict.
- `def from_dict(cls, data: dict) -> 'TraceContext'` — Reconstruct a TraceContext from a dict (e.g., from ``to_dict()``).

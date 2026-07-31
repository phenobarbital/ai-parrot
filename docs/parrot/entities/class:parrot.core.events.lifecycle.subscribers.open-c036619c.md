---
type: Wiki Entity
title: OpenTelemetrySubscriber
id: class:parrot.core.events.lifecycle.subscribers.opentelemetry.OpenTelemetrySubscriber
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: EventProvider that maps lifecycle events to OpenTelemetry spans.
---

# OpenTelemetrySubscriber

Defined in [`parrot.core.events.lifecycle.subscribers.opentelemetry`](../summaries/mod:parrot.core.events.lifecycle.subscribers.opentelemetry.md).

```python
class OpenTelemetrySubscriber
```

EventProvider that maps lifecycle events to OpenTelemetry spans.

Each ``Before*`` event opens a span; the matching ``After*`` or ``*Failed``
event closes it.  The ``TraceContext.parent_span_id`` is used to set the
parent span context so spans nest correctly in distributed traces.

Requires the ``otel`` extra:  ``pip install 'ai-parrot[otel]'``

Note:
    This subscriber should be registered on only one registry per process
    to avoid concurrent access across event loops.  The internal
    ``_active_spans`` dict is protected by an ``asyncio.Lock``; however,
    sharing the same instance across multiple independently-running event
    loops is not supported.

Args:
    service_name: Name used to identify the tracer (default ``"parrot"``).
    endpoint: Optional OTel collector endpoint.  When ``None``, the
        currently configured ``TracerProvider`` is used (falls back to the
        no-op provider if none is configured).
    tracer_provider: Optional ``TracerProvider`` instance.  Pass this in
        tests to avoid global-state conflicts from ``set_tracer_provider()``.
        When ``None`` (default), the global provider is used.

## Methods

- `def register(self, registry: 'EventRegistry') -> None` — Register all Before/After/Failed subscribers with *registry*.

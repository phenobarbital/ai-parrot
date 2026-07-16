---
type: Wiki Entity
title: GenAIOpenTelemetrySubscriber
id: class:parrot.observability.subscribers.trace.GenAIOpenTelemetrySubscriber
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Rich OTel span subscriber implementing GenAI Semantic Conventions.
---

# GenAIOpenTelemetrySubscriber

Defined in [`parrot.observability.subscribers.trace`](../summaries/mod:parrot.observability.subscribers.trace.md).

```python
class GenAIOpenTelemetrySubscriber
```

Rich OTel span subscriber implementing GenAI Semantic Conventions.

Subscribes to 12 FEAT-176 lifecycle event classes and maps them to OTel
spans. Use ``register(registry)`` to attach to an ``EventRegistry``.

This class is distinct from FEAT-176's ``OpenTelemetrySubscriber`` stub,
which it coexists with. Never rename it to ``OpenTelemetrySubscriber``.

Args:
    service_name: Used as the OTel tracer name / ``service.name``.
    tracer_provider: Optional pre-built OTel ``TracerProvider``. When
        ``None``, the global provider is used.
    cost_calculator: Optional ``CostCalculator`` for attaching USD cost
        to ``AfterClientCallEvent`` spans and span attributes.
    capture_completions: When ``True``, each ``ClientStreamChunkEvent``
        adds a span *event* to the active span. Default ``False`` (PII).

## Methods

- `def register(self, registry: 'EventRegistry') -> None` — Subscribe all handlers to *registry*.

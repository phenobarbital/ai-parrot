---
type: Wiki Entity
title: ParrotTelemetryProvider
id: class:parrot.observability.provider.ParrotTelemetryProvider
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Bundles trace + metrics subscribers for one-call registration.
---

# ParrotTelemetryProvider

Defined in [`parrot.observability.provider`](../summaries/mod:parrot.observability.provider.md).

```python
class ParrotTelemetryProvider
```

Bundles trace + metrics subscribers for one-call registration.

Either subscriber may be ``None`` (e.g., trace-only or metrics-only
deployments). If both are ``None``, ``register`` is a no-op.

Implements the ``EventProvider`` Protocol (``provider.py:45``): the
``register`` method is synchronous.

Args:
    trace_subscriber: Optional ``GenAIOpenTelemetrySubscriber``.
    metrics_subscriber: Optional ``MetricsSubscriber``.

## Methods

- `def register(self, registry: 'EventRegistry') -> None` — Register all non-None subscribers with *registry*.

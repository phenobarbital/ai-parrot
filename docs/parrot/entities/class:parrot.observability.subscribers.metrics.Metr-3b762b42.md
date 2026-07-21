---
type: Wiki Entity
title: MetricsSubscriber
id: class:parrot.observability.subscribers.metrics.MetricsSubscriber
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: OTel counter and histogram subscriber for LLM / tool / invoke events.
---

# MetricsSubscriber

Defined in [`parrot.observability.subscribers.metrics`](../summaries/mod:parrot.observability.subscribers.metrics.md).

```python
class MetricsSubscriber
```

OTel counter and histogram subscriber for LLM / tool / invoke events.

Implements ``EventProvider`` Protocol: ``register(registry)`` is
synchronous per provider.py:45.

``ClientStreamChunkEvent`` is NEVER subscribed — chunks must not update
metrics (fire-and-forget streaming path; cardinality guard).

Args:
    meter_provider: Optional pre-built OTel ``MeterProvider``. When
        ``None``, the global provider is used.
    service_name: Used as the OTel meter name / ``service.name``.
    histogram_buckets: Override the default LLM-tuned bucket boundaries
        (seconds). When ``None``, uses ``_DEFAULT_BUCKETS``.
    cost_calculator: Optional ``CostCalculator`` for ``gen_ai.client.cost.total``.

## Methods

- `def buckets(self) -> list[float]` — Return the histogram bucket boundaries (seconds).
- `def register(self, registry: 'EventRegistry') -> None` — Subscribe all metric handlers to *registry*.

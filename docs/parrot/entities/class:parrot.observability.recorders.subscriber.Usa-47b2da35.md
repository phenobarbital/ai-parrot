---
type: Wiki Entity
title: UsageRecordingSubscriber
id: class:parrot.observability.recorders.subscriber.UsageRecordingSubscriber
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build ``UsageRecord``s from LLM-call events and fan out to recorders.
---

# UsageRecordingSubscriber

Defined in [`parrot.observability.recorders.subscriber`](../summaries/mod:parrot.observability.recorders.subscriber.md).

```python
class UsageRecordingSubscriber
```

Build ``UsageRecord``s from LLM-call events and fan out to recorders.

Args:
    recorders: The pluggable backends to forward each record to.
    cost_calculator: Optional ``CostCalculator``; when provided, the per-call
        and cumulative USD cost are computed.
    service_name: ``service.name`` stamped on each record.

## Methods

- `def recorders(self) -> 'list[AbstractLogger]'` — The configured recorder backends.
- `def register(self, registry: 'EventRegistry') -> None` — Subscribe the usage handler to *registry*.
- `async def aclose(self) -> None` — Close all recorders (flush stateful backends).

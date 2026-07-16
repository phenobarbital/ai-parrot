---
type: Wiki Entity
title: StoreScore
id: class:parrot.registry.routing.models.StoreScore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: One ranked store entry within a ``StoreRoutingDecision``.
---

# StoreScore

Defined in [`parrot.registry.routing.models`](../summaries/mod:parrot.registry.routing.models.md).

```python
class StoreScore(BaseModel)
```

One ranked store entry within a ``StoreRoutingDecision``.

Args:
    store: The store type.
    confidence: Routing confidence in ``[0.0, 1.0]``.
    reason: Human-readable explanation for the score.

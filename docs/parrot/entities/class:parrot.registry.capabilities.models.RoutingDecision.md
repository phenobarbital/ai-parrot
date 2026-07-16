---
type: Wiki Entity
title: RoutingDecision
id: class:parrot.registry.capabilities.models.RoutingDecision
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: The router's selected strategy and candidates.
---

# RoutingDecision

Defined in [`parrot.registry.capabilities.models`](../summaries/mod:parrot.registry.capabilities.models.md).

```python
class RoutingDecision(BaseModel)
```

The router's selected strategy and candidates.

Args:
    routing_type: Primary routing strategy selected.
    candidates: Top-K registry candidates that influenced the decision.
    cascades: Ordered list of fallback strategies if primary fails.
    confidence: Confidence score in [0.0, 1.0].
    reasoning: LLM explanation for the routing choice.

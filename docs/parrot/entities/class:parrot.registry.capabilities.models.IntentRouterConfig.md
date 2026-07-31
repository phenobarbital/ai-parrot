---
type: Wiki Entity
title: IntentRouterConfig
id: class:parrot.registry.capabilities.models.IntentRouterConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for the IntentRouter.
---

# IntentRouterConfig

Defined in [`parrot.registry.capabilities.models`](../summaries/mod:parrot.registry.capabilities.models.md).

```python
class IntentRouterConfig(BaseModel)
```

Configuration for the IntentRouter.

Args:
    confidence_threshold: Minimum confidence to accept a route (0.0–1.0).
    hitl_threshold: Below this confidence, ask the human for clarification.
    strategy_timeout_s: Per-strategy timeout in seconds (must be > 0).
    exhaustive_mode: When True, run all strategies and concatenate results.
    max_cascades: Maximum number of cascade fallback steps before FALLBACK.
    custom_keywords: Extra keyword→strategy mappings merged on top of the
        built-in ``_KEYWORD_STRATEGY_MAP``.  Keys are lowercase keyword
        phrases; values are ``RoutingType`` values (as strings or enum
        members).  Example::

            custom_keywords={
                "pricing": "graph_pageindex",
                "stock level": "dataset",
            }

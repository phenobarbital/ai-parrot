---
type: Wiki Entity
title: StoreFallbackPolicy
id: class:parrot.registry.routing.models.StoreFallbackPolicy
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: What the router does when no store scores above ``confidence_floor``.
---

# StoreFallbackPolicy

Defined in [`parrot.registry.routing.models`](../summaries/mod:parrot.registry.routing.models.md).

```python
class StoreFallbackPolicy(str, Enum)
```

What the router does when no store scores above ``confidence_floor``.

Attributes:
    FAN_OUT: Delegate to ``MultiStoreSearchTool._execute()`` for parallel
        fan-out across all configured stores + BM25 reranking.
    FIRST_AVAILABLE: Use the first configured store in insertion order.
    EMPTY: Return an empty result list without raising.
    RAISE: Raise ``NoSuitableStoreError``.

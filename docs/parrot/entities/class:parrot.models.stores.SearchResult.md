---
type: Wiki Entity
title: SearchResult
id: class:parrot.models.stores.SearchResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Data model for a single document returned from a vector search.
---

# SearchResult

Defined in [`parrot.models.stores`](../summaries/mod:parrot.models.stores.md).

```python
class SearchResult(BaseModel)
```

Data model for a single document returned from a vector search.

``score`` carries the raw value produced by the configured vector-store
metric (e.g. L2 / cosine distance / negative inner product). For
distance-based metrics (the common case) **lower means closer**. The
same value is also serialised as ``distance`` via a computed alias so
API consumers can use the unambiguous name without any input changes
on the producer side.

## Methods

- `def distance(self) -> float` — Alias for :attr:`score` — same value, unambiguous name.

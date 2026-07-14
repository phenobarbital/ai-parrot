---
type: Wiki Entity
title: DataSource
id: class:parrot.tools.dataset_manager.sources.base.DataSource
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base for all data sources.
---

# DataSource

Defined in [`parrot.tools.dataset_manager.sources.base`](../summaries/mod:parrot.tools.dataset_manager.sources.base.md).

```python
class DataSource(ABC)
```

Abstract base for all data sources.

A DataSource is a reference to data. It knows how to prefetch schema,
fetch actual data, describe itself to the LLM, and provide a stable
cache key for Redis.

Subclasses must implement:
    - fetch(**params) -> pd.DataFrame
    - describe() -> str
    - cache_key (property) -> str

Subclasses may optionally override:
    - prefetch_schema() -> Dict[str, str]

Attributes:
    routing_meta: Optional dict of routing hints for CapabilityRegistry.
        Supported keys:
        - ``"description"``: overrides describe() for embedding.
        - ``"not_for"``: list of query patterns to avoid.
        Example: ``{"description": "Q1 sales", "not_for": ["HR"]}``

## Methods

- `async def prefetch_schema(self) -> Dict[str, str]` — Return column-to-type mapping without fetching any rows.
- `async def fetch(self, **params) -> pd.DataFrame` — Execute and return a DataFrame.
- `def describe(self) -> str` — Return a human-readable description for the LLM guide.
- `def has_builtin_cache(self) -> bool` — Whether this source manages its own caching internally.
- `def cache_key(self) -> str` — Stable, unique string for Redis keying.

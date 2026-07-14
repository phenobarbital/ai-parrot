---
type: Wiki Entity
title: InMemorySource
id: class:parrot.tools.dataset_manager.sources.memory.InMemorySource
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Wraps an already-loaded pd.DataFrame as a DataSource.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.base.DataSource
  rel: extends
---

# InMemorySource

Defined in [`parrot.tools.dataset_manager.sources.memory`](../summaries/mod:parrot.tools.dataset_manager.sources.memory.md).

```python
class InMemorySource(DataSource)
```

Wraps an already-loaded pd.DataFrame as a DataSource.

Args:
    df: The DataFrame to wrap.
    name: Logical name used as the cache key suffix.

## Methods

- `async def prefetch_schema(self) -> Dict[str, str]` — Return column-to-type mapping derived from df.dtypes (no I/O).
- `async def fetch(self, **params) -> pd.DataFrame` — Return the wrapped DataFrame unchanged.
- `def describe(self) -> str` — Return a human-readable description for the LLM.
- `def cache_key(self) -> str` — Stable cache key for Redis keying.

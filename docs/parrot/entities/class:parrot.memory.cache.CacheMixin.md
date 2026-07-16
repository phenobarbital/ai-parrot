---
type: Wiki Entity
title: CacheMixin
id: class:parrot.memory.cache.CacheMixin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mixin to add caching capabilities using Redis.
---

# CacheMixin

Defined in [`parrot.memory.cache`](../summaries/mod:parrot.memory.cache.md).

```python
class CacheMixin(ABC)
```

Mixin to add caching capabilities using Redis.

## Methods

- `async def get(self, query_type: str, **params) -> Optional[Any]` — Get a cached value from Redis based on the query type and parameters.
- `async def set(self, query_type: str, value: Any, ttl: Optional[int]=None, **params)` — Save result to cache with TTL (async).
- `async def invalidate_cache(self, object_oid: str)` — Invalidate cache related to an object (async).
- `async def clear_all(self)` — Clear all hierarchy cache (async).

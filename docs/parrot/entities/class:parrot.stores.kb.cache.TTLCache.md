---
type: Wiki Entity
title: TTLCache
id: class:parrot.stores.kb.cache.TTLCache
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Thread-safe TTL cache with memory management.
---

# TTLCache

Defined in [`parrot.stores.kb.cache`](../summaries/mod:parrot.stores.kb.cache.md).

```python
class TTLCache
```

Thread-safe TTL cache with memory management.

## Methods

- `async def start(self)` — Start the cleanup background task.
- `async def stop(self)` — Stop the cleanup task.
- `async def get(self, key: str, default: Any=None) -> Optional[Any]` — Get value from cache.
- `async def set(self, key: str, value: Any, ttl: Optional[int]=None)` — Set value in cache with TTL.
- `async def invalidate(self, pattern: str=None)` — Invalidate cache entries matching pattern.
- `def get_stats(self) -> Dict[str, Any]` — Get cache statistics.

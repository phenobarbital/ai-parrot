---
type: Wiki Entity
title: ToolCache
id: class:parrot_tools.cache.ToolCache
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Redis-backed cache for tool/toolkit API responses.
---

# ToolCache

Defined in [`parrot_tools.cache`](../summaries/mod:parrot_tools.cache.md).

```python
class ToolCache
```

Redis-backed cache for tool/toolkit API responses.

Generates deterministic cache keys from tool name, method, and
call parameters so that identical queries are served from Redis
instead of hitting external APIs.

Attributes:
    prefix: Key prefix used in Redis to namespace tool cache entries.
    ttl: Default time-to-live in seconds for cached values.

## Methods

- `async def get(self, tool_name: str, method: str, **params) -> Optional[Any]` — Retrieve a cached value if it exists and has not expired.
- `async def set(self, tool_name: str, method: str, value: Any, ttl: Optional[int]=None, **params) -> None` — Store a value in the cache with a TTL.
- `async def close(self) -> None` — Close the underlying Redis connection.

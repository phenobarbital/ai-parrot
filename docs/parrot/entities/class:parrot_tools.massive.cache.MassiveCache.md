---
type: Wiki Entity
title: MassiveCache
id: class:parrot_tools.massive.cache.MassiveCache
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Cache layer for MassiveToolkit with per-endpoint TTLs.
---

# MassiveCache

Defined in [`parrot_tools.massive.cache`](../summaries/mod:parrot_tools.massive.cache.md).

```python
class MassiveCache
```

Cache layer for MassiveToolkit with per-endpoint TTLs.

Wraps the existing ToolCache infrastructure to provide endpoint-aware
caching with appropriate TTLs based on data freshness requirements.

Usage:
    cache = MassiveCache()

    # Check cache before API call
    cached = await cache.get("options_chain", underlying="AAPL")
    if cached:
        return cached

    # Store result after API call
    await cache.set("options_chain", result, underlying="AAPL")

## Methods

- `def get_ttl(self, endpoint: str) -> int` — Get the TTL for a specific endpoint.
- `async def get(self, endpoint: str, **params) -> dict | None` — Get cached result for endpoint with given parameters.
- `async def set(self, endpoint: str, data: dict, ttl: int | None=None, **params) -> None` — Cache result with endpoint-specific TTL.
- `async def invalidate(self, endpoint: str, **params) -> bool` — Invalidate a specific cache entry.
- `async def invalidate_endpoint(self, endpoint: str) -> int` — Invalidate all cache entries for an endpoint.
- `async def close(self) -> None` — Close the underlying cache connection.

---
type: Wiki Entity
title: FormCache
id: class:parrot_formdesigner.services.cache.FormCache
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: In-memory TTL cache for FormSchema with optional Redis backend.
---

# FormCache

Defined in [`parrot_formdesigner.services.cache`](../summaries/mod:parrot_formdesigner.services.cache.md).

```python
class FormCache
```

In-memory TTL cache for FormSchema with optional Redis backend.

Supports:
- In-memory cache with per-entry TTL expiration
- Optional Redis backend for distributed/multi-process caching
- Async-safe with asyncio.Lock
- Invalidation callbacks for downstream notification

Example:
    cache = FormCache(ttl_seconds=3600)
    await cache.set(form_schema)
    form = await cache.get("my-form")

    # With Redis
    cache = FormCache(ttl_seconds=3600, redis_url="redis://localhost:6379")
    await cache.set(form_schema)

## Methods

- `async def get(self, form_id: str) -> FormSchema | None` — Retrieve a form from cache.
- `async def set(self, form: FormSchema) -> None` — Store a form in cache.
- `async def invalidate(self, form_id: str) -> None` — Remove a form from cache.
- `async def invalidate_all(self) -> None` — Clear all forms from cache.
- `def on_invalidate(self, callback: Callable[[str], Awaitable[None]]) -> None` — Register a callback for invalidation events.
- `async def size(self) -> int` — Return number of currently cached (unexpired) forms.
- `async def close(self) -> None` — Close the Redis connection if open.

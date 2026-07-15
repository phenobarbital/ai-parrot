---
type: Wiki Entity
title: OptionsLoader
id: class:parrot_formdesigner.services.options_loader.OptionsLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Async service that fetches and caches ``FieldOption`` lists.
---

# OptionsLoader

Defined in [`parrot_formdesigner.services.options_loader`](../summaries/mod:parrot_formdesigner.services.options_loader.md).

```python
class OptionsLoader
```

Async service that fetches and caches ``FieldOption`` lists.

Uses ``aiohttp.ClientSession`` for all HTTP requests. Auth headers are
resolved via ``AuthContext.resolve_for(source.auth_ref)`` if an auth
context is provided.

Caching: in-memory dict keyed by ``(source_ref, auth_ref)`` with per-entry
expiry timestamps derived from ``OptionsSource.cache_ttl_seconds``.

Single-flight: concurrent calls for the same cache key share exactly one
in-flight HTTP request via ``asyncio.Event`` + result sharing.

Args:
    timeout: Request timeout in seconds. Defaults to ``DEFAULT_TIMEOUT``.

## Methods

- `async def fetch(self, source: OptionsSource, *, auth_context: AuthContext | None=None) -> list[FieldOption]` — Fetch and normalise options from the given ``OptionsSource``.
- `def invalidate(self, source_ref: str, auth_ref: str | None=None) -> None` — Remove a specific cache entry.
- `def clear_cache(self) -> None` — Clear all cached option lists.

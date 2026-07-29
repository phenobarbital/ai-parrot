---
type: Wiki Summary
title: parrot.memory.cache
id: mod:parrot.memory.cache
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.memory.cache
relates_to:
- concept: class:parrot.memory.cache.CacheMixin
  rel: defines
- concept: func:parrot.memory.cache.cached_query
  rel: defines
- concept: mod:parrot.conf
  rel: references
---

# `parrot.memory.cache`

## Classes

- **`CacheMixin(ABC)`** — Mixin to add caching capabilities using Redis.

## Functions

- `def cached_query(query_type: str, ttl: Optional[int]=None) -> Callable[[Callable[P, asyncio.Future[T]]], Callable[P, asyncio.Future[T]]]` — Decorator to cache the result of async methods in classes

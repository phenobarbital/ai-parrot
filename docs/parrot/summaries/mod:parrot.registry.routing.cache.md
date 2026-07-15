---
type: Wiki Summary
title: parrot.registry.routing.cache
id: mod:parrot.registry.routing.cache
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Asyncio-safe LRU cache for store routing decisions (FEAT-111 Module 6).
relates_to:
- concept: class:parrot.registry.routing.cache.DecisionCache
  rel: defines
- concept: func:parrot.registry.routing.cache.build_cache_key
  rel: defines
- concept: mod:parrot.registry.routing.models
  rel: references
---

# `parrot.registry.routing.cache`

Asyncio-safe LRU cache for store routing decisions (FEAT-111 Module 6).

``functools.lru_cache`` silently misbehaves on async methods — it caches the
coroutine object instead of the awaited result.  This module provides a small
``asyncio.Lock``-guarded LRU implemented over ``collections.OrderedDict``.

Usage::

    from parrot.registry.routing import DecisionCache, build_cache_key

    cache = DecisionCache(maxsize=256)
    key = build_cache_key(query, ("pgvector", "arango"))
    decision = await cache.get(key)
    if decision is None:
        decision = ... # compute it
        await cache.put(key, decision)

## Classes

- **`DecisionCache`** — Asyncio-safe LRU cache for :class:`~parrot.registry.routing.StoreRoutingDecision`.

## Functions

- `def build_cache_key(query: str, store_fingerprint: tuple[str, ...]) -> str` — Build a stable, compact cache key.

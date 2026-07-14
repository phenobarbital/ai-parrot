---
type: Wiki Entity
title: DecisionCache
id: class:parrot.registry.routing.cache.DecisionCache
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Asyncio-safe LRU cache for :class:`~parrot.registry.routing.StoreRoutingDecision`.
---

# DecisionCache

Defined in [`parrot.registry.routing.cache`](../summaries/mod:parrot.registry.routing.cache.md).

```python
class DecisionCache
```

Asyncio-safe LRU cache for :class:`~parrot.registry.routing.StoreRoutingDecision`.

Uses :class:`collections.OrderedDict` + :class:`asyncio.Lock` to provide
a thread/coroutine-safe LRU without requiring ``functools.lru_cache`` (which
does not work correctly with async methods).

.. note::
    Returned ``StoreRoutingDecision`` objects are **not** deep-copied.
    Callers must not mutate them.

Args:
    maxsize: Maximum number of entries.  ``0`` disables the cache (all
        ``get`` calls return ``None``; ``put`` calls are no-ops).

## Methods

- `async def get(self, key: str) -> Optional[StoreRoutingDecision]` — Retrieve *key* from the cache, promoting it to MRU position.
- `async def put(self, key: str, decision: StoreRoutingDecision) -> None` — Store *decision* under *key*, evicting the LRU entry if needed.

---
type: Wiki Entity
title: InMemoryStateStore
id: class:parrot.integrations.core.state.InMemoryStateStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Simple in-memory key-value store with TTL support.
---

# InMemoryStateStore

Defined in [`parrot.integrations.core.state`](../summaries/mod:parrot.integrations.core.state.md).

```python
class InMemoryStateStore
```

Simple in-memory key-value store with TTL support.

Used as a fallback when no persistent store (e.g., Redis) is available.

.. warning::
    **Memory leak risk** — this store holds all keys in memory indefinitely
    unless they are explicitly deleted or their TTL is checked on access.
    Entries with an ``expire`` value are evicted lazily on ``get()`` and
    swept proactively (via :meth:`_sweep_expired`) whenever the store
    exceeds ``_SWEEP_THRESHOLD`` entries.  For production workloads with
    high message volumes, replace this with a real Redis-backed store.

## Methods

- `async def set(self, key: str, value: str, expire: int=0) -> None`
- `async def get(self, key: str) -> Optional[str]`
- `async def delete(self, key: str) -> None`

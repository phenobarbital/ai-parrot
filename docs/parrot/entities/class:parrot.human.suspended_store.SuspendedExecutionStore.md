---
type: Wiki Entity
title: SuspendedExecutionStore
id: class:parrot.human.suspended_store.SuspendedExecutionStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Redis-backed store for :class:`SuspendedExecution` blobs.
---

# SuspendedExecutionStore

Defined in [`parrot.human.suspended_store`](../summaries/mod:parrot.human.suspended_store.md).

```python
class SuspendedExecutionStore
```

Redis-backed store for :class:`SuspendedExecution` blobs.

Key format: ``hitl:suspended:{interaction_id}``

TTL is caller-provided (use
:meth:`~parrot.human.manager.HumanInteractionManager._compute_ttl` so
the suspended blob expires coherently with the interaction).

The ``delete`` method removes ONLY the suspended key — ``hitl:interaction:{id}``
is deliberately left intact (escalation seam; TTL-owned expiry).

Args:
    redis: An ``redis.asyncio`` client (``decode_responses=True`` recommended).

Example::

    store = SuspendedExecutionStore(redis_client)
    await store.save(record, ttl=7260)
    loaded = await store.load(record.interaction_id)
    await store.delete(record.interaction_id)

## Methods

- `async def save(self, record: SuspendedExecution, ttl: int) -> None` — Persist a suspended-execution record to Redis with TTL.
- `async def load(self, interaction_id: str) -> Optional[SuspendedExecution]` — Load a suspended-execution record from Redis.
- `async def delete(self, interaction_id: str) -> None` — Remove the suspended-execution key from Redis.

---
type: Wiki Entity
title: RedisEventDeduplicator
id: class:parrot.integrations.slack.dedup.RedisEventDeduplicator
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Redis-backed deduplication for multi-instance deployments.
---

# RedisEventDeduplicator

Defined in [`parrot.integrations.slack.dedup`](../summaries/mod:parrot.integrations.slack.dedup.md).

```python
class RedisEventDeduplicator
```

Redis-backed deduplication for multi-instance deployments.

Uses Redis SET NX with TTL for atomic deduplication across
multiple application instances.

Args:
    redis_pool: An async Redis client/pool (aioredis or redis-py async).
    prefix: Key prefix for deduplication keys (default: "slack:dedup:").
    ttl: Time-to-live in seconds (default: 300).

Example:
    >>> import redis.asyncio as redis
    >>> pool = redis.from_url("redis://localhost")
    >>> dedup = RedisEventDeduplicator(pool)
    >>> await dedup.start()
    >>> if not await dedup.is_duplicate("evt_123"):
    ...     # Process the event
    ...     pass
    >>> await dedup.stop()

## Methods

- `async def is_duplicate(self, event_id: Optional[str]) -> bool` — Check if event was seen using Redis SETNX.
- `async def start(self) -> None` — No-op for Redis (connection managed externally).
- `async def stop(self) -> None` — No-op for Redis (connection managed externally).

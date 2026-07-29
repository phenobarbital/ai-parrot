---
type: Wiki Entity
title: RedisResultStorage
id: class:parrot.bots.flows.core.storage.backends.redis.RedisResultStorage
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Persist crew/flow execution results to Redis (one key per execution).
relates_to:
- concept: class:parrot.bots.flows.core.storage.backends.base.ResultStorage
  rel: extends
---

# RedisResultStorage

Defined in [`parrot.bots.flows.core.storage.backends.redis`](../summaries/mod:parrot.bots.flows.core.storage.backends.redis.md).

```python
class RedisResultStorage(ResultStorage)
```

Persist crew/flow execution results to Redis (one key per execution).

Key shape: ``{collection}:{crew_name}:{timestamp_ms}``
Value: JSON-encoded document (with ``default=str`` for non-serialisable fields).
TTL: configurable via constructor or ``CREW_RESULT_STORAGE_REDIS_TTL`` (default 7 days).

## Methods

- `async def save(self, collection: str, document: dict[str, Any]) -> None` — Write one execution record to Redis.
- `async def fetch(self, collection: str, execution_id: str) -> list[dict[str, Any]]` — Return all documents written under *execution_id* in *collection*.
- `async def close(self) -> None` — Release the Redis connection. Safe to call multiple times.
- `async def list(self, collection: str, filters: Optional[dict[str, Any]]=None, limit: int=20, offset: int=0) -> list[dict[str, Any]]` — List execution documents ordered by ``timestamp DESC``.
- `async def get(self, collection: str, record_id: str) -> Optional[dict[str, Any]]` — Retrieve a single execution document by its Redis key.
- `async def delete(self, collection: str, record_id: str) -> bool` — Delete a single execution document by its Redis key.
- `async def count(self, collection: str, filters: Optional[dict[str, Any]]=None) -> int` — Count execution documents matching the given filters.

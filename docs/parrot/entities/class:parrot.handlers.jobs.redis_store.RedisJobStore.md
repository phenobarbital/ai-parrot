---
type: Wiki Entity
title: RedisJobStore
id: class:parrot.handlers.jobs.redis_store.RedisJobStore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Async Redis-backed store for background Job objects.
---

# RedisJobStore

Defined in [`parrot.handlers.jobs.redis_store`](../summaries/mod:parrot.handlers.jobs.redis_store.md).

```python
class RedisJobStore
```

Async Redis-backed store for background Job objects.

Args:
    redis_url: Redis connection URL. Defaults to ``REDIS_SERVICES_URL``
               from ``parrot.conf``.
    key_prefix: Prefix for all Redis keys managed by this store.
    job_ttl: Seconds to keep a terminal job in Redis (default 24 h).

## Methods

- `async def connect(self) -> None` — Open the Redis connection (idempotent, concurrency-safe).
- `async def close(self) -> None` — Close the Redis connection.
- `async def ping(self) -> bool` — Return True if the Redis connection is alive.
- `async def save(self, job: Job) -> None` — Persist a Job to Redis.
- `async def get(self, job_id: str) -> Optional[Job]` — Return the Job for ``job_id``, or ``None`` if not found.
- `async def delete(self, job_id: str) -> bool` — Remove a job from Redis.
- `async def list_jobs(self, obj_id: Optional[str]=None, status: Optional[JobStatus]=None, limit: int=100) -> List[Job]` — Return jobs from Redis, optionally filtered.
- `async def exists(self, job_id: str) -> bool` — Return True if a job with ``job_id`` is currently stored.

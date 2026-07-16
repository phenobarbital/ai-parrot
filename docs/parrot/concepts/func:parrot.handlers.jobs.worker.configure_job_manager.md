---
type: Concept
title: configure_job_manager()
id: func:parrot.handlers.jobs.worker.configure_job_manager
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configure and register a JobManager on the aiohttp Application.
---

# configure_job_manager

```python
def configure_job_manager(app: web.Application, *, use_redis: bool=False, redis_url: Optional[str]=None, key_prefix: str='parrot:jobs', job_ttl: int=86400) -> JobManager
```

Configure and register a JobManager on the aiohttp Application.

Args:
    app: The aiohttp Application instance.
    use_redis: When True, attach a RedisJobStore for durable persistence.
    redis_url: Override Redis connection URL.  Defaults to
        ``REDIS_SERVICES_URL`` from ``parrot.conf``.
    key_prefix: Redis key prefix for all job hashes.
    job_ttl: TTL in seconds for completed/failed jobs in Redis.

Returns:
    The configured JobManager (also stored in ``app['job_manager']``).

Example::

    # Simple in-memory (default)
    configure_job_manager(app)

    # Redis-backed (persistent across restarts)
    configure_job_manager(app, use_redis=True)

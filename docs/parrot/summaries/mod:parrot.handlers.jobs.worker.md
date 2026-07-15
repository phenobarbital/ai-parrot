---
type: Wiki Summary
title: parrot.handlers.jobs.worker
id: mod:parrot.handlers.jobs.worker
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Worker / startup helpers for JobManager configuration.
relates_to:
- concept: func:parrot.handlers.jobs.worker.configure_job_manager
  rel: defines
- concept: mod:parrot.handlers.jobs.job
  rel: references
- concept: mod:parrot.handlers.jobs.redis_store
  rel: references
---

# `parrot.handlers.jobs.worker`

Worker / startup helpers for JobManager configuration.

Provides convenience functions to wire up a ``JobManager`` (with or without
Redis persistence) into an aiohttp ``Application``.

## Functions

- `def configure_job_manager(app: web.Application, *, use_redis: bool=False, redis_url: Optional[str]=None, key_prefix: str='parrot:jobs', job_ttl: int=86400) -> JobManager` — Configure and register a JobManager on the aiohttp Application.

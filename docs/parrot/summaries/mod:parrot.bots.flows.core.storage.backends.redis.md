---
type: Wiki Summary
title: parrot.bots.flows.core.storage.backends.redis
id: mod:parrot.bots.flows.core.storage.backends.redis
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: RedisResultStorage — Redis backend for crew/flow execution results (FEAT-147).
relates_to:
- concept: class:parrot.bots.flows.core.storage.backends.redis.RedisResultStorage
  rel: defines
- concept: mod:parrot.bots.flows.core.storage.backends.base
  rel: references
- concept: mod:parrot.conf
  rel: references
---

# `parrot.bots.flows.core.storage.backends.redis`

RedisResultStorage — Redis backend for crew/flow execution results (FEAT-147).

One key per execution: ``{collection}:{crew_name}:{ts_ms}``, JSON value, optional TTL.

## Classes

- **`RedisResultStorage(ResultStorage)`** — Persist crew/flow execution results to Redis (one key per execution).

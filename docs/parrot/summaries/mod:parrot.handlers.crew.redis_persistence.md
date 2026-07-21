---
type: Wiki Summary
title: parrot.handlers.crew.redis_persistence
id: mod:parrot.handlers.crew.redis_persistence
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Redis Persistence for AgentsCrew Definitions.
relates_to:
- concept: class:parrot.handlers.crew.redis_persistence.CrewRedis
  rel: defines
- concept: func:parrot.handlers.crew.redis_persistence.test_crew_redis
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.handlers.crew.models
  rel: references
---

# `parrot.handlers.crew.redis_persistence`

Redis Persistence for AgentsCrew Definitions.

Provides async-based persistence layer for storing and retrieving
Crew definitions from Redis using JSON serialization.

## Classes

- **`CrewRedis`** — Redis-based persistence for AgentsCrew definitions.

## Functions

- `async def test_crew_redis()` — Test the CrewRedis persistence layer.

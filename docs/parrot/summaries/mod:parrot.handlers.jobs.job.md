---
type: Wiki Summary
title: parrot.handlers.jobs.job
id: mod:parrot.handlers.jobs.job
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Job Manager for Asynchronous Crew Execution.
relates_to:
- concept: class:parrot.handlers.jobs.job.JobManager
  rel: defines
- concept: mod:parrot.handlers.jobs.models
  rel: references
- concept: mod:parrot.handlers.jobs.redis_store
  rel: references
---

# `parrot.handlers.jobs.job`

Job Manager for Asynchronous Crew Execution.

Manages async execution of AgentCrew operations with job tracking,
status monitoring, and result retrieval.

When a ``RedisJobStore`` is provided at construction time the manager mirrors
every job mutation to Redis, making jobs durable across server restarts.

## Classes

- **`JobManager`** — Manages asynchronous job execution for crew operations.

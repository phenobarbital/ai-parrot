---
type: Wiki Summary
title: parrot.handlers.jobs.redis_store
id: mod:parrot.handlers.jobs.redis_store
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Redis-backed persistence layer for Job objects.
relates_to:
- concept: class:parrot.handlers.jobs.redis_store.RedisJobStore
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.handlers.jobs.models
  rel: references
---

# `parrot.handlers.jobs.redis_store`

Redis-backed persistence layer for Job objects.

Stores job state in Redis so that video-generation (and other background) jobs
survive server restarts and can be queried from any process.

Key schema
----------
Jobs are stored as Redis hashes under the key::

    {prefix}:{job_id}

An additional sorted-set keeps track of all known job IDs so that
``list_jobs()`` does not need to do a full key scan::

    {prefix}:_index   score=created_at_timestamp  member=job_id

TTL is applied to individual job hashes after they reach a terminal state
(completed, failed, cancelled).

## Classes

- **`RedisJobStore`** — Async Redis-backed store for background Job objects.

---
type: Wiki Overview
title: 'TASK-1099: OntologyCache Pub/Sub Subscriber'
id: doc:sdd-tasks-completed-task-1099-ontology-cache-pubsub-subscriber-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: When a concept or schema overlay is approved/deprecated, the sync workers
  publish `ontology:invalidate:<tenant_id>` on Redis. Every agent process must subscribe
  to this channel and call `TenantOntologyManager.invalidate(tenant_id)` + `OntologyCache.invalidate_tenant(tenant_id)`
  o
relates_to:
- concept: mod:parrot.knowledge.ontology.cache
  rel: mentions
- concept: mod:parrot.knowledge.ontology.tenant
  rel: mentions
---

# TASK-1099: OntologyCache Pub/Sub Subscriber

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1098
**Assigned-to**: unassigned

---

## Context

When a concept or schema overlay is approved/deprecated, the sync workers publish `ontology:invalidate:<tenant_id>` on Redis. Every agent process must subscribe to this channel and call `TenantOntologyManager.invalidate(tenant_id)` + `OntologyCache.invalidate_tenant(tenant_id)` on message. This task adds the subscriber loop to `OntologyCache`. See spec §3 Module 16.

---

## Scope

- Add `async def subscribe_invalidation(self, manager: TenantOntologyManager) -> None` to `OntologyCache`.
- Subscribe to wildcard `ontology:invalidate:*` channel.
- On message: extract `tenant_id` from channel name, call `manager.invalidate(tenant_id)` + `self.invalidate_tenant(tenant_id)`.
- Designed to be started by the application bootstrap (long-running task).
- Write unit tests.

**NOT in scope**: Worker pub/sub publishing (TASK-1089, TASK-1096), tenant manager extension (TASK-1098).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/cache.py` | MODIFY | Add subscribe_invalidation method |
| `tests/knowledge/ontology/test_cache_pubsub.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.cache import OntologyCache           # cache.py:30
from parrot.knowledge.ontology.tenant import TenantOntologyManager  # tenant.py:18
# redis.asyncio for pub/sub subscription
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/cache.py
class OntologyCache:                                                            # line 30
    def __init__(self, redis_client: Any = None) -> None: ...                   # line 39
    async def invalidate_tenant(self, tenant_id: str) -> None: ...              # line 99
    async def invalidate_all(self) -> None: ...                                 # line 125
    # self._redis is the redis client stored in __init__

# packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py
class TenantOntologyManager:
    def invalidate(self, tenant_id: str | None = None) -> None: ...             # line 165
```

### Does NOT Exist

- ~~`OntologyCache.subscribe_invalidation()`~~ — does not exist; this task creates it.
- ~~Existing Redis pub/sub usage in OntologyCache~~ — the cache uses Redis for key/value only. The subscriber loop is new.

---

## Implementation Notes

### Pattern to Follow

```python
class OntologyCache:
    # ... existing methods ...

    async def subscribe_invalidation(self, manager: TenantOntologyManager) -> None:
        """Subscribe to ontology:invalidate:* and trigger cache + manager invalidation.

        Long-running coroutine — start with asyncio.create_task() during app bootstrap.
        """
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe("ontology:invalidate:*")
        self.logger.info("Subscribed to ontology:invalidate:*")

        async for message in pubsub.listen():
            if message["type"] != "pmessage":
                continue
            channel = message["channel"]
            if isinstance(channel, bytes):
                channel = channel.decode()
            # channel format: "ontology:invalidate:<tenant_id>"
            tenant_id = channel.rsplit(":", 1)[-1]
            self.logger.info("Invalidating tenant %s via pub/sub", tenant_id)
            manager.invalidate(tenant_id)
            await self.invalidate_tenant(tenant_id)
```

### Key Constraints

- Uses `psubscribe` (pattern subscribe) for the wildcard `ontology:invalidate:*`.
- Must handle reconnection gracefully — if Redis connection drops, log error and attempt to resubscribe.
- `manager.invalidate()` is sync; `self.invalidate_tenant()` is async.
- Channel name bytes → string decoding required (`redis.asyncio` returns bytes by default).
- The method runs indefinitely — it's a long-running coroutine.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/cache.py` — existing `OntologyCache` code.
- `redis.asyncio` pub/sub API documentation.

---

## Acceptance Criteria

- [ ] `subscribe_invalidation()` method exists on `OntologyCache`.
- [ ] Subscribes to `ontology:invalidate:*` wildcard pattern.
- [ ] On message, calls `manager.invalidate(tenant_id)`.
- [ ] On message, calls `self.invalidate_tenant(tenant_id)`.
- [ ] Handles bytes → string decoding for channel names.
- [ ] Existing cache tests still pass.
- [ ] All tests pass: `pytest tests/knowledge/ontology/test_cache_pubsub.py -v`

---

## Test Specification

```python
# tests/knowledge/ontology/test_cache_pubsub.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from parrot.knowledge.ontology.cache import OntologyCache


class TestCachePubSubSubscriber:
    async def test_subscriber_calls_invalidate(self, cache_with_redis, mock_manager):
        """Subscriber calls invalidate on both manager and cache when message received."""
        # Publish a message to ontology:invalidate:tenant-a
        # Verify mock_manager.invalidate("tenant-a") was called
        # Verify cache.invalidate_tenant("tenant-a") was called

    async def test_subscriber_extracts_tenant_from_channel(self, cache_with_redis, mock_manager):
        """Subscriber correctly extracts tenant_id from channel name."""
        # Publish to ontology:invalidate:my-complex-tenant-id
        # Verify invalidate was called with "my-complex-tenant-id"

    async def test_subscriber_ignores_non_pmessage(self, cache_with_redis, mock_manager):
        """Subscriber ignores subscribe/unsubscribe confirmation messages."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read** `packages/ai-parrot/src/parrot/knowledge/ontology/cache.py` — understand existing structure
2. **Verify** TASK-1098 is done (manager extension with invalidate)
3. **Check** how the app bootstraps long-running tasks (asyncio.create_task pattern)
4. **Implement** the subscriber with reconnection handling
5. **Run tests**: `pytest tests/knowledge/ontology/test_cache*.py -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any

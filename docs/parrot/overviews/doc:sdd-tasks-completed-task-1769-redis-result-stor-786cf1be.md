---
type: Wiki Overview
title: 'TASK-1769: RedisResultStorage Read Methods'
id: doc:sdd-tasks-completed-task-1769-redis-result-storage-read-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Redis SCAN + GET for listing and direct key operations for get/delete.
relates_to:
- concept: mod:parrot.bots.flows.core.storage.backends.redis
  rel: mentions
---

# TASK-1769: RedisResultStorage Read Methods

**Feature**: FEAT-306 — AgentCrew Saved Crews (Execution Persistence & Replay)
**Spec**: `sdd/specs/agentcrew-saved-crews.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1765
**Assigned-to**: unassigned

---

## Context

`RedisResultStorage` stores one key per execution with format
`{collection}:{crew_name}:{ts_ms}`. This task implements read methods using
Redis SCAN + GET for listing and direct key operations for get/delete.

Redis is not the recommended backend for production read-heavy workloads, but
the spec requires real implementations for all backends.

Implements spec Module 3.

---

## Scope

- Implement `list()` in `RedisResultStorage`:
  - Use SCAN with pattern `{collection}:*` to find matching keys
  - GET each key, parse JSON, filter in-memory by tenant, user_id, crew_name,
    method, date_from, date_to
  - Apply limit/offset after filtering
  - Sort by timestamp descending
- Implement `get()`:
  - SCAN for keys matching `{collection}:*` and find the one whose parsed
    document has matching `id` (or use a secondary index key)
  - Alternative: store an `id` → key mapping on save (future optimization)
  - For now: SCAN + filter approach (acceptable for Redis backend's use case)
- Implement `delete()`:
  - Find key via SCAN (same as get), then DEL
  - Return True if deleted, False if not found
- Implement `count()`:
  - SCAN + filter, return count (no LIMIT/OFFSET)
- Write unit tests for all methods

**NOT in scope**: Optimizing Redis for high-volume reads (documented as known risk).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/redis.py` | MODIFY | Add list, get, delete, count methods |
| `tests/unit/test_redis_result_storage_read.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.core.storage.backends.redis import RedisResultStorage  # redis.py:21
from asyncdb import AsyncDB  # used by RedisResultStorage
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/redis.py:21
class RedisResultStorage(ResultStorage):
    def __init__(self, dsn=None, ttl=None) -> None: ...  # line 29
    async def _ensure(self) -> AsyncDB: ...  # line 46
    async def save(self, collection, document) -> None: ...  # line 53
    # Key pattern: f"{collection}:{crew_name}:{ts_ms}" (line 67)
    # Value: json.dumps(document, default=str) (line 68)
    # conn.execute("SET", key, value, "EX", str(self._ttl)) (line 70)
    async def close(self) -> None: ...  # line 80
```

### Does NOT Exist
- ~~`RedisResultStorage.list()`~~ — does not exist yet
- ~~`RedisResultStorage.get()`~~ — does not exist yet
- ~~`RedisResultStorage.delete()`~~ — does not exist yet
- ~~`RedisResultStorage.scan()`~~ — no scan helper exists
- ~~Redis secondary index for execution IDs~~ — keys are only `{collection}:{crew_name}:{ts_ms}`

---

## Implementation Notes

### Pattern to Follow
Use `conn.execute("SCAN", cursor, "MATCH", pattern, "COUNT", batch_size)` for
scanning. Parse each value with `json.loads()`. Filter in-memory.

```python
async def list(self, collection, filters=None, limit=20, offset=0):
    conn = await self._ensure()
    pattern = f"{collection}:*"
    cursor = "0"
    all_docs = []

    while True:
        result = await conn.execute("SCAN", cursor, "MATCH", pattern, "COUNT", "100")
        cursor = result[0]
        keys = result[1]
        if keys:
            values = await conn.execute("MGET", *keys)
            for val in values:
                if val:
                    doc = json.loads(val)
                    if self._matches_filters(doc, filters):
                        all_docs.append(doc)
        if cursor == "0":
            break

    all_docs.sort(key=lambda d: d.get("timestamp", 0), reverse=True)
    return all_docs[offset:offset + limit]
```

### Key Constraints
- SCAN is non-blocking but O(N) — acceptable for the Redis backend's intended use
- Document structure in Redis is the full document dict (same as what was passed to save)
- The document does NOT have a top-level `id` field in Redis — it's only in Postgres.
  For Redis, use the key itself as the identifier, or generate an ID from the key.
- `asyncdb` Redis execute returns raw Redis protocol values — may need decoding

---

## Acceptance Criteria

- [ ] `list()` returns filtered, paginated results from SCAN
- [ ] `get()` finds a specific execution by identifier
- [ ] `delete()` removes a key and returns bool
- [ ] `count()` returns total matching documents
- [ ] In-memory filtering by tenant, user_id, crew_name, method, date range
- [ ] Results sorted by timestamp descending
- [ ] Tests pass
- [ ] No linting errors

---

## Test Specification

```python
# tests/unit/test_redis_result_storage_read.py
import pytest
from unittest.mock import AsyncMock, patch


class TestRedisResultStorageRead:
    async def test_list_scans_and_filters(self):
        """list() uses SCAN + MGET and filters by tenant/user_id."""

    async def test_list_pagination(self):
        """list() applies offset and limit after filtering."""

    async def test_list_sort_by_timestamp(self):
        """list() returns results newest first."""

    async def test_get_by_key(self):
        """get() finds document by key identifier."""

    async def test_get_not_found(self):
        """get() returns None when key not found."""

    async def test_delete_success(self):
        """delete() removes key and returns True."""

    async def test_delete_not_found(self):
        """delete() returns False when key not found."""

    async def test_count_matches_filter(self):
        """count() returns correct count after filtering."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1765 must be completed
3. **Verify the Codebase Contract** — confirm RedisResultStorage and asyncdb patterns
4. **Update status** in `sdd/tasks/index/agentcrew-saved-crews.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1769-redis-result-storage-read.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-14
**Notes**: Implemented `list()`, `get()`, `delete()`, `count()` on `RedisResultStorage`
using SCAN+MGET (via `_scan_documents()` helper) with in-memory filtering
(`_matches_filters()`, mirroring the Postgres backend's tenant/user_id/crew_name/
method/date_from/date_to semantics, including the `tenant` default-to-`"global"`
COALESCE-equivalent for legacy documents). Since Redis documents have no natural
`id` field, `_scan_documents()`/`get()` set `doc["id"] = <redis key>` so the
returned document shape matches Postgres's (both have an `"id"` the service layer
can rely on). `get()`/`delete()` take the Redis key as `record_id` per the task's
explicit guidance ("For Redis, use the key itself as the identifier"). `delete()`
uses `DEL` and returns `True` iff the reported delete count is `>0`. Created
`tests/unit/test_redis_result_storage_read.py` covering all 8 scenarios from the
task's Test Specification plus 4 exception-handling tests for parity with the
Postgres read-methods test suite. 18/18 new+existing redis tests pass; 68/68
across the full storage test slice touched by TASK-1765/1766/1768/1769. `ruff
check` clean.

**Deviations from spec**: none beyond the `id = redis key` convention explicitly
sanctioned by the task's own Implementation Notes.

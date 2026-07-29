---
type: Wiki Overview
title: 'TASK-1248: PartialSaveStore Redis Service'
id: doc:sdd-tasks-completed-task-1248-partial-save-store-service-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the core service for the partial saves feature (Spec §2 New Public
---

# TASK-1248: PartialSaveStore Redis Service

**Feature**: FEAT-186 — FormDesigner Partial Saves
**Spec**: `sdd/specs/formdesigner-partial-saves.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1247
**Assigned-to**: unassigned

---

## Context

This is the core service for the partial saves feature (Spec §2 New Public
Interfaces, §3 Module 2). It provides Redis-backed ephemeral storage with TTL,
session isolation, and merge-on-write semantics. The implementation must follow
the exact same patterns as `FormCache` in `services/cache.py`.

---

## Scope

- Create `packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py`
- Implement `PartialSaveStore` class with:
  - `REDIS_KEY_PREFIX = "parrot:partial:"`
  - `__init__(self, ttl_seconds: int = 3600, redis_url: str | None = None)`
  - `async def save(form_id, session_id, answers) -> PartialFormData`
    (merge-on-write: load existing, update with new answers, write back)
  - `async def get(form_id, session_id) -> PartialFormData | None`
  - `async def delete(form_id, session_id) -> bool`
  - `async def close() -> None`
  - Internal `_get_redis()` with lazy double-checked locking
  - Internal `_redis_key(form_id, session_id) -> str`
- Redis key format: `parrot:partial:{form_id}:{session_id}`
- SETEX with configurable TTL on every write (refreshes TTL on each save)
- Write unit tests (with Redis mocking)

**NOT in scope**: Handler methods (TASK-1249), merge into submit (TASK-1250),
route registration (TASK-1251), per-field validation (TASK-1249).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py` | CREATE | PartialSaveStore service |
| `packages/parrot-formdesigner/tests/test_partial_save_store.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Within the package (relative imports)
from ..core.partial import PartialFormData  # TASK-1247 creates this

# Standard library
import asyncio  # verified: services/cache.py:15
import logging  # verified: services/cache.py:16
from datetime import datetime, timedelta, timezone  # verified: services/cache.py:17
from typing import Any  # verified: services/cache.py:19

# Redis (lazy import inside method — same as FormCache)
from redis.asyncio import Redis  # verified: services/cache.py:92
```

### Existing Signatures to Use
```python
# services/cache.py — THE PATTERN TO REPLICATE
class FormCache:  # line 38
    REDIS_KEY_PREFIX = "parrot:form:"  # line 57

    def __init__(
        self,
        ttl_seconds: int = 3600,
        redis_url: str | None = None,
    ) -> None:  # line 59
        self._memory_cache: dict[str, _CacheEntry] = {}  # line 72
        self._ttl = timedelta(seconds=ttl_seconds)  # line 73
        self._redis_url = redis_url  # line 74
        self._redis: Any | None = None  # line 75
        self._lock = asyncio.Lock()  # line 76
        self.logger = logging.getLogger(__name__)  # line 78

    async def _get_redis(self) -> Any | None:  # line 80
        # Double-checked locking pattern
        async with self._lock:
            if self._redis is None and self._redis_url:
                from redis.asyncio import Redis
                self._redis = await Redis.from_url(self._redis_url)
        return self._redis

    async def _redis_set(self, redis: Any, form: FormSchema) -> None:  # line 252
        key = self._redis_key(form.form_id)
        ttl_secs = int(self._ttl.total_seconds())
        await redis.setex(key, ttl_secs, form.model_dump_json())

    async def _redis_get(self, redis: Any, form_id: str) -> FormSchema | None:  # line 233
        data = await redis.get(key)
        if data:
            return FormSchema.model_validate_json(data)

    async def _redis_delete(self, redis: Any, form_id: str) -> None:  # line 268
        await redis.delete(self._redis_key(form_id))

    async def close(self) -> None:  # line 293
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
```

### Does NOT Exist
- ~~`parrot_formdesigner.services.partial_saves`~~ — does not exist yet (this task creates it)
- ~~`PartialSaveStore`~~ — does not exist yet
- ~~`FormCache.save_partial()`~~ — FormCache has no partial methods
- ~~`FormCache.get_partial()`~~ — not a real method

---

## Implementation Notes

### Pattern to Follow
```python
class PartialSaveStore:
    REDIS_KEY_PREFIX = "parrot:partial:"

    def __init__(self, ttl_seconds: int = 3600, redis_url: str | None = None) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._redis_url = redis_url
        self._redis: Any | None = None
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    def _redis_key(self, form_id: str, session_id: str) -> str:
        return f"{self.REDIS_KEY_PREFIX}{form_id}:{session_id}"

    async def save(self, form_id: str, session_id: str, answers: dict[str, Any]) -> PartialFormData:
        # 1. Load existing partial (if any)
        existing = await self.get(form_id, session_id)
        # 2. Merge: existing.data | answers (answers win)
        merged_data = {**(existing.data if existing else {}), **answers}
        # 3. Build PartialFormData with updated timestamps
        now = datetime.now(tz=timezone.utc)
        partial = PartialFormData(
            form_id=form_id,
            session_id=session_id,
            data=merged_data,
            field_errors={},  # errors populated by handler, not store
            saved_at=now,
            expires_at=now + self._ttl,
        )
        # 4. Write to Redis with SETEX (refreshes TTL)
        redis = await self._get_redis()
        if redis:
            await self._redis_set(redis, partial)
        return partial
```

### Key Constraints
- No in-memory cache tier (unlike FormCache). Partial saves are Redis-only
  since they are per-session ephemeral data not worth local caching.
- Every `save()` refreshes the TTL for the entire entry.
- `get()` returns `None` if key is absent (Redis handles TTL expiry natively).
- `delete()` returns `True` if key existed, `False` otherwise (use `redis.delete()` return value).
- Wrap all Redis calls in try/except with warning logs (same as FormCache).

### References in Codebase
- `services/cache.py` — primary pattern reference (copy structure)

---

## Acceptance Criteria

- [ ] `PartialSaveStore` class exists in `services/partial_saves.py`
- [ ] Redis key format is `parrot:partial:{form_id}:{session_id}`
- [ ] `save()` merges new answers over existing cached data (last-write-wins)
- [ ] `save()` refreshes TTL on every write
- [ ] `get()` returns `PartialFormData` or `None`
- [ ] `delete()` returns `True`/`False` based on key existence
- [ ] `close()` closes Redis connection
- [ ] Graceful failure when Redis unavailable (logs warning, does not raise)
- [ ] TTL defaults to 3600 seconds (1 hour)
- [ ] Unit tests pass: `pytest packages/parrot-formdesigner/tests/test_partial_save_store.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/test_partial_save_store.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot_formdesigner.services.partial_saves import PartialSaveStore


@pytest.fixture
def store():
    return PartialSaveStore(ttl_seconds=60, redis_url="redis://localhost:6379")


class TestPartialSaveStore:
    async def test_save_single_field(self, store):
        """Save one field, verify stored."""
        ...

    async def test_save_bulk(self, store):
        """Save multiple fields at once."""
        ...

    async def test_merge_overwrite(self, store):
        """New values override cached values."""
        ...

    async def test_get_existing(self, store):
        """Retrieve previously saved data."""
        ...

    async def test_get_nonexistent(self, store):
        """Returns None when no data cached."""
        ...

    async def test_delete(self, store):
        """Delete removes cached data."""
        ...

    async def test_session_isolation(self, store):
        """Different sessions have separate data."""
        ...

    async def test_no_redis_graceful(self):
        """Graceful failure when Redis unavailable."""
        store = PartialSaveStore(ttl_seconds=60, redis_url=None)
        result = await store.save("form1", "sess1", {"name": "test"})
        assert result.data == {"name": "test"}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-partial-saves.spec.md` §2 New Public Interfaces
2. **Check dependencies** — verify TASK-1247 is complete (`core/partial.py` exists)
3. **Read `services/cache.py`** line by line — replicate the pattern exactly
4. **Implement** `services/partial_saves.py`
5. **Run tests**: `pytest packages/parrot-formdesigner/tests/test_partial_save_store.py -v`
6. **Update index** and move file on completion

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-05-19
**Notes**: Created `services/partial_saves.py` with `PartialSaveStore` class following the
`FormCache` pattern exactly. Implements save (merge-on-write), get, delete, close, and
internal _get_redis (lazy double-checked locking), _redis_key, _redis_set, _redis_get,
_redis_delete helpers. 22 unit tests all pass.

**Deviations from spec**: none

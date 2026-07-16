---
type: Wiki Overview
title: 'TASK-1218: `_FileBlobCache` SHA-keyed cache helper'
id: doc:sdd-tasks-completed-task-1218-file-blob-cache-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 2. Provides a SHA-keyed cache that fronts file
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots.database.cache
  rel: mentions
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
---

# TASK-1218: `_FileBlobCache` SHA-keyed cache helper

**Feature**: FEAT-182 — GitToolkit On-Demand Code Retrieval for GithubReviewer
**Spec**: `sdd/specs/gittoolkit-pr-context-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2. Provides a SHA-keyed cache that fronts file
fetches for the on-demand code retrieval tools. Reuses the existing
`CachePartition` from `parrot.bots.database.cache` — Redis-backed when
`REDIS_URL` is configured, in-memory LRU fallback otherwise.

Prerequisite for TASK-1219 (`get_file_content_at_ref`).

---

## Scope

- Add a private `_FileBlobCache` class to
  `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py`, placed near
  other private helpers (e.g. close to `_GitHubAppTokenProvider`).
- Public surface (async):
  - `async def get(self, repository: str, sha: str) -> Optional[bytes]`
  - `async def set(self, repository: str, sha: str, content: bytes) -> None`
- Internally builds a `CachePartition` with namespace `gittoolkit_blob`
  using `CacheManager(redis_url=<navconfig REDIS_URL>)`. If Redis init
  fails, falls back to in-memory LRU silently (CachePartition already
  handles this — see `cache.py:644`).
- Read `GITHUB_REVIEWER_BLOB_CACHE_TTL` from navconfig with fallback
  `604800` (7 days).
- Lazy-init: cache instance is created on first `.get()` / `.set()` call,
  not at module import.
- Write unit tests in
  `packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py` covering:
  - cache miss returns `None`,
  - set+get round-trip returns bytes,
  - LRU fallback when `REDIS_URL` is unset,
  - Redis mode is selected when `REDIS_URL` is set (patch `aioredis.from_url`).

**NOT in scope**:
- Wiring the cache into any tool (TASK-1219 does that).
- Adding navconfig keys to `.env.example` — done in TASK-1223 (docs).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY | Add `_FileBlobCache` private class |
| `packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py` | MODIFY | Add cache unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# To be added to gittoolkit.py:
from parrot.bots.database.cache import (
    CacheManager,
    CachePartition,
    CachePartitionConfig,
)
# Verified at parrot/bots/database/cache.py:53, 611, 32
# NOTE: ai-parrot-tools must declare ai-parrot as a runtime dep for this
# to work cleanly. Check packages/ai-parrot-tools/pyproject.toml — if
# the dep is not there, add it via `uv add ai-parrot --package ai-parrot-tools`
# BEFORE writing code.

# Already imported in gittoolkit.py:
from typing import Any, Dict, List, Literal, Optional   # gittoolkit.py:31
```

If the inter-package dep cannot be added cleanly, the implementer may
instead duplicate a thin Redis+LRU wrapper inside `gittoolkit.py`
(escalate via the Completion Note rather than implementing silently).

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/database/cache.py
class CachePartitionConfig(BaseModel):                              # line 32
    namespace: str
    lru_maxsize: int
    lru_ttl: int
    redis_ttl: int
    # other optional fields

class CachePartition:                                                # line 53
    # Provides async get/set/delete with Redis (when pool set) + LRU.
    # Constructor signature:
    def __init__(self, namespace: str, lru_maxsize: int, lru_ttl: int,
                 redis_ttl: int, redis_pool: Any, vector_store: Any = None,
                 ttl_by_completeness: Any = None): ...

class CacheManager:                                                  # line 611
    def __init__(self, redis_url: Optional[str] = None,              # line 619
                 vector_store: Optional[Any] = None): ...
    def _init_redis(self, redis_url: str) -> None: ...               # line 634
    def create_partition(self,                                       # line 649
                         config: CachePartitionConfig) -> CachePartition: ...
```

```python
# Reading config (navconfig pattern already used in the codebase):
from navconfig import config
# Verified usage in packages/ai-parrot/src/parrot/bots/github_reviewer.py:420
ttl = config.get("GITHUB_REVIEWER_BLOB_CACHE_TTL", fallback=604800)
redis_url = config.get("REDIS_URL")  # may be None
```

NB: per the memory record `feedback_navconfig_kardex_fallback.md`,
**always use `fallback=`, never `default=`** with navconfig — `default=`
raises `TypeError`.

### Does NOT Exist

- ~~`parrot.cache.RedisCache`~~ — no `parrot.cache` module exists.
- ~~`CachePartition.get_or_set(...)`~~ — not a real method. Use `get` then
  `set` explicitly.
- ~~`aioredis` as a separate package~~ — use `redis.asyncio as aioredis`
  (the import-aliased version in `parrot/bots/database/cache.py:637`).

---

## Implementation Notes

### Pattern to Follow

```python
# Sketch only — real implementation in the task.
class _FileBlobCache:
    """SHA-keyed blob cache for GitHub file content."""

    def __init__(self) -> None:
        self._partition: Optional[CachePartition] = None
        self._lock = asyncio.Lock()

    async def _ensure_partition(self) -> CachePartition:
        if self._partition is not None:
            return self._partition
        async with self._lock:
            if self._partition is not None:
                return self._partition
            redis_url = config.get("REDIS_URL")
            ttl = int(config.get("GITHUB_REVIEWER_BLOB_CACHE_TTL", fallback=604800))
            manager = CacheManager(redis_url=redis_url)
            self._partition = manager.create_partition(
                CachePartitionConfig(
                    namespace="gittoolkit_blob",
                    lru_maxsize=1024,
                    lru_ttl=ttl,
                    redis_ttl=ttl,
                )
            )
            return self._partition
```

Key naming: `f"{repository}:{sha}"`. Repository is lowercased to avoid
case collisions (`Owner/Repo` vs `owner/repo`).

### Key Constraints

- Lazy init avoids requiring Redis at module import time (tests must be
  able to import `gittoolkit` without Redis running).
- Thread-safe / coroutine-safe via `asyncio.Lock`. Multiple concurrent
  reviewers share one partition instance.
- Silent degradation: if Redis is set but unreachable at runtime,
  `CacheManager._init_redis` already logs a warning and falls back to
  LRU-only mode — propagate that behavior; don't re-raise.

---

## Acceptance Criteria

- [ ] `_FileBlobCache` defined in `gittoolkit.py` with the public async
  surface (`get`, `set`).
- [ ] Lazy partition init: first call constructs the partition, later
  calls reuse it.
- [ ] Unit test `test_blob_cache_redis_hit` passes (Redis pool mocked).
- [ ] Unit test `test_blob_cache_lru_fallback` passes (Redis absent).
- [ ] Unit test `test_blob_cache_miss_then_hit` passes.
- [ ] `ruff check packages/ai-parrot-tools/` passes.

---

## Test Specification

```python
# Extend packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py
import pytest
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_blob_cache_miss_then_hit(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    from parrot_tools.gittoolkit import _FileBlobCache
    cache = _FileBlobCache()
    assert await cache.get("owner/repo", "deadbeef") is None
    await cache.set("owner/repo", "deadbeef", b"hello")
    assert await cache.get("owner/repo", "deadbeef") == b"hello"


@pytest.mark.asyncio
async def test_blob_cache_lru_fallback(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    from parrot_tools.gittoolkit import _FileBlobCache
    cache = _FileBlobCache()
    await cache.set("o/r", "s1", b"x")
    # Same process, second instance: LRU is per-instance, so cache is empty.
    cache2 = _FileBlobCache()
    assert await cache2.get("o/r", "s1") is None
```

---

## Agent Instructions

1. Verify `ai-parrot` is a declared dep of `ai-parrot-tools`. If not,
   stop and surface the issue.
2. Implement `_FileBlobCache` per spec §3 Module 2.
3. Write tests. Run `pytest` and `ruff`.
4. Update task status to `done` in the per-spec index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-18
**Notes**:

**Deviations from spec**: none

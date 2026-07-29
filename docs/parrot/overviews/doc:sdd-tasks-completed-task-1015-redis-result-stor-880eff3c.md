---
type: Wiki Overview
title: 'TASK-1015: RedisResultStorage backend'
id: doc:sdd-tasks-completed-task-1015-redis-result-storage-backend-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements the Redis backend for FEAT-147. One key per execution
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends.redis
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
---

# TASK-1015: RedisResultStorage backend

**Feature**: FEAT-147 — Crew Result Storage Backends
**Spec**: `sdd/specs/crew-result-storage-backends.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1013
**Assigned-to**: unassigned

---

## Context

Implements the Redis backend for FEAT-147. One key per execution
(`crew_executions:{crew_name}:{ts_ms}`), JSON-encoded value, optional TTL.
Resolves spec §2 "Backend: Redis" and §3 Module 3.

This task is conceptually parallel to TASK-1014 and TASK-1016 — they
share no source files. Within a single worktree they still run
sequentially.

---

## Scope

- Implement `RedisResultStorage(ResultStorage)` in
  `parrot/bots/flows/core/storage/backends/redis.py`.
- Use `asyncdb.AsyncDB('redis', dsn=...)` as the driver, mirroring
  `parrot/handlers/agents/abstract.py:48`.
- Connection lifecycle: lazy-connect on first `save()`, store the
  connection on `self._conn`; `close()` releases it.
- DSN source: constructor argument, then
  `parrot.conf.CREW_RESULT_STORAGE_REDIS_URL`, then `parrot.conf.REDIS_URL`.
- TTL source: constructor argument, then
  `parrot.conf.CREW_RESULT_STORAGE_REDIS_TTL` (seconds; `0` disables TTL).
- Key shape: `f"{collection}:{document['crew_name']}:{int(time.time()*1000)}"`.
  If `crew_name` is missing from the document, fall back to `"unknown"`.
- Value: `json.dumps(document, default=str)` to tolerate non-serializable
  fields (datetimes, custom objects).
- Failures inside `save()` log a `WARNING` and are swallowed (matches the
  existing fire-and-forget contract).
- Add unit tests with a mocked `AsyncDB` recording the calls.

**NOT in scope**: Per-key compression, batching, or LIST-based circular
logs (rejected in spec §8 Q2 in favour of option (a)). Reading past
executions (out of scope per spec §1 Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/flows/core/storage/backends/redis.py` | CREATE | `RedisResultStorage`. |
| `tests/bots/flows/core/storage/test_redis_backend.py` | CREATE | Unit tests with mocked asyncdb. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from asyncdb import AsyncDB                               # verified: parrot/handlers/agents/abstract.py:13, parrot/interfaces/database.py:12
from parrot.conf import CREW_RESULT_STORAGE_REDIS_URL, CREW_RESULT_STORAGE_REDIS_TTL
# (the two CREW_RESULT_STORAGE_* keys are CREATED by TASK-1013 — verify they import successfully)
```

### Existing Signatures to Use
```python
# Existing redis-via-asyncdb usage pattern
# parrot/handlers/agents/abstract.py:48
self.conn = AsyncDB('redis', dsn=CACHE_URL)
```

`AsyncDB('redis', dsn=...)` constructs a connection wrapper. The
underlying methods used are:
- `await conn.connection()` — open the connection (returns the wrapper).
- `await conn.execute(command, *args)` — execute a Redis command. For
  this task we issue `SET <key> <value>` or `SET <key> <value> EX <ttl>`.
- `await conn.close()` — release the connection.

If the implementing agent finds the asyncdb redis API surface differs
from this assumption, **prefer using `redis.asyncio` directly** as a
fallback (same approach as `parrot/autonomous/redis_jobs.py:6,38`):
```python
import redis.asyncio as aioredis
self._conn = await aioredis.from_url(dsn, decode_responses=True)
await self._conn.set(key, value, ex=ttl or None)
```
Document whichever path is taken in the Completion Note.

### Does NOT Exist
- ~~`asyncdb.RedisStorage`~~ — no such class; always go through `AsyncDB('redis', ...)`.
- ~~`AsyncDB.write_redis`~~ — not a method; use `execute('SET', ...)` or `set(key, value)` depending on the chosen path.

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/bots/flows/core/storage/backends/redis.py
from __future__ import annotations
import json
import time
from typing import Any, Optional

from navconfig.logging import logging
from asyncdb import AsyncDB

from parrot.conf import (
    CREW_RESULT_STORAGE_REDIS_URL,
    CREW_RESULT_STORAGE_REDIS_TTL,
)
from .base import ResultStorage


class RedisResultStorage(ResultStorage):
    """Persist crew/flow execution results to Redis (one key per execution)."""

    def __init__(
        self,
        dsn: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> None:
        self._dsn = dsn or CREW_RESULT_STORAGE_REDIS_URL
        self._ttl = CREW_RESULT_STORAGE_REDIS_TTL if ttl is None else ttl
        self._conn = None
        self.logger = logging.getLogger("parrot.crew_storage.redis")

    async def _ensure(self):
        if self._conn is None:
            self._conn = AsyncDB("redis", dsn=self._dsn)
            await self._conn.connection()
        return self._conn

    async def save(self, collection: str, document: dict[str, Any]) -> None:
        try:
            conn = await self._ensure()
            crew_name = document.get("crew_name", "unknown")
            ts_ms = int(time.time() * 1000)
            key = f"{collection}:{crew_name}:{ts_ms}"
            value = json.dumps(document, default=str)
            if self._ttl > 0:
                await conn.execute("SET", key, value, "EX", str(self._ttl))
            else:
                await conn.execute("SET", key, value)
        except Exception as exc:
            self.logger.warning(
                "RedisResultStorage save failed for collection=%s: %s",
                collection, exc,
            )

    async def close(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.close()
            finally:
                self._conn = None
```

### Key Constraints
- Always wrap `save()` body in `try/except` and log at WARNING — never
  raise into the caller (preserves fire-and-forget contract).
- `close()` must be idempotent (safe to call twice or before any save).
- Use `json.dumps(..., default=str)` to tolerate datetimes / dataclasses
  (see spec §7 "Known Risks / Gotchas").
- TTL of `0` (or negative) means "no TTL" — do NOT pass `EX 0` to Redis.

### References in Codebase
- `parrot/handlers/agents/abstract.py:48` — asyncdb redis init pattern.
- `parrot/autonomous/redis_jobs.py:38` — fallback pattern using `redis.asyncio`.

---

## Acceptance Criteria

- [ ] `from parrot.bots.flows.core.storage.backends import RedisResultStorage` succeeds.
- [ ] `get_result_storage("redis")` returns a `RedisResultStorage` instance.
- [ ] First `save()` call lazily connects (one `AsyncDB('redis', ...)` construction); second call reuses the same connection.
- [ ] When TTL > 0, the issued command includes `EX <ttl>`.
- [ ] When TTL is `0`, the issued command does NOT include `EX`.
- [ ] Backend `save()` failures (driver raises) are logged at WARNING and do not propagate.
- [ ] `close()` releases the connection and is idempotent.
- [ ] `pytest tests/bots/flows/core/storage/test_redis_backend.py -v` is green.
- [ ] `ruff check parrot/bots/flows/core/storage/backends/redis.py` is clean.

---

## Test Specification

```python
# tests/bots/flows/core/storage/test_redis_backend.py
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_asyncdb(monkeypatch):
    conn = MagicMock()
    conn.connection = AsyncMock(return_value=conn)
    conn.execute = AsyncMock(return_value=None)
    conn.close = AsyncMock(return_value=None)
    cls = MagicMock(return_value=conn)
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.redis.AsyncDB",
        cls,
    )
    return conn, cls


@pytest.mark.asyncio
async def test_redis_save_uses_ttl_by_default(mock_asyncdb):
    from parrot.bots.flows.core.storage.backends import RedisResultStorage
    conn, _ = mock_asyncdb
    backend = RedisResultStorage(ttl=60)
    await backend.save("crew_executions", {"crew_name": "x"})
    args = conn.execute.await_args.args
    assert args[0] == "SET"
    assert args[1].startswith("crew_executions:x:")
    assert "EX" in args
    assert args[args.index("EX") + 1] == "60"


@pytest.mark.asyncio
async def test_redis_save_omits_ttl_when_zero(mock_asyncdb):
    from parrot.bots.flows.core.storage.backends import RedisResultStorage
    conn, _ = mock_asyncdb
    backend = RedisResultStorage(ttl=0)
    await backend.save("crew_executions", {"crew_name": "x"})
    args = conn.execute.await_args.args
    assert "EX" not in args


@pytest.mark.asyncio
async def test_redis_save_swallows_exceptions(mock_asyncdb, caplog):
    from parrot.bots.flows.core.storage.backends import RedisResultStorage
    conn, _ = mock_asyncdb
    conn.execute.side_effect = RuntimeError("redis down")
    backend = RedisResultStorage(ttl=60)
    await backend.save("crew_executions", {"crew_name": "x"})
    assert "RedisResultStorage save failed" in caplog.text


@pytest.mark.asyncio
async def test_redis_close_idempotent(mock_asyncdb):
    from parrot.bots.flows.core.storage.backends import RedisResultStorage
    backend = RedisResultStorage(ttl=60)
    await backend.close()        # never connected → no-op
    await backend.save("crew_executions", {"crew_name": "x"})
    await backend.close()
    await backend.close()        # second close → no-op
```

---

## Agent Instructions

1. **Read the spec** §2 "Backend: Redis" and verify TASK-1013 is in `tasks/completed/`.
2. **Activate the venv**: `source .venv/bin/activate`.
3. **Verify** the asyncdb redis API surface — start by `grep -n "AsyncDB('redis'" parrot/handlers/agents/abstract.py` and try a small REPL session with `AsyncDB('redis', dsn=...)`. If `execute("SET", ...)` is unavailable, switch to the `redis.asyncio` fallback documented above.
4. **Implement** the backend.
5. **Run** `pytest tests/bots/flows/core/storage/test_redis_backend.py -v`.
6. **Move this file** to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-05
**Notes**: 6 tests pass. Uses asyncdb.AsyncDB('redis'). Lazy connect,
EX TTL omitted when 0, exceptions swallowed and logged. JSON encoded
with default=str.

**Deviations from spec**: none

---
type: Wiki Overview
title: 'TASK-926: Connection Boundary Unwrap — yield raw asyncpg.Connection'
id: doc:sdd-tasks-completed-task-926-asyncpg-boundary-unwrap-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 1 of the spec. Currently `_acquire_asyncdb_connection`
---

# TASK-926: Connection Boundary Unwrap — yield raw asyncpg.Connection

**Feature**: FEAT-118 — Database Toolkit asyncpg Native Boundary Refactor
**Spec**: `sdd/specs/database-toolkit-asyncpg-boundary-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements Module 1 of the spec. Currently `_acquire_asyncdb_connection`
yields the asyncdb `pg` wrapper object. Downstream callers (CRUD, transaction)
call asyncpg-native methods (`fetch`, `fetchrow`, `execute`) on this wrapper,
which has incompatible signatures — causing `TypeError` at runtime (defect D1).

This task unwraps the driver **once at the boundary** via `conn.engine()`
(alias for `get_connection()`) so every downstream consumer receives a raw
`asyncpg.Connection`.

---

## Scope

- Modify `_acquire_asyncdb_connection` in `base.py` to call `engine()` on the
  acquired wrapper and yield the raw connection.
- For the pool path: the wrapper (not the raw conn) must still be passed to
  `release()`.
- For the single-connection path: unwrap after entering the wrapper's context
  manager.
- Simplify `PostgresToolkit._run_on_conn` — remove the need for any unwrap
  guard since the boundary now yields raw asyncpg.
- Write unit tests for both pool and single-connection paths.

**NOT in scope**: query-builder param changes (TASK-928), SQLAlchemy removal
(TASK-927), transaction rewrite (TASK-929), NavigatorToolkit cleanup (TASK-930).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/toolkits/base.py` | MODIFY | `_acquire_asyncdb_connection` — unwrap via `engine()` |
| `packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py` | MODIFY | `_run_on_conn` — simplify (conn is now raw asyncpg) |
| `tests/unit/bots/database/toolkits/test_acquire_conn_boundary.py` | CREATE | Unit tests for boundary unwrap |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from contextlib import asynccontextmanager  # stdlib
from typing import Any, AsyncIterator       # stdlib

# asyncdb external — DO NOT import directly in toolkit code;
# asyncdb is used via self._connection (AsyncDB or AsyncPool instance)

# asyncdb driver interface (for understanding, not importing):
# asyncdb/interfaces/abstract.py:66  def get_connection(self): ...
# asyncdb/interfaces/abstract.py:69  engine = get_connection
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/base.py:378-399
@asynccontextmanager
async def _acquire_asyncdb_connection(self) -> AsyncIterator[Any]:
    """Yield a usable asyncdb connection, abstracting pool vs single."""
    if self._connection is None:
        raise RuntimeError("Not connected (call start() first)")
    if self.use_pool:
        conn = await self._connection.acquire()  # returns asyncdb pg wrapper
        try:
            yield conn          # <-- CHANGE: yield conn.engine() instead
        finally:
            try:
                await self._connection.release(conn)  # release WRAPPER, not raw
            except Exception as exc:
                self.logger.debug("Pool release failed: %s", exc)
    else:
        async with await self._connection.connection() as conn:
            yield conn          # <-- CHANGE: yield conn.engine() instead

# packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py:807-824
@staticmethod
async def _run_on_conn(
    sql: str,
    args: tuple[Any, ...],
    returning: Optional[List[str]],
    conn: Any,
    single_row: bool,
) -> Any:
    """Execute on a concrete connection object."""
    # After this task, conn IS raw asyncpg — no unwrap needed.
    if not returning:
        await conn.execute(sql, *args)
        return {"status": "ok"}
    if single_row:
        row = await conn.fetchrow(sql, *args)
        return dict(row) if row else {}
    else:
        rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows] if rows else []

# packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py:787-805
async def _execute_crud(
    self,
    sql: str,
    args: tuple[Any, ...],
    returning: Optional[List[str]],
    conn: Optional[Any],
    single_row: bool,
) -> Any:
    if conn is not None:
        return await self._run_on_conn(sql, args, returning, conn, single_row)
    async with self._acquire_asyncdb_connection() as acquired_conn:
        return await self._run_on_conn(sql, args, returning, acquired_conn, single_row)
```

### asyncdb Driver API (external, verified)
```python
# asyncdb/interfaces/abstract.py
class AbstractDriver:
    def get_connection(self): ...   # line 66 — returns raw driver connection
    engine = get_connection         # line 69 — alias

# asyncdb/drivers/pg.py
class pg(SQLDriver, DBCursorBackend, ModelBackend):
    # self._connection is asyncpg.Connection (set by async def connection())
    def get_connection(self):
        return self._connection     # returns raw asyncpg.Connection

class pgPool(BasePool):
    async def acquire(self) -> pg: ...         # line 321 — returns pg wrapper
    async def release(self, connection=None, ...) # line 356 — accepts wrapper or raw
```

### Does NOT Exist
- ~~`asyncdb.drivers.pg.pg.raw_connection()`~~ — use `engine()` (alias for `get_connection()`)
- ~~`asyncpg.Connection.savepoint()`~~ — savepoints are nested `transaction()` blocks
- ~~`self._connection.unwrap()`~~ — not a method; use `engine()` on the acquired wrapper
- ~~`conn.get_raw()`~~ — does not exist

---

## Implementation Notes

### Pattern
```python
# Pool path — unwrap but release the WRAPPER
if self.use_pool:
    wrapper = await self._connection.acquire()
    try:
        yield wrapper.engine()    # raw asyncpg.Connection
    finally:
        await self._connection.release(wrapper)  # release the wrapper

# Single path — unwrap inside the context manager
async with await self._connection.connection() as wrapper:
    yield wrapper.engine()        # raw asyncpg.Connection
```

### Key Constraints
- `pgPool.release()` must receive the **wrapper**, not the raw conn.
- `_run_on_conn` body stays the same — it already calls asyncpg APIs
  (`fetch`, `fetchrow`, `execute`). The fix is that `conn` is now actually
  a raw `asyncpg.Connection` instead of the wrapper.
- `_execute_asyncdb` in `sql.py` still calls `conn.query(sql)` — that will
  break after this change (fixed in TASK-928). This task does NOT modify
  `_execute_asyncdb`.

---

## Acceptance Criteria

- [ ] `_acquire_asyncdb_connection` yields raw `asyncpg.Connection` (via `engine()`)
- [ ] Pool path: `release()` still receives the asyncdb wrapper (not raw conn)
- [ ] `PostgresToolkit._run_on_conn` works without any unwrap guard
- [ ] `test_acquire_asyncdb_yields_raw_asyncpg` passes
- [ ] `test_acquire_asyncdb_pool_releases_wrapper` passes
- [ ] No regressions in existing CRUD tests

---

## Test Specification

```python
# tests/unit/bots/database/toolkits/test_acquire_conn_boundary.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class FakeRawConn:
    """Stub for raw asyncpg.Connection."""
    async def fetch(self, sql, *args): return []
    async def fetchrow(self, sql, *args): return None
    async def execute(self, sql, *args): return "ok"


class FakeWrapper:
    """Stub for asyncdb pg driver wrapper."""
    def engine(self):
        return FakeRawConn()


class FakePool:
    """Stub for asyncdb pgPool."""
    async def acquire(self):
        return FakeWrapper()
    async def release(self, conn):
        self._released = conn


@pytest.mark.asyncio
async def test_acquire_asyncdb_yields_raw_asyncpg():
    """Boundary yields raw conn (engine()), not the wrapper."""
    # ... instantiate toolkit with mocked _connection ...
    # assert yielded object is FakeRawConn, not FakeWrapper

@pytest.mark.asyncio
async def test_acquire_asyncdb_pool_releases_wrapper():
    """Pool.release() receives the wrapper, not the raw conn."""
    # ... assert pool._released is the FakeWrapper instance ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `_acquire_asyncdb_connection` is at `base.py:378`
   - Confirm `_run_on_conn` is at `postgres.py:807`
   - Confirm `engine()` alias exists in asyncdb
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-926-asyncpg-boundary-unwrap.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any

---
type: Wiki Overview
title: 'TASK-929: Transaction on asyncpg Native with Savepoint Support'
id: doc:sdd-tasks-completed-task-929-transaction-asyncpg-native-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 4 of the spec. Fixes defect D5. Currently
---

# TASK-929: Transaction on asyncpg Native with Savepoint Support

**Feature**: FEAT-118 — Database Toolkit asyncpg Native Boundary Refactor
**Spec**: `sdd/specs/database-toolkit-asyncpg-boundary-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-926
**Assigned-to**: unassigned

---

## Context

Implements Module 4 of the spec. Fixes defect D5. Currently
`PostgresToolkit.transaction()` calls `async with conn.transaction()` where
`conn` is the asyncdb `pg` wrapper — the wrapper's `transaction()` is an
`async def` that returns `self`, not a proper async context manager.

After TASK-926, `_acquire_asyncdb_connection` yields raw `asyncpg.Connection`.
This task rewrites `transaction()` to use asyncpg's native transaction API,
which properly supports nested savepoints.

---

## Scope

- Rewrite `PostgresToolkit.transaction()` to use raw asyncpg transaction API.
- Remove the `self._in_transaction` guard and `RuntimeError` for nested
  transactions — asyncpg natively supports nested `transaction()` as
  savepoints.
- Write unit tests for transaction yield type and savepoint rollback.

**NOT in scope**: connection boundary (TASK-926), SQLAlchemy removal
(TASK-927), query-builder params (TASK-928), NavigatorToolkit cleanup
(TASK-930).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py` | MODIFY | Rewrite `transaction()` |
| `tests/unit/bots/database/toolkits/test_transaction_savepoint.py` | CREATE | Unit + integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Signatures to Modify

```python
# postgres.py:830-865 — current transaction()
@asynccontextmanager
async def transaction(self) -> AsyncIterator[Any]:
    """Yield an asyncdb connection inside a transaction block."""
    if self._in_transaction:
        raise RuntimeError(
            "Nested transactions are not supported. "
            "Complete the current transaction before starting a new one."
        )
    self._in_transaction = True
    try:
        async with self._acquire_asyncdb_connection() as conn:
            async with conn.transaction():   # <-- broken on wrapper (D5)
                try:
                    yield conn
                except Exception:
                    self._in_transaction = False
                    raise
    finally:
        self._in_transaction = False

# postgres.py:58 — instance state
self._in_transaction: bool = False
```

### Target Implementation
```python
# postgres.py — AFTER rewrite:
@asynccontextmanager
async def transaction(self) -> AsyncIterator[Any]:
    """Yield a raw asyncpg connection inside a transaction block.

    Commits on normal exit, rolls back on exception. Supports nested
    savepoints via ``async with conn.transaction()`` inside the block.

    Yields:
        Raw ``asyncpg.Connection`` — can be passed as ``conn=`` to
        CRUD methods or used directly for ``fetch``/``execute``.
    """
    async with self._acquire_asyncdb_connection() as raw_conn:
        async with raw_conn.transaction():
            yield raw_conn
```

### asyncpg Transaction API (external, verified)
```python
# asyncpg.Connection.transaction() returns a Transaction object
# that is an async context manager:
#   async with conn.transaction():
#       ...  # auto-commit on exit, auto-rollback on exception
#
# Nested calls create savepoints:
#   async with conn.transaction():          # BEGIN
#       async with conn.transaction():      # SAVEPOINT sp1
#           ...                             # RELEASE sp1 on success
#                                           # ROLLBACK TO sp1 on exception
#       ...                                 # COMMIT on success
```

### Does NOT Exist
- ~~`asyncpg.Connection.savepoint()`~~ — savepoints are nested `transaction()` blocks
- ~~`asyncpg.Connection.begin()`~~ — use `transaction()` context manager
- ~~`conn.start_transaction()`~~ — not an asyncpg method
- ~~Keeping `self._in_transaction` guard~~ — asyncpg handles nesting natively

---

## Implementation Notes

### Key Changes
1. Remove `self._in_transaction` field and all references.
2. The rewritten `transaction()` is much simpler — just two nested `async with`.
3. After TASK-926, `raw_conn` from `_acquire_asyncdb_connection` is already a
   raw `asyncpg.Connection`, so `raw_conn.transaction()` is the proper asyncpg
   `Transaction` async context manager.

### Callers of transaction()
Grep for `self.transaction()` and `toolkit.transaction()` to identify all
callers. Existing callers (e.g., NavigatorToolkit CRUD methods) pass the
yielded `conn` as `conn=tx` to other methods — this pattern remains unchanged
since `_run_on_conn` already expects asyncpg-style calls.

### Key Constraints
- `self._in_transaction` attribute can be removed from `__init__` — but verify
  no other method reads it. If `_execute_crud` or other methods check it,
  remove those checks too.

---

## Acceptance Criteria

- [ ] `transaction()` yields raw `asyncpg.Connection` (verified by type)
- [ ] Nested `async with conn.transaction()` works as savepoint (no RuntimeError)
- [ ] `self._in_transaction` flag removed
- [ ] `test_transaction_yields_raw_asyncpg` passes
- [ ] `test_transaction_savepoint_rollback` passes (live-DB gated)
- [ ] No regressions in CRUD tests that use `conn=tx` pattern

---

## Test Specification

```python
# tests/unit/bots/database/toolkits/test_transaction_savepoint.py
import pytest
from unittest.mock import AsyncMock, MagicMock


class FakeTransaction:
    """Stub for asyncpg Transaction context manager."""
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass


class FakeRawConn:
    """Stub for raw asyncpg.Connection."""
    def transaction(self):
        return FakeTransaction()
    async def fetch(self, sql, *args): return []
    async def execute(self, sql, *args): return "ok"


@pytest.mark.asyncio
async def test_transaction_yields_raw_asyncpg():
    """transaction() yields an object with fetch/fetchrow/execute."""
    # Mock _acquire_asyncdb_connection to yield FakeRawConn
    # assert yielded conn has .fetch, .fetchrow, .execute

@pytest.mark.asyncio
async def test_nested_transaction_no_error():
    """Nested transaction() calls do not raise RuntimeError."""
    # After rewrite, nested calls should work (savepoints)

# Live-DB gated test (skip if no PG available)
@pytest.mark.asyncio
@pytest.mark.skipif(not PG_AVAILABLE, reason="No live PG")
async def test_transaction_savepoint_rollback():
    """Inner savepoint rolls back without affecting outer."""
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-926 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `transaction()` is at `postgres.py:830`
4. **Grep for `_in_transaction`** — find all references before removing
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** the rewrite
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-929-transaction-asyncpg-native.md`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any

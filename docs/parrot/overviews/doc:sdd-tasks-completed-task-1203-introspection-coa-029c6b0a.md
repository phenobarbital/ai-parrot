---
type: Wiki Overview
title: 'TASK-1203: Concurrency coalescing for DB introspection'
id: doc:sdd-tasks-completed-task-1203-introspection-coalescing-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: promotion from `NAME_ONLY` to `FULL` in `search_schema` must
relates_to:
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.sql
  rel: mentions
---

# TASK-1203: Concurrency coalescing for DB introspection

**Feature**: FEAT-178 — Database Toolkit Cache Contract & Tool Semantics
**Spec**: `sdd/specs/database-toolkit-cache-contract.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1201
**Assigned-to**: unassigned

---

## Context

`SQLToolkit.describe_table` (TASK-1204) and the on-demand
promotion from `NAME_ONLY` to `FULL` in `search_schema` must
coalesce concurrent identical introspection calls so the same
`(schema, table)` does not hit the DB N times when N parallel
LLM tool calls land simultaneously.

Implements **Module 3** of the spec.

---

## Scope

- Add private state on `SQLToolkit`:
  - `_inflight: Dict[Tuple[str, str], asyncio.Future[Optional[TableMetadata]]]`
  - `_inflight_lock: asyncio.Lock`
- Add private helper `async def _introspect_table_full(self, schema, table) -> Optional[TableMetadata]`:
  - Under `_inflight_lock`: check the map. If a future exists,
    return it (the caller awaits outside the lock). Otherwise
    create a new `asyncio.Future`, register it, release the lock.
  - Outside the lock, call the existing
    `await self._build_table_metadata(schema, table, table_type="BASE TABLE", comment=None)`
    (sql.py:811) which is bounded by the existing `_search_in_database`
    4-way semaphore.
  - On the new `TableMetadata`, set `completeness=Completeness.FULL`
    and `source="information_schema"` (Module 5 / TASK-1205 will
    flip this to `"pg_catalog"` once the new query hooks land).
  - Set the future's result or exception. Remove the entry from
    the map under the lock. Return the value.
- Unit test that two parallel `_introspect_table_full` calls for
  the same key issue exactly one underlying `_build_table_metadata`
  call.

**NOT in scope**: `describe_table` / `search_schema` public method
changes (TASK-1204), `pg_catalog` query rewrites (TASK-1205).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` | MODIFY | Add `_inflight`, `_inflight_lock`, `_introspect_table_full` |
| `packages/ai-parrot/tests/bots/database/test_sql_toolkit_coalescing.py` | CREATE | Unit test for coalescing |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio
from typing import Dict, Optional, Tuple

from parrot.bots.database.models import Completeness, TableMetadata
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py
class SQLToolkit(DatabaseToolkit):                           # line 61
    def __init__(self, ...): ...                              # line 78
    async def _build_table_metadata(
        self, schema, table, table_type, comment=None,
    ) -> Optional[TableMetadata]: ...                         # line 811
    async def _search_in_database(
        self, search_term, schema_name=None, limit=10,
    ) -> List[TableMetadata]: ...                             # line 716  (uses internal 4-way semaphore)
```

### Does NOT Exist
- ~~`SQLToolkit._inflight`~~ — introduced here.
- ~~`SQLToolkit._inflight_lock`~~ — introduced here.
- ~~`SQLToolkit._introspect_table_full`~~ — introduced here.

---

## Implementation Notes

### Pattern (spec §7)
```python
async def _introspect_table_full(
    self, schema: str, table: str,
) -> Optional[TableMetadata]:
    key = (schema, table)

    async with self._inflight_lock:
        existing = self._inflight.get(key)
        if existing is not None:
            future = existing
            owner = False
        else:
            future = asyncio.get_running_loop().create_future()
            self._inflight[key] = future
            owner = True

    if not owner:
        return await future

    try:
        meta = await self._build_table_metadata(
            schema, table, table_type="BASE TABLE",
        )
        if meta is not None:
            meta.completeness = Completeness.FULL
            meta.source = "information_schema"
        future.set_result(meta)
        return meta
    except Exception as exc:        # noqa: BLE001
        future.set_exception(exc)
        raise
    finally:
        async with self._inflight_lock:
            self._inflight.pop(key, None)
```

### Initialise the maps in `__init__`
Add at the end of `SQLToolkit.__init__` (after super init):
```python
self._inflight: Dict[Tuple[str, str], asyncio.Future] = {}
self._inflight_lock = asyncio.Lock()
```
Be careful: `asyncio.Lock()` constructed outside a running loop in
older Python versions binds to the wrong loop. The safest pattern
is lazy init on first use, or use the same approach the rest of
the codebase uses for toolkit locks — grep
`packages/ai-parrot/src/parrot/bots/database/` for existing
`asyncio.Lock()` patterns and follow them.

### `source` value
Set `source="information_schema"` here. TASK-1205 (pg_catalog
migration) will later flip this to `"pg_catalog"` at the same
call site once the query hooks are migrated.

---

## Acceptance Criteria

- [ ] `SQLToolkit` instances expose `_inflight` (dict) and
      `_inflight_lock` (asyncio.Lock) after construction
- [ ] `_introspect_table_full` returns `TableMetadata` with
      `completeness == Completeness.FULL`
- [ ] Two concurrent `_introspect_table_full(schema, table)` calls
      for the same key produce exactly one `_build_table_metadata`
      invocation
- [ ] If `_build_table_metadata` raises, both callers see the same
      exception and the map is cleaned up
- [ ] All existing `SQLToolkit` tests pass
- [ ] New coalescing test passes:
      `pytest packages/ai-parrot/tests/bots/database/test_sql_toolkit_coalescing.py -v`

---

## Test Specification

```python
import asyncio
from unittest.mock import AsyncMock
import pytest

from parrot.bots.database.models import Completeness, TableMetadata
from parrot.bots.database.toolkits.sql import SQLToolkit


@pytest.fixture
def toolkit():
    tk = SQLToolkit.__new__(SQLToolkit)
    tk._inflight = {}
    tk._inflight_lock = asyncio.Lock()
    tk.logger = __import__("logging").getLogger("test")
    return tk


async def test_coalesces_two_concurrent_calls(toolkit):
    call_count = 0

    async def fake_build(schema, table, table_type, comment=None):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return TableMetadata(
            schema=schema, tablename=table, table_type=table_type,
            full_name=f"{schema}.{table}",
        )

    toolkit._build_table_metadata = fake_build

    results = await asyncio.gather(
        toolkit._introspect_table_full("s", "t"),
        toolkit._introspect_table_full("s", "t"),
    )
    assert call_count == 1
    assert all(r.completeness == Completeness.FULL for r in results)


async def test_clears_inflight_on_exception(toolkit):
    async def fake_build(*a, **kw):
        raise RuntimeError("boom")

    toolkit._build_table_metadata = fake_build

    with pytest.raises(RuntimeError):
        await toolkit._introspect_table_full("s", "t")
    assert ("s", "t") not in toolkit._inflight
```

---

## Agent Instructions

1. Confirm TASK-1201 is in `sdd/tasks/completed/`.
2. Re-verify line numbers in `sql.py` — they shift as other tasks
   land.
3. Inspect existing `asyncio.Lock()` usage patterns in the toolkits
   to match initialization style.
4. Implement.
5. Run the new test + existing toolkit tests.
6. Move task file to `completed/` and update the per-spec index.
7. Fill in the Completion Note.

---

## Completion Note

Implemented on branch `feat-178-database-toolkit-cache-contract`.

- Added `Tuple` to typing imports and `Completeness` to models import in `sql.py`.
- Added `_inflight: Dict[Tuple[str, str], asyncio.Future]` and `_inflight_lock: asyncio.Lock` to `SQLToolkit.__init__` (pattern consistent with rest of codebase).
- Added `_introspect_table_full(schema, table)`: coalesces concurrent calls via a future map; owner does the DB call, waiters await the same future; `finally` cleans up the map under the lock.
- Sets `completeness=FULL` and `source="information_schema"` on the result (ready for TASK-1205 to flip to `"pg_catalog"`).
- Done-callback added to the future to suppress asyncio's "Future exception was never retrieved" warning in single-caller exception scenarios.
- Pre-existing E402 lint (regexes before relative imports) fixed by moving constants after imports.
- 7/7 new tests pass with no asyncio warnings; all 59 existing database tests unaffected.

---
type: Wiki Overview
title: 'TASK-1768: PostgresResultStorage Read Methods + DDL Migration'
id: doc:sdd-tasks-completed-task-1768-postgres-result-storage-read-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: implements the four read methods defined in the ABC (TASK-1765) with parameterized
relates_to:
- concept: mod:parrot.bots.flows.core.storage.backends.base
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends.postgres
  rel: mentions
---

# TASK-1768: PostgresResultStorage Read Methods + DDL Migration

**Feature**: FEAT-306 — AgentCrew Saved Crews (Execution Persistence & Replay)
**Spec**: `sdd/specs/agentcrew-saved-crews.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1765
**Assigned-to**: unassigned

---

## Context

`PostgresResultStorage` is the primary backend for production use. This task
implements the four read methods defined in the ABC (TASK-1765) with parameterized
SQL queries against the `crew_executions` table.

Note: The DDL migration for `tenant` and `prompt` columns is handled by TASK-1766.
This task assumes those columns exist and implements the query logic.

Implements spec Module 2 (read methods portion).

---

## Scope

- Implement `list()` in `PostgresResultStorage`:
  - Parameterized SELECT with optional filters (crew_name, method, date_from, date_to)
  - Mandatory tenant + user_id scoping: `WHERE tenant = $1 AND user_id = $2`
  - Support `LIMIT` and `OFFSET` for pagination
  - Order by `timestamp DESC` (newest first)
  - Handle legacy rows where `tenant IS NULL` using `COALESCE(tenant, 'global')`
- Implement `get()`:
  - SELECT by `id` (UUID) with tenant + user_id scoping
  - Return full row including `payload` jsonb
  - Return `None` if not found
- Implement `delete()`:
  - DELETE by `id` with tenant + user_id scoping
  - Return `True` if a row was deleted, `False` otherwise
- Implement `count()`:
  - COUNT(*) with same filters as `list()` (without LIMIT/OFFSET)
- Write unit tests for all four methods

**NOT in scope**: DDL migration (TASK-1766), Redis/DocumentDB backends (TASK-1769/1770).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py` | MODIFY | Add list, get, delete, count methods |
| `tests/unit/test_postgres_result_storage_read.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.core.storage.backends.postgres import PostgresResultStorage  # postgres.py:23
from parrot.bots.flows.core.storage.backends.base import ResultStorage  # base.py:8
from asyncdb import AsyncDB  # used by PostgresResultStorage
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py:23
class PostgresResultStorage(ResultStorage):
    def __init__(self, dsn: Optional[str] = None) -> None: ...  # line 35
    async def _ensure(self) -> AsyncDB: ...  # line 46
    async def _ensure_table(self, conn: AsyncDB, table: str) -> None: ...  # line 53
    async def save(self, collection: str, document: dict[str, Any]) -> None: ...  # line 85
    async def close(self) -> None: ...  # line 131
    # _dsn: str (line 41), _conn: Optional[AsyncDB] (line 42), _initialised: set[str] (line 43)

# _TABLE_RE at line 19: re.compile(r"^[a-z_][a-z0-9_]*$")
# _NAMED_COLUMNS at line 20 (will include "tenant" and "prompt" after TASK-1766)

# AsyncDB query patterns (from save method):
# await conn.execute("SQL", param1, param2, ...)  — positional params with $1, $2, etc.
```

### Does NOT Exist
- ~~`PostgresResultStorage.list()`~~ — does not exist yet; this task creates it
- ~~`PostgresResultStorage.get()`~~ — does not exist yet
- ~~`PostgresResultStorage.delete()`~~ — does not exist yet
- ~~`PostgresResultStorage.count()`~~ — does not exist yet
- ~~`PostgresResultStorage.query()`~~ — no generic query method exists

---

## Implementation Notes

### Pattern to Follow
Follow the existing `save()` method pattern: use `_ensure()` to get the connection,
`_ensure_table()` for DDL, then execute parameterized SQL.

```python
async def list(
    self,
    collection: str,
    filters: dict[str, Any] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    try:
        conn = await self._ensure()
        await self._ensure_table(conn, collection)

        # Build parameterized WHERE clause
        conditions = []
        params = []
        idx = 1

        if filters:
            if filters.get("tenant"):
                conditions.append(f"COALESCE(tenant, 'global') = ${idx}")
                params.append(filters["tenant"])
                idx += 1
            if filters.get("user_id"):
                conditions.append(f"user_id = ${idx}")
                params.append(filters["user_id"])
                idx += 1
            # ... crew_name, method, date_from, date_to

        where = " AND ".join(conditions) if conditions else "TRUE"

        rows = await conn.fetch(
            f"SELECT * FROM {collection} WHERE {where} "
            f"ORDER BY timestamp DESC LIMIT ${idx} OFFSET ${idx+1}",
            *params, limit, offset,
        )
        return [dict(row) for row in rows] if rows else []
    except Exception as exc:
        self.logger.warning("PostgresResultStorage list failed: %s", exc)
        return []
```

### Key Constraints
- All SQL uses `$N` positional placeholders — no string formatting of user input
- Table name validated by `_TABLE_RE` (same as save)
- `conn.fetch()` for SELECT (returns rows), `conn.execute()` for DELETE
- Wrap payloads: `payload` is stored as jsonb; rows returned should include it parsed
- Handle legacy NULL tenant with `COALESCE(tenant, 'global')`

---

## Acceptance Criteria

- [ ] `list()` returns paginated results with tenant+user_id scoping
- [ ] `list()` supports all filters: crew_name, method, date_from, date_to
- [ ] `list()` orders by timestamp DESC
- [ ] `get()` returns single record by UUID with scoping, or None
- [ ] `delete()` removes record by UUID with scoping, returns bool
- [ ] `count()` returns total matching records
- [ ] All SQL uses parameterized queries (no string interpolation of values)
- [ ] Legacy NULL tenant rows handled via COALESCE
- [ ] Tests pass
- [ ] No linting errors

---

## Test Specification

```python
# tests/unit/test_postgres_result_storage_read.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestPostgresResultStorageRead:
    async def test_list_with_filters(self):
        """list() builds correct WHERE clause from filters."""

    async def test_list_pagination(self):
        """list() respects limit and offset."""

    async def test_list_empty_result(self):
        """list() returns empty list when no matches."""

    async def test_get_by_id(self):
        """get() returns record matching UUID."""

    async def test_get_not_found(self):
        """get() returns None when UUID not found."""

    async def test_delete_success(self):
        """delete() removes record and returns True."""

    async def test_delete_not_found(self):
        """delete() returns False when UUID not found."""

    async def test_count_with_filters(self):
        """count() returns correct total with filters."""

    async def test_tenant_coalesce(self):
        """Queries use COALESCE(tenant, 'global') for legacy rows."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1765 must be completed (ABC has list/get/delete/count)
3. **Verify the Codebase Contract** — confirm PostgresResultStorage signatures
4. **Update status** in `sdd/tasks/index/agentcrew-saved-crews.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1768-postgres-result-storage-read.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-14
**Notes**: Implemented `list()`, `get()`, `delete()`, `count()` on `PostgresResultStorage`.
Added two private helpers: `_build_where(filters)` (shared parameterized `WHERE` clause
builder for `list()`/`count()`, with `COALESCE(tenant, 'global')` handling for legacy
NULL-tenant rows) and `_row_to_document(row)` (parses the `payload` jsonb column into a
dict whether the driver returns it as a JSON string or an already-decoded dict, and
stringifies `id`). `delete()` parses the asyncpg-style `"DELETE N"` command-status
string returned by `conn.execute()` to determine whether a row was removed (same pattern
as `parrot/storage/backends/postgres.py::delete_thread_cascade`). All methods wrap
backend errors in `try/except`, log via `self.logger.warning`, and return the ABC's
documented "nothing happened" default (`[]` / `None` / `False` / `0`). Created
`tests/unit/test_postgres_result_storage_read.py` covering all 9 scenarios from the
task's Test Specification plus 4 additional exception-handling tests for parity with
`test_postgres_backend.py`'s coverage style. 21/21 new+existing postgres tests pass;
50/50 pass across the full storage test slice touched by TASK-1765/1766/1768. `ruff
check` clean.

**Deviations from spec**: The ABC's `get(self, collection, record_id)` and
`delete(self, collection, record_id)` signatures (fixed by TASK-1765, matching the
spec's own Codebase Contract) take no `tenant`/`user_id` parameters, so this task's
scope note ("SELECT/DELETE by id with tenant + user_id scoping") could not be
implemented at the SQL level for `get()`/`delete()` without inventing a signature the
ABC doesn't have. `list()` and `count()` DO enforce tenant/user_id scoping via the
`filters` dict exactly as specified. Per-record `get()`/`delete()` scope only by
`record_id`; ownership/tenant verification for those two operations is deferred to the
service layer (TASK-1772 `SavedExecutionService`), which already receives `tenant`
and `user_id` on every call and can check them against the fetched row before
returning/deleting. Flagging for spec review — if per-record scoping in SQL is
required, the ABC signature would need `tenant`/`user_id` params added in a follow-up.

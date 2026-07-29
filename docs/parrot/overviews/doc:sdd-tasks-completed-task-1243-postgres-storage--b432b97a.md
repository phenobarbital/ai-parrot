---
type: Wiki Overview
title: 'TASK-1243: PostgresFormStorage Self-Managed Pool'
id: doc:sdd-tasks-completed-task-1243-postgres-storage-self-managed-pool-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task refactors `PostgresFormStorage` in the parrot-formdesigner package
---

# TASK-1243: PostgresFormStorage Self-Managed Pool

**Feature**: FEAT-185 — Refactor FormRegistry
**Spec**: `sdd/specs/refactor-formregistry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1242
**Assigned-to**: unassigned

---

## Context

This task refactors `PostgresFormStorage` in the parrot-formdesigner package
to manage its own asyncpg connection pool lifecycle. Currently the constructor
requires a pre-created `asyncpg.Pool` instance, pushing pool creation and
cleanup onto the caller. After this change, callers can construct the storage
with connection parameters alone and let `initialize()` / `close()` handle
the pool.

Implements spec §3 Module 2.

---

## Scope

- Refactor `PostgresFormStorage.__init__` to accept:
  - `pool: Any | None = None` — optional pre-created pool
  - `dsn: str | None = None` — asyncpg DSN string
  - `schema`, `table_name`, `tenant` — same as before (keep defaults)
  - `min_size: int = 2`, `max_size: int = 10` — pool sizing
  - `**pool_kwargs` — forwarded to `asyncpg.create_pool()`
- Add `_owns_pool: bool` flag — `True` when pool is created internally,
  `False` when provided externally.
- Refactor `initialize()`:
  - If `self._pool is None`, call `asyncpg.create_pool(dsn=self._dsn, ...)`.
  - Then run the CREATE TABLE DDL (existing behavior).
- Add `async def close(self) -> None`:
  - If `self._owns_pool` and `self._pool` is not None, call `await self._pool.close()`.
  - Set `self._pool = None`.
  - Idempotent — calling twice must not raise.
- All existing methods (`save`, `load`, `delete`, `list_forms`) continue to
  use `self._pool.acquire()` — no changes needed there.

**NOT in scope**: FormRegistry changes (TASK-1242), core package mirror
(TASK-1244), tests (TASK-1246).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py` | MODIFY | Refactor constructor, update `initialize()`, add `close()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_formdesigner.services.storage import PostgresFormStorage  # verified: services/storage.py:55
from parrot_formdesigner.services.registry import FormStorage         # verified: services/registry.py:35
from parrot_formdesigner.services._identifiers import validate_identifier, qualified_table  # verified: _identifiers.py:23,43
from parrot_formdesigner.core.schema import FormSchema                # verified via storage.py:46
from parrot_formdesigner.core.style import StyleSchema                # verified via storage.py:47

import asyncpg  # TYPE_CHECKING import in storage.py:33; runtime import needed for create_pool
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py
class PostgresFormStorage(FormStorage):                    # line 55
    def __init__(
        self,
        pool: Any,
        *,
        schema: str = DEFAULT_SCHEMA,      # "navigator"
        table_name: str = DEFAULT_TABLE,   # "form_schemas"
        tenant: str | None = None,
    ) -> None:                                             # line 74
    _pool: Any                                             # line 87
    _schema: str                                           # line 88
    _table: str                                            # line 89
    _tenant: str | None                                    # line 90
    logger: logging.Logger                                 # line 91

    def _resolve_schema(self, tenant) -> str:              # line 97
    def _qualified(self, tenant) -> str:                   # line 109
    def _create_table_sql(self, tenant) -> str:            # line 116
    async def initialize(self, *, tenant=None) -> None:    # line 185
    async def save(self, form, style=None, *, created_by=None, tenant=None) -> str:  # line 204
    async def load(self, form_id, version=None, *, tenant=None):  # line 249
    async def delete(self, form_id, *, tenant=None) -> bool:  # line 304
    async def list_forms(self, *, tenant=None) -> list[dict[str, Any]]:  # line 329

DEFAULT_SCHEMA = "navigator"   # line 51
DEFAULT_TABLE = "form_schemas" # line 52

# asyncpg API
asyncpg.create_pool(dsn=..., min_size=..., max_size=..., **kwargs) -> asyncpg.Pool
pool.close()  # graceful shutdown — waits for all connections to be released
pool.acquire() -> asyncpg.Connection  # context manager
```

### Does NOT Exist

- ~~`PostgresFormStorage.close()`~~ — does not exist yet; you are adding it
- ~~`PostgresFormStorage._owns_pool`~~ — does not exist yet; you are adding it
- ~~`PostgresFormStorage._dsn`~~ — does not exist yet; you are adding it
- ~~`PostgresFormStorage._pool_kwargs`~~ — does not exist yet; you are adding it
- ~~`asyncpg.Pool.terminate()`~~ — exists but prefer `close()` for graceful shutdown

---

## Implementation Notes

### Pattern to Follow

```python
# Reference: how app.py currently creates the pool (app.py:290-292)
pool = await asyncpg.create_pool(dsn=default_dsn)
```

```python
# Reference: existing initialize() at storage.py:185
async def initialize(self, *, tenant: str | None = None) -> None:
    sql = self._create_table_sql(tenant)
    async with self._pool.acquire() as conn:
        await conn.execute(sql)
```

### Key Constraints

- When `pool` is provided at construction, `_owns_pool = False` and `close()`
  must NOT close it.
- When `pool` is None, `_pool` is set to None until `initialize()` is called.
  Any method called before `initialize()` will raise `AttributeError` on
  `self._pool.acquire()` — this is acceptable (initialize is required).
- `close()` must be idempotent. Set `self._pool = None` after closing.
- The `dsn` parameter takes precedence. If neither `dsn` nor `pool` is
  provided, `initialize()` should attempt `asyncpg.create_pool()` with no
  DSN (asyncpg falls back to libpq env vars / defaults).
- Keep the `import asyncpg` as a runtime import inside `initialize()` to
  preserve the lazy-import pattern. Add `asyncpg` to TYPE_CHECKING as well.

---

## Acceptance Criteria

- [ ] `PostgresFormStorage(schema=..., table_name=..., tenant=...)` constructs without pool
- [ ] `PostgresFormStorage(pool=existing_pool)` still works (backward compat)
- [ ] `PostgresFormStorage(dsn="postgresql://...")` stores the DSN for later use
- [ ] `initialize()` creates the pool when none was provided
- [ ] `initialize()` still runs CREATE TABLE DDL
- [ ] `close()` closes the pool when `_owns_pool is True`
- [ ] `close()` does NOT close an externally-provided pool
- [ ] `close()` is idempotent (no error on double-call)
- [ ] All existing methods work unchanged after `initialize()`

---

## Test Specification

```python
# Tests are in TASK-1246 — this section shows expected behavior.
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


async def test_storage_no_pool():
    """Can construct without pool; pool is None until initialize."""
    from parrot_formdesigner.services.storage import PostgresFormStorage
    storage = PostgresFormStorage(schema="test", table_name="forms")
    assert storage._pool is None
    assert storage._owns_pool is True


async def test_storage_with_pool():
    """External pool is used; _owns_pool is False."""
    from parrot_formdesigner.services.storage import PostgresFormStorage
    mock_pool = AsyncMock()
    storage = PostgresFormStorage(pool=mock_pool, schema="test")
    assert storage._pool is mock_pool
    assert storage._owns_pool is False


async def test_close_idempotent():
    """close() twice does not raise."""
    from parrot_formdesigner.services.storage import PostgresFormStorage
    storage = PostgresFormStorage(schema="test")
    storage._pool = AsyncMock()
    storage._owns_pool = True
    await storage.close()
    await storage.close()  # no error
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/refactor-formregistry.spec.md` for full context
2. **Check dependencies** — verify TASK-1242 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `FormStorage.close()` now exists (added by TASK-1242)
4. **Implement** the changes in `storage.py` following the scope above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-1243-postgres-storage-self-managed-pool.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: SDD Worker (claude-sonnet-4-6)
**Date**: 2026-05-19
**Notes**: Refactored `__init__` to keyword-only with `pool: Any | None = None`, added `dsn`, `min_size`, `max_size`, `**pool_kwargs`. Added `_owns_pool` flag (True when pool is None at construction). Updated `initialize()` to create asyncpg pool via lazy `import asyncpg` when no pool is set. Added `close()` method that is idempotent and only closes pool when `_owns_pool is True`.

**Deviations from spec**: none

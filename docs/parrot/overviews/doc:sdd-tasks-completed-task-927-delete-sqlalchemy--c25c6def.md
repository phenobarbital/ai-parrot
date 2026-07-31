---
type: Wiki Overview
title: 'TASK-927: Delete SQLAlchemy Backend Path'
id: doc:sdd-tasks-completed-task-927-delete-sqlalchemy-backend-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 2 of the spec. The `backend="sqlalchemy"` code path has
relates_to:
- concept: mod:parrot.bots.database.toolkits.base
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.postgres
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.sql
  rel: mentions
---

# TASK-927: Delete SQLAlchemy Backend Path

**Feature**: FEAT-118 — Database Toolkit asyncpg Native Boundary Refactor
**Spec**: `sdd/specs/database-toolkit-asyncpg-boundary-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-926
**Assigned-to**: unassigned

---

## Context

Implements Module 2 of the spec. The `backend="sqlalchemy"` code path has
**zero production callers** (verified via repo-wide grep). It forces
maintaining two execution routes and two parameter styles. Per lead
directive: hard remove, no deprecation cycle.

This also includes BigQueryToolkit's `_build_sqlalchemy_dsn` override, since
BigQuery will use asyncdb natively (Q-A decision).

---

## Scope

- Remove `backend` field from `DatabaseToolkitConfig` and `DatabaseToolkit.__init__`.
- Remove `self.backend` attribute and all `if self.backend == ...` branches.
- Delete `_connect_sqlalchemy`, `_build_sqlalchemy_dsn` in `base.py`.
- Delete `_execute_sqlalchemy` in `sql.py`.
- Delete `_build_sqlalchemy_dsn` overrides in `postgres.py` and `bigquery.py`.
- Delete all `self.backend == "sqlalchemy"` branches in `sql.py` (`execute_query`,
  `_explain`, `_search_in_database`, `_build_table_metadata`).
- Remove `self._engine` attribute and its disposal in `stop()`.
- Remove `backend` param from `SQLToolkit.__init__` and `PostgresToolkit.__init__`
  and `BigQueryToolkit.__init__`.
- Remove SQLAlchemy-mentioning docstrings.
- Update existing unit tests that reference `backend="sqlalchemy"` to assert
  `TypeError` (kwarg no longer accepted).

**NOT in scope**: query-builder param normalisation (TASK-928), transaction
rewrite (TASK-929), NavigatorToolkit cleanup (TASK-930).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/toolkits/base.py` | MODIFY | Remove `backend` field, `_engine`, `_connect_sqlalchemy`, `_build_sqlalchemy_dsn`, all backend branches |
| `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` | MODIFY | Remove `backend` param, `_execute_sqlalchemy`, all backend branches |
| `packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py` | MODIFY | Remove `backend` param, `_build_sqlalchemy_dsn` |
| `packages/ai-parrot/src/parrot/bots/database/toolkits/bigquery.py` | MODIFY | Remove `backend` param, `_build_sqlalchemy_dsn` |
| `tests/unit/test_sql_toolkit.py` | MODIFY | Update `backend="sqlalchemy"` tests |
| `tests/unit/test_database_toolkit_base.py` | MODIFY | Update `backend="sqlalchemy"` tests |
| `tests/unit/test_postgres_toolkit.py` | MODIFY | Update `backend="sqlalchemy"` tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Locations to Delete/Modify

```python
# base.py — DELETE these:
# line 58:  backend: str = Field(default="asyncdb", ...)  (in DatabaseToolkitConfig)
# line 115: backend: str = "asyncdb",  (in __init__)
# line 133: self.backend = backend
# line 144: self._engine: Any = None
# line 212-214: docstring mentioning sqlalchemy
# line 219-224: if self.backend == "asyncdb" / elif == "sqlalchemy" branches in start()
# line 248-253: self._engine disposal in stop()
# line 271-284: backend branches in health_check()
# line 401-406: _connect_sqlalchemy() method
# line 424-431: _build_sqlalchemy_dsn() method

# sql.py — DELETE these:
# line 66:  backend: str = "asyncdb", (in __init__)
# line 78:  backend=backend, (in super().__init__ call)
# line 195-198: backend branch in execute_query()
# line 242-245: backend branch in _explain()
# line 510-536: _execute_sqlalchemy() method
# line 550-551: if self.backend == "asyncdb" in _search_in_database()
# line 555-558: else branch (sqlalchemy) in _search_in_database()
# line 592-595: backend branches in _build_table_metadata() (columns)
# line 609-612: backend branches in _build_table_metadata() (primary keys)
# line 622-625: backend branches in _build_table_metadata() (unique constraints)

# postgres.py — DELETE these:
# line 48:  backend: str = "asyncdb", (in __init__)
# line 83:  backend=backend, (in super().__init__ call)
# line 150-156: _build_sqlalchemy_dsn() override

# bigquery.py — DELETE these:
# line 30:  backend: str = "asyncdb", (in __init__)
# line 43:  backend=backend, (in super().__init__ call)
# line 117-121: _build_sqlalchemy_dsn() override
```

### Existing Signatures (after cleanup)

```python
# base.py DatabaseToolkit.__init__ — AFTER removal:
def __init__(
    self,
    dsn: str,
    allowed_schemas: Optional[List[str]] = None,
    primary_schema: Optional[str] = None,
    tables: Optional[List[str]] = None,
    read_only: bool = True,
    cache_partition: Optional[CachePartition] = None,
    retry_config: Optional[QueryRetryConfig] = None,
    database_type: str = "postgresql",
    use_pool: bool = False,
    pool_params: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> None:

# base.py start() — AFTER removal:
async def start(self) -> None:
    if self._connected:
        return
    await self._connect_asyncdb()
    self._connected = True
    ...

# base.py stop() — AFTER removal:
async def stop(self) -> None:
    if self._connection is not None:
        await self._connection.close()
        self._connection = None
    self._connected = False
    # No self._engine disposal

# base.py health_check() — AFTER removal:
async def health_check(self) -> bool:
    if not self._connected:
        return False
    if self._connection is not None:
        if hasattr(self._connection, "test_connection"):
            return await self._connection.test_connection()
        return True
    return False
```

### Does NOT Exist
- ~~`backend="asyncdb"` kwarg after removal~~ — no backend kwarg at all
- ~~`DeprecationWarning` for backend~~ — hard remove per lead directive
- ~~`self._engine` after cleanup~~ — deleted entirely
- ~~`_execute_sqlalchemy` after cleanup~~ — deleted entirely

---

## Implementation Notes

### Pattern
For each backend branch, remove the entire `if/elif/else` and keep only the
asyncdb path (now the only path). Example:

```python
# BEFORE:
if self.backend == "asyncdb":
    data, error = await self._execute_asyncdb(sql)
else:
    data, error = await self._execute_sqlalchemy(sql)

# AFTER:
data, error = await self._execute_asyncdb(sql)
```

### Key Constraints
- Do NOT add a `DeprecationWarning`. Hard remove.
- `DatabaseToolkitConfig` Pydantic model must also lose the `backend` field.
- Test files should assert that passing `backend=` raises `TypeError`.
- Do NOT remove `sqlalchemy` from `pyproject.toml` yet (deferred to TASK-930).

---

## Acceptance Criteria

- [ ] `backend` kwarg removed from all `__init__` signatures
- [ ] `DatabaseToolkit(dsn="...", backend="sqlalchemy")` raises `TypeError`
- [ ] No `sqlalchemy` imports at module level in `base.py`, `sql.py`, `postgres.py`
- [ ] `_connect_sqlalchemy`, `_execute_sqlalchemy`, `_build_sqlalchemy_dsn` deleted
- [ ] `self._engine` attribute removed
- [ ] All `if self.backend == ...` branches removed
- [ ] Existing tests updated — `test_backend_kwarg_removed` passes
- [ ] `test_no_sqlalchemy_imports_at_module_level` passes

---

## Test Specification

```python
# Update in tests/unit/test_database_toolkit_base.py
def test_backend_kwarg_removed():
    """backend= kwarg no longer accepted."""
    with pytest.raises(TypeError):
        SomeConcreteToolkit(dsn="postgresql://localhost/test", backend="sqlalchemy")

# New test (can go in existing test file or new one)
def test_no_sqlalchemy_imports_at_module_level():
    """sqlalchemy must not be imported at module level."""
    import importlib
    import sys
    for mod_name in [
        "parrot.bots.database.toolkits.base",
        "parrot.bots.database.toolkits.sql",
        "parrot.bots.database.toolkits.postgres",
    ]:
        mod = importlib.import_module(mod_name)
        source = inspect.getsource(mod)
        # Only top-level imports matter; local imports inside deleted methods are gone
        assert "from sqlalchemy" not in source.split("def ")[0]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-926 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm line numbers still match
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** — delete all SQLAlchemy code paths systematically
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-927-delete-sqlalchemy-backend.md`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-29
**Notes**: All SQLAlchemy code paths hard-removed from base.py, sql.py, postgres.py,
bigquery.py. `backend=` kwarg raises TypeError via explicit guard in
DatabaseToolkit.__init__. DatabaseToolkitConfig has no backend field.
`_connect_sqlalchemy`, `_execute_sqlalchemy`, `_build_sqlalchemy_dsn` deleted.
`self._engine` removed. All `if self.backend == ...` branches removed.
Existing tests updated: `test_backend_kwarg_removed` + `test_no_sqlalchemy_imports_at_module_level`
both pass. All 78 unit tests pass.

**Deviations from spec**: none

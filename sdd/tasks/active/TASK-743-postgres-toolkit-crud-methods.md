# TASK-743: PostgresToolkit CRUD tool methods + template cache + transaction + reload_metadata

**Feature**: FEAT-106 — NavigatorToolkit ↔ PostgresToolkit Interaction
**Spec**: `sdd/specs/navigatortoolkit-postgrestoolkit-interaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-739, TASK-740, TASK-741, TASK-742
**Assigned-to**: unassigned

---

## Context

This is the centerpiece of the feature. `PostgresToolkit` gains five
LLM-callable CRUD tools (`insert_row`, `upsert_row`, `update_row`,
`delete_row`, `select_rows`), a per-instance SQL template cache, a
`transaction()` async context manager, and a `reload_metadata()` hook —
all wired to the primitives built in TASK-739..742.

Implements **Module 5** of the spec.

---

## Scope

### Template cache + helpers

- Initialize `self._prepared_cache: Dict[str, str] = {}` at the **top**
  of `PostgresToolkit.__init__`, BEFORE `super().__init__(**kwargs)`.
- Add `self._json_cols_cache: Dict[str, FrozenSet[str]] = {}` alongside.
- Add private helper
  `_resolve_table(self, table: str) -> tuple[str, str, TableMetadata]`:
  - Accept `"schema.table"` or `"table"` (the latter uses
    `self.primary_schema`).
  - Reject (`ValueError`) if the resolved `"schema.table"` is not in
    `self.tables`.
  - Look up `TableMetadata` via `self.cache_partition.get_table_metadata`
    or (when `cache_partition` is None) via `_build_table_metadata`.
  - Return `(schema, table, meta)`.
- Add private helper
  `_get_or_build_template(self, op, schema, table, **kwargs) -> tuple[str, list[str]]`:
  - Key = hashable shape of all kwargs (conflict_cols, update_cols,
    columns, where_columns, returning, order_by, limit). Convert lists
    to tuples, None to `()`.
  - On miss, dispatch to `_crud._build_{op}_sql(...)` with `json_cols`
    computed from `meta.columns`.
  - Store the resulting `sql` string in `self._prepared_cache`
    (the `param_order` list is recomputed on each call — cheap).
- Add private helper `_get_or_build_pydantic_model(self, meta) -> Type[BaseModel]`:
  - `name = f"{meta.schema}_{meta.tablename}_model"`.
  - `key = _crud._columns_key_from_metadata(meta)`.
  - Return `_crud._build_pydantic_model(name, key)` (cached globally).

### CRUD methods (tool signatures — see spec §2)

For each of `insert_row`, `upsert_row`, `update_row`, `delete_row`,
`select_rows`:

1. `_resolve_table(table)` → schema, table, meta.
2. Validate `data` (or `where`) through the dynamic Pydantic model;
   `.model_dump(exclude_none=True)` to drop None defaults.
3. For `upsert_row`: default `conflict_cols` to `meta.primary_keys` when
   None; default `update_cols` to `[c for c in data.keys() if c not in conflict_cols]`.
4. Compute `param_order` + `sql` via `_get_or_build_template`.
5. For `update_row` / `delete_row`: call
   `QueryValidator.validate_sql_ast(sql, dialect="postgres", read_only=False, require_pk_in_where=True, primary_keys=meta.primary_keys)`.
   Reject with `RuntimeError` on failure (log the validator's message).
6. Bind args: `tuple(data[c] if c in data else where[c] for c in param_order)`.
   JSON columns (identified via `meta.columns`) get `json.dumps(value)`.
7. Execute:
   - Use `conn` if caller passed one; otherwise `async with self._connection() as conn:`
     (the asyncdb pool). Verify the exact acquisition pattern by
     reading `SQLToolkit._execute_asyncdb` (sql.py:451).
   - `returning` is None → `await conn.execute(sql, *args)`; return
     `{"status": "ok"}`.
   - `returning` is non-None + single-row ops → `await conn.fetchrow(sql, *args)`;
     return `dict(row)` or `{}` when None.
   - `select_rows` → `await conn.fetch(sql, *args)` → `[dict(r) for r in rows]`.
8. For `upsert_row` with RETURNING yielding 0 rows (i.e., the
   DO UPDATE fired against an identical row so RETURNING was empty):
   perform a follow-up SELECT using `conflict_cols` to return the
   existing row — per spec Q2 (formalize idempotency).

### transaction() context manager

```python
@asynccontextmanager
async def transaction(self) -> AsyncIterator[Any]:
    """Yield an asyncdb connection inside a transaction block.

    Commits on normal exit, rolls back on exception. Nested calls raise
    RuntimeError — only top-level transactions are supported.
    """
    ...
```

- Guard against nesting: set `self._in_transaction = False` in `__init__`;
  enter → if True, raise `RuntimeError`; set True; yield.
- On exception inside the `async with`, roll back and re-raise.
- Use the asyncdb `pg` driver's `conn.transaction()` — verify shape by
  reading `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py`.

### reload_metadata(schema, table)

```python
async def reload_metadata(self, schema: str, table: str) -> None:
    """Purge cached metadata + templates for (schema, table)."""
```

- Delete from `self.cache_partition.schema_cache[schema].tables.pop(table, None)`
  (verify exact path — might be `schema_cache[schema].tables` or
  `.table_metadata`).
- Purge the matching `hot_cache` entry.
- Drop every key in `self._prepared_cache` that starts with
  `f"{op}|{schema}|{table}|"` (design the key format accordingly).
- Clear the global Pydantic cache: `_crud._build_pydantic_model.cache_clear()`
  and log `self.logger.info("Cleared Pydantic model cache — %d entries", previous_size)`.
- Do NOT eagerly re-warm; the next CRUD call triggers lazy re-warm via
  `_resolve_table → _build_table_metadata`.

### `read_only` tool gating

- In `PostgresToolkit.__init__`, BEFORE `super().__init__(**kwargs)`:
  ```python
  self._prepared_cache: Dict[str, str] = {}
  self._json_cols_cache: Dict[str, FrozenSet[str]] = {}
  self._in_transaction: bool = False
  extra_excludes: tuple[str, ...] = ()
  if read_only:
      extra_excludes = ("insert_row", "upsert_row", "update_row", "delete_row")
  # Merge into class attr via instance attr to override class-level
  self.exclude_tools = tuple(SQLToolkit.exclude_tools) + extra_excludes
  ```
- CRITICAL: this must happen BEFORE `AbstractToolkit._generate_tools()`
  runs (which is called from inside `super().__init__`). Verify the
  call chain by reading `tools/toolkit.py` lines 286–321.

**NOT in scope**:
- Refactoring `NavigatorToolkit` — TASK-744.
- `examples/navigator_agent.py` — TASK-745.
- Integration tests against a live PG — TASK-746.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py` | MODIFY | Add CRUD methods, template cache, `transaction()`, `reload_metadata()`, read_only gating |
| `tests/unit/test_postgres_toolkit.py` | CREATE or EXTEND | Tests per spec §4 Module 5 rows |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
import json
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any, AsyncIterator, FrozenSet, Type

from pydantic import BaseModel, ValidationError

from parrot.bots.database.toolkits.sql import SQLToolkit
# verified at: packages/ai-parrot/src/parrot/bots/database/toolkits/__init__.py:10

from parrot.bots.database.models import TableMetadata
# verified at: packages/ai-parrot/src/parrot/bots/database/models.py:106

from parrot.bots.database.cache import CachePartition
# verified at: packages/ai-parrot/src/parrot/bots/database/cache.py:45

from parrot.security import QueryValidator
# verified at: packages/ai-parrot/src/parrot/security/__init__.py:11
# NOTE: validate_sql_ast gains kwargs require_pk_in_where / primary_keys via TASK-739

from parrot.bots.database.toolkits._crud import (
    _build_pydantic_model,
    _columns_key_from_metadata,
    _build_insert_sql,
    _build_upsert_sql,
    _build_update_sql,
    _build_delete_sql,
    _build_select_sql,
)
# Created by TASK-741 + TASK-742
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py
class PostgresToolkit(SQLToolkit):
    def __init__(                                               # line 22
        self,
        dsn: str,
        allowed_schemas: Optional[List[str]] = None,
        primary_schema: Optional[str] = None,
        tables: Optional[List[str]] = None,
        read_only: bool = True,
        backend: str = "asyncdb",
        **kwargs: Any,
    ) -> None:
        # ADD to the top of this body (before super().__init__):
        #   self._prepared_cache, self._json_cols_cache, self._in_transaction
        #   self.exclude_tools extension when read_only=True
        ...
    def _get_asyncdb_driver(self) -> str: ...                   # line 111 — returns "pg"
```

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py
class SQLToolkit(DatabaseToolkit):
    exclude_tools: tuple[str, ...] = (                          # line 51
        "start", "stop", "cleanup", "get_table_metadata", "health_check",
    )
    async def execute_query(                                    # line 162 — DO NOT CHANGE
        self, query: str, limit: int = 1000, timeout: int = 30,
    ) -> QueryExecutionResponse: ...
    async def _execute_asyncdb(                                 # line 451 — reference for connection acquisition pattern
        self, sql: str, limit: int = 1000, timeout: int = 30,
    ) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]: ...
    async def _build_table_metadata(                            # line 545
        self, schema: str, table: str, table_type: str, comment: Optional[str] = None,
    ) -> Optional[TableMetadata]: ...
```

```python
# packages/ai-parrot/src/parrot/bots/database/cache.py
class CachePartition:                                           # line 45
    # Relevant methods:
    async def get_table_metadata(self, schema, table) -> Optional[TableMetadata]: ...
    async def store_table_metadata(self, metadata: TableMetadata) -> None: ...
    # Internal state:
    #   self.hot_cache: TTLCache
    #   self.schema_cache: Dict[str, SchemaMetadata]
```

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    exclude_tools: tuple[str, ...] = ()                         # line 177
    def _generate_tools(self) -> None:                          # line 286
        # Reads self.exclude_tools ONCE during __init__.
        # Therefore extensions MUST happen BEFORE super().__init__ runs.
```

### Does NOT Exist

- ~~`PostgresToolkit.insert_row` / `upsert_row` / `update_row` / `delete_row` / `select_rows`~~ — this task creates them.
- ~~`PostgresToolkit.transaction()`~~ — this task creates it.
- ~~`PostgresToolkit.reload_metadata()`~~ — this task creates it.
- ~~`SQLToolkit._whitelist_check`~~ — no existing whitelist enforcement; the new `_resolve_table` fills the gap.
- ~~`asyncdb.AsyncDB.connection().__aenter__`~~ — verify the actual API: it may be `async with self._connection()` where `self._connection` is the AsyncDB instance returned by `_connect_asyncdb` (base.py:336). Read `_execute_asyncdb` (sql.py:451) to see the exact acquisition idiom.
- ~~`conn.fetchrow()` returning a dict~~ — asyncpg returns `Record`. Cast with `dict(row)` before returning.
- ~~`CachePartition.delete_table(schema, table)`~~ — no such method; delete directly from `schema_cache[schema].tables` dict.

---

## Implementation Notes

### Cache-key format

```
<op>|<schema>|<table>|<json_key_tuple>

e.g.:
  insert|auth|programs|('a','b','c')|ret=('id',)
  upsert|auth|programs|cols=('a','b','c')|conflict=('program_slug',)|update=('a','b')|ret=('id',)
  update|auth|programs|set=('a',)|where=('program_id',)|ret=()
  delete|auth|programs|where=('program_id',)|ret=('program_id',)
  select|auth|programs|cols=('*',)|where=('active',)|order=('created_at DESC',)|limit=10
```

Keep keys human-readable for log-based debugging. Use `json.dumps` with
`sort_keys=True` only if a short textual repr is insufficient.

### JSON column handling

```python
def _json_cols_for(self, meta: TableMetadata) -> FrozenSet[str]:
    key = f"{meta.schema}.{meta.tablename}"
    cached = self._json_cols_cache.get(key)
    if cached is not None:
        return cached
    cols = frozenset(
        c["name"] for c in meta.columns
        if (c.get("type") or "").lower() in {"json", "jsonb", "hstore"}
    )
    self._json_cols_cache[key] = cols
    return cols
```

Then in execution: for every element of `param_order` that is a JSON
column, apply `json.dumps(value)` before binding.

### Key Constraints

- `exclude_tools` extension MUST happen before `super().__init__`.
- `_resolve_table` MUST normalize to lowercase for both schema and table
  names before whitelist comparison (PG convention — verify against
  existing `tables` values in NavigatorToolkit).
- Never pass user data into SQL via concatenation — only through asyncpg
  positional binds.
- Log (DEBUG) on template cache hits/misses so operators can validate
  cache hit rates.
- Transactions yield the **same** `conn` object that CRUD methods
  accept via `conn=` kwarg. The CRUD method must branch:
  `conn = external_conn or await self._acquire_conn()`.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py:451` — connection acquisition idiom (`_execute_asyncdb`)
- `packages/ai-parrot/src/parrot/tools/toolkit.py:286` — `_generate_tools` timing
- `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py:600-700` — existing SQL patterns being superseded

---

## Acceptance Criteria

- [ ] `PostgresToolkit(dsn=…, tables=[…], read_only=False).get_tools()` exposes `db_insert_row`, `db_upsert_row`, `db_update_row`, `db_delete_row`, `db_select_rows` (prefix `db` inherited from `DatabaseToolkit.tool_prefix`).
- [ ] `read_only=True` → `get_tools()` contains `db_select_rows` only (no write tools).
- [ ] CRUD methods reject writes to tables not in `self.tables` with `ValueError` including the rejected `schema.table`.
- [ ] Unknown field in `data` → `pydantic.ValidationError`.
- [ ] `upsert_row(..., conflict_cols=None)` defaults to `meta.primary_keys`.
- [ ] `update_row` / `delete_row` pass `require_pk_in_where=True, primary_keys=meta.primary_keys` to `QueryValidator.validate_sql_ast`.
- [ ] Second call with identical shape → `_prepared_cache` hit (mock asserts `_build_*_sql` called once).
- [ ] `async with toolkit.transaction() as tx:` yields a connection; exception → rollback; success → commit; nested `transaction()` raises `RuntimeError`.
- [ ] `reload_metadata(schema, table)` purges entries from `cache_partition`, `_prepared_cache`, and calls `_build_pydantic_model.cache_clear()`.
- [ ] `upsert_row` with `returning=[…]` returns the row even when DO UPDATE fires against an identical row (via auto-SELECT fallback).
- [ ] `pytest tests/unit/test_postgres_toolkit.py -v` passes all new assertions.

---

## Test Specification

Minimum coverage (add more as needed):

```python
# tests/unit/test_postgres_toolkit.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pydantic import ValidationError
from parrot.bots.database.toolkits.postgres import PostgresToolkit
from parrot.bots.database.models import TableMetadata


@pytest.fixture
def fake_meta() -> TableMetadata:
    return TableMetadata(
        schema="test", tablename="t", table_type="BASE TABLE",
        full_name='"test"."t"',
        columns=[
            {"name": "id", "type": "integer", "nullable": False, "default": None},
            {"name": "name", "type": "varchar", "nullable": False, "default": None},
            {"name": "data", "type": "jsonb", "nullable": True, "default": "'{}'"},
        ],
        primary_keys=["id"],
    )


class TestPostgresToolkitCrud:
    def test_read_only_hides_write_tools(self):
        tk = PostgresToolkit(dsn="postgres://x", tables=["test.t"], read_only=True)
        names = [t.name for t in tk.get_tools()]
        assert "db_select_rows" in names
        for tool_name in ("db_insert_row", "db_upsert_row", "db_update_row", "db_delete_row"):
            assert tool_name not in names

    def test_read_only_false_exposes_write_tools(self):
        tk = PostgresToolkit(dsn="postgres://x", tables=["test.t"], read_only=False)
        names = [t.name for t in tk.get_tools()]
        for tool_name in (
            "db_insert_row", "db_upsert_row", "db_update_row",
            "db_delete_row", "db_select_rows",
        ):
            assert tool_name in names

    @pytest.mark.asyncio
    async def test_insert_row_whitelist_rejection(self, fake_meta):
        tk = PostgresToolkit(dsn="postgres://x", tables=["test.t"], read_only=False)
        with pytest.raises(ValueError, match="public.foo"):
            await tk.insert_row("public.foo", {"a": 1})

    @pytest.mark.asyncio
    async def test_insert_row_validates_input(self, fake_meta):
        tk = PostgresToolkit(dsn="postgres://x", tables=["test.t"], read_only=False)
        # Patch _resolve_table to return fake_meta
        with patch.object(tk, "_resolve_table", return_value=("test", "t", fake_meta)):
            with pytest.raises(ValidationError):
                await tk.insert_row("test.t", {"nope": 1})

    @pytest.mark.asyncio
    async def test_upsert_row_template_cached_on_second_call(self, fake_meta):
        tk = PostgresToolkit(dsn="postgres://x", tables=["test.t"], read_only=False)
        # ... mock _resolve_table, mock asyncdb conn; assert _build_upsert_sql called once
        ...

    @pytest.mark.asyncio
    async def test_transaction_commits_and_rolls_back(self):
        ...

    @pytest.mark.asyncio
    async def test_reload_metadata_clears_entries(self, fake_meta):
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — especially Section 2 (public interfaces), Section 3 Module 5, and Section 7 (Known Risks — `exclude_tools` timing, asyncdb RETURNING, extra="forbid")
2. **Check dependencies** — TASK-739, 740, 741, 742 all `done` in `tasks/completed/`
3. **Verify the Codebase Contract** — critical. Confirm:
   - `validate_sql_ast` now accepts `require_pk_in_where` / `primary_keys` (TASK-739)
   - `TableMetadata.unique_constraints` exists (TASK-740)
   - `_crud._build_pydantic_model` / template builders exist and return the documented shapes (TASK-741, TASK-742)
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** one tool at a time. Unit-test after each. Coordinate the `exclude_tools` mutation **before** `super().__init__`.
6. **Verify** every acceptance criterion
7. **Move this file** to `tasks/completed/TASK-743-postgres-toolkit-crud-methods.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any

# Feature Specification: PostgresToolkit asyncdb Connection Unwrap + Warm-up Params

**Feature ID**: FEAT-112
**Date**: 2026-04-20
**Author**: Javier León
**Status**: draft
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement
After the FEAT-107 migration (commit `c1e93b8d`, TASK-743), NavigatorToolkit tools
that go through `PostgresToolkit.execute_sql` / `select_rows` fail at runtime with:

```
pg.fetch() takes from 1 to 2 positional arguments but 3 were given
```

Observed in production logs while calling `nav_list_modules`, `nav_list_programs`,
and `nav_search` via the Telegram agent:

```
[ERROR] nav_list_modules.Tool(abstract.py:478) :: Error in nav_list_modules:
  pg.fetch() takes from 1 to 2 positional arguments but 3 were given
```

Root cause: `PostgresToolkit._run_on_conn` assumes `conn` is a raw
`asyncpg.Connection` (with `fetch(sql, *args)` / `fetchrow(sql, *args)` /
`execute(sql, *args)` signatures). In reality,
`BaseDatabaseToolkit._acquire_asyncdb_connection` (base.py:379) yields the
**asyncdb `pg` driver wrapper**, not a raw asyncpg connection. The asyncdb
`pg.fetch(self, number=1)` method is a *cursor-advance* helper that accepts a
single integer — so passing `(sql, *args)` raises `TypeError`.

A secondary, related bug in the same connection abstraction breaks metadata
warm-up: `SQLToolkit._execute_asyncdb` receives SQL from `_get_columns_query`
with named placeholders (`:schema`, `:table`) + a params dict, but **drops the
params** before calling `conn.query(sql)`. Every table in the warm list logs
`Warm-up skipped <schema>.<table> (table not found or no columns)`, leaving
the metadata cache empty.

### Goals
- Restore NavigatorToolkit end-to-end functionality for list/search tools by
  making `_run_on_conn` tolerant of both asyncdb-wrapped and raw asyncpg
  connections.
- Fix `_build_table_metadata` warm-up so NavigatorToolkit's whitelisted tables
  populate `cache_partition` on startup (0/13 → 13/13 warmed).
- Add regression tests that would have caught both bugs.

### Non-Goals
- Reworking the asyncdb/asyncpg boundary or introducing a new abstraction layer.
- Changing public NavigatorToolkit / PostgresToolkit signatures.
- Retrofitting other toolkits (BigQuery, InfluxDB, etc.) — this spec covers the
  `pg` driver path only.

---

## 2. Architectural Design

### Overview
Two surgical fixes inside the PostgresToolkit / SQLToolkit stack, plus targeted
regression tests. No new classes, no new public API.

### Component Diagram
```
NavigatorToolkit.list_programs / list_modules / search_database
        │
        ▼
PostgresToolkit.execute_sql / select_rows   (packages/ai-parrot/…/postgres.py)
        │
        ▼
PostgresToolkit._execute_crud
        │
        ▼
PostgresToolkit._run_on_conn          ◄── Fix #1 (unwrap asyncdb wrapper)
        │   uses conn.fetch/fetchrow/execute
        ▼
asyncpg.Connection (raw)              ◄── target signature

SQLToolkit._warm_cache
        │
        ▼
SQLToolkit._build_table_metadata
        │
        ▼
SQLToolkit._execute_asyncdb           ◄── Fix #2 (stop dropping params)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PostgresToolkit._run_on_conn` | **modify in place** | Unwrap asyncdb `pg` wrapper via `conn.engine()` before dispatch. |
| `SQLToolkit._execute_asyncdb` | **modify signature** | Accept optional params dict; forward to asyncdb. |
| `SQLToolkit._build_table_metadata` | **update callers** | Pass `col_params` / `pk_params` / `uq_params` through. |
| `BaseDatabaseToolkit._acquire_asyncdb_connection` | **unchanged** | Keep yielding the asyncdb wrapper — unwrapping is the consumer's responsibility. |
| `asyncdb.drivers.pg.pg` | consumed | Read-only dependency on `engine()` alias and `fetch_all/fetch_one` methods. |

### Data Models
No new Pydantic models. Fixes are behavioural.

### New Public Interfaces
None. All changes are to private `_` methods.

---

## 3. Module Breakdown

### Module 1: `_run_on_conn` asyncdb unwrap
- **Path**: `packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py`
- **Responsibility**: Dispatch a prepared SQL statement + positional params to a
  raw `asyncpg.Connection`, regardless of whether the caller passed the asyncdb
  `pg` wrapper (the common case) or a raw `asyncpg.Connection` (possible when
  `conn` was previously unwrapped by a caller).
- **Depends on**: `asyncdb.interfaces.abstract.AbstractDriver.engine()` alias of
  `get_connection()` (interfaces/abstract.py:66-69).

### Module 2: `_execute_asyncdb` params passthrough
- **Path**: `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py`
- **Responsibility**: Allow metadata-introspection queries (built with named
  `:schema` / `:table` placeholders by `_get_columns_query`,
  `_get_primary_keys_query`, `_get_unique_constraints_query`) to execute
  correctly during warm-up.
- **Depends on**: `asyncdb.drivers.pg.pg.fetch_all(sentence, *args)` for
  parameterised fetches.

### Module 3: Regression tests
- **Path**: `tests/unit/bots/database/toolkits/test_postgres_run_on_conn.py`
  (new) and extension of existing `test_postgres_crud.py` / `test_sql_warmup.py`
  if present.
- **Responsibility**: Lock down both fixes:
  1. `_run_on_conn` returns rows when given the asyncdb wrapper;
  2. Warm-up populates `cache_partition` for at least one whitelisted table.
- **Depends on**: Module 1 + Module 2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_run_on_conn_unwraps_asyncdb_wrapper` | Module 1 | `_run_on_conn` called with a fake asyncdb wrapper (exposing `engine()` → raw stub) dispatches to raw stub's `fetch`. |
| `test_run_on_conn_accepts_raw_asyncpg_conn` | Module 1 | Fallback path: when `conn` has no `engine` attribute, the raw conn is used directly. |
| `test_run_on_conn_execute_only` | Module 1 | `returning=False` path calls `execute`, returns `{"status": "ok"}`. |
| `test_run_on_conn_single_row` | Module 1 | `single_row=True` dispatches to `fetchrow`, returns dict or `{}`. |
| `test_run_on_conn_multi_row` | Module 1 | Default path dispatches to `fetch`, returns list of dicts. |
| `test_execute_asyncdb_forwards_params` | Module 2 | Params dict is forwarded to asyncdb (not silently dropped). |
| `test_build_table_metadata_returns_columns` | Module 2 | Against a mocked asyncdb driver, `_build_table_metadata` returns a populated `TableMetadata` (non-empty `columns`). |
| `test_warm_cache_populates_cache_partition` | Module 3 | End-to-end warm-up over a fake-table list, verifying `store_table_metadata` is called the expected number of times. |

### Integration Tests

| Test | Description |
|---|---|
| `test_navigator_list_programs_no_pgfetch_error` | With a real PostgresToolkit against a test database (or a close asyncdb double), `NavigatorToolkit.list_programs()` returns a list result without raising the `pg.fetch()` TypeError. |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_raw_asyncpg_conn():
    class Raw:
        async def fetch(self, sql, *args):
            return [{"program_id": 1, "program_name": "demo"}]
        async def fetchrow(self, sql, *args):
            return {"program_id": 1}
        async def execute(self, sql, *args):
            return "OK"
    return Raw()

@pytest.fixture
def fake_asyncdb_wrapper(fake_raw_asyncpg_conn):
    class Wrapper:
        def engine(self):
            return fake_raw_asyncpg_conn
        # asyncdb pg.fetch is a cursor-advance method — calling it with
        # sql + args must raise to prove we are unwrapping.
        async def fetch(self, number=1):
            raise AssertionError("asyncdb wrapper.fetch should not be called")
        async def fetchrow(self):
            raise AssertionError("asyncdb wrapper.fetchrow should not be called")
        async def execute(self, *args, **kwargs):
            raise AssertionError("asyncdb wrapper.execute should not be called")
    return Wrapper()
```

---

## 5. Acceptance Criteria

- [ ] `PostgresToolkit._run_on_conn` unwraps asyncdb driver wrappers via
      `engine()` before calling `fetch` / `fetchrow` / `execute`.
- [ ] Fallback path preserves current behaviour when `conn` lacks an `engine`
      callable (future-proofing against raw-asyncpg callers).
- [ ] `SQLToolkit._execute_asyncdb` forwards the `params` dict supplied by
      `_get_columns_query` / `_get_primary_keys_query` / `_get_unique_constraints_query`
      (either translated to asyncpg `$N` or safely inlined for identifier-only
      queries).
- [ ] Warm-up no longer emits
      `Warm-up skipped <schema>.<table> (table not found or no columns)`
      for the NavigatorToolkit whitelist when the target schema exists.
- [ ] All new unit tests in Module 3 pass (`pytest tests/unit/bots/database/ -v`).
- [ ] Smoke integration test: `NavigatorToolkit.list_programs` + `list_modules`
      execute without raising `pg.fetch()` TypeError against a live test DB.
- [ ] No regression in `PostgresToolkit.transaction()`: existing transaction
      tests still pass.
- [ ] No breaking changes to any public method signature.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-04-20 via direct Read + Grep on `main` @ 76f0d6c4 and on `dev`.

### Verified Imports
```python
# Already present in postgres.py — no new imports required for Fix #1.
from contextlib import asynccontextmanager  # postgres.py:top
from typing import Any, AsyncIterator, Dict, List, Optional  # postgres.py:top

# For tests:
import pytest  # standard
import pytest_asyncio  # present in dev deps
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py
class PostgresToolkit(SQLToolkit):
    async def execute_sql(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        conn: Optional[Any] = None,
        returning: bool = True,
        single_row: bool = False,
    ) -> Any:                                    # line 682

    async def select_rows(
        self,
        table: str,
        where: Optional[Dict[str, Any]] = None,
        columns: Optional[List[str]] = None,
        order_by: Optional[List[str]] = None,
        limit: Optional[int] = None,
        conn: Optional[Any] = None,
        distinct: bool = False,
        column_casts: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:                   # line 616

    async def _execute_crud(
        self,
        sql: str,
        args: tuple[Any, ...],
        returning: Optional[List[str]],
        conn: Optional[Any],
        single_row: bool,
    ) -> Any:                                    # line 752

    @staticmethod
    async def _run_on_conn(
        sql: str,
        args: tuple[Any, ...],
        returning: Optional[List[str]],
        conn: Any,
        single_row: bool,
    ) -> Any:                                    # line 772  ◄── Fix #1 target

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:  # line 795
```

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/base.py
class BaseDatabaseToolkit:
    @asynccontextmanager
    async def _acquire_asyncdb_connection(self) -> AsyncIterator[Any]:
        """
        Yields an asyncdb driver wrapper (NOT a raw asyncpg.Connection).
        Pool path: pg = await self._connection.acquire()
        Direct path: async with await self._connection.connection() as conn → pg driver
        """                                      # line 378
```

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py
class SQLToolkit(BaseDatabaseToolkit):
    async def _execute_asyncdb(
        self,
        sql: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """Currently executes `await conn.query(sql)` — DROPS PARAMS."""  # line 487  ◄── Fix #2 target

    async def _build_table_metadata(
        self,
        schema: str,
        table: str,
        table_type: str,
        comment: Optional[str] = None,
    ) -> Optional[TableMetadata]:                # line 581  (call-site update)
```

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py
class PostgresToolkit(SQLToolkit):
    def _get_columns_query(
        self, schema: str, table: str
    ) -> tuple[str, Dict[str, Any]]:
        """Returns SQL with :schema and :table placeholders + params dict."""  # line 127
```

### asyncdb external dependency — verified

```python
# .venv/lib/python3.11/site-packages/asyncdb/interfaces/abstract.py
class AbstractDriver:
    def get_connection(self):                    # line 66
        """Returns the raw underlying connection (asyncpg for pg driver)."""
    engine = get_connection                      # line 69  ← alias used by this spec
```

```python
# .venv/lib/python3.11/site-packages/asyncdb/drivers/pg.py
class pg(SQLDriver, DBCursorBackend, ModelBackend):
    async def execute(self, sentence, *args, **kwargs): ...   # line 813 (wraps asyncpg.execute)
    async def fetch_all(self, sentence, *args, **kwargs): ... # line 889
    async def fetch_one(self, sentence, *args, **kwargs): ... # line 912
    async def fetch(self, number=1): ...                      # line 981  (cursor-advance — DO NOT call with SQL)
    async def fetchrow(self): ...                             # line 988  (cursor-advance — DO NOT call with SQL)
```

### Integration Points

| New Code | Connects To | Via | Verified At |
|---|---|---|---|
| `_run_on_conn` (patched) | `conn.engine()` | method call | `asyncdb/interfaces/abstract.py:66-69` |
| `_run_on_conn` raw path | `asyncpg.Connection.fetch / fetchrow / execute` | method call | `asyncdb/drivers/pg.py:625-660` (connects asyncpg internally) |
| `_execute_asyncdb` (patched) | `asyncdb.pg.fetch_all(sentence, *args)` | method call | `asyncdb/drivers/pg.py:889` |

### Does NOT Exist (Anti-Hallucination)

- ~~`PostgresToolkit._unwrap_conn()`~~ — not defined; do NOT invent a helper class method. Inline the `hasattr(conn, "engine") and callable(conn.engine)` guard in `_run_on_conn`.
- ~~`asyncdb.drivers.pg.pg.raw_connection()`~~ — not a method. The raw connection is obtained via `engine()` / `get_connection()` only.
- ~~`conn.fetchall(sql, *args)`~~ on the asyncdb wrapper — wrong name. The driver exposes `fetch_all` (underscore). `fetchall` is a module-level alias for `fetch_all` (pg.py:910) that also expects `(sentence, *args)`, NOT `(sql, *args)` positional on an already-bound cursor.
- ~~`_run_on_conn` self reference~~ — it is a `@staticmethod`. Do not introduce `self` in the signature.
- ~~Replacing `_acquire_asyncdb_connection` to yield `engine()` directly~~ — out of scope: transaction() currently calls `conn.transaction()` on the asyncdb wrapper; changing the yield shape would break that path.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Keep `_run_on_conn` a `@staticmethod`.
- Use the existing `hasattr(...) and callable(...)` pattern — no new abstraction.
- Preserve the `dict(row)` / `[dict(r) for r in rows]` result shapes verbatim
  (existing callers in `postgres.py` rely on them).
- Maintain async-first style; no new blocking calls.

### Known Risks / Gotchas
- **Risk**: `conn.engine()` may return `None` if the asyncdb wrapper is not
  connected. Mitigation: call `engine()` inside a `try/except` or check for
  `None` and fall back to raising the original error with context.
- **Risk**: `transaction()` (postgres.py:795) already does
  `async with conn.transaction():` — if `transaction()` is currently silently
  broken on asyncdb `pg`, this fix will *reveal* (not introduce) that latent
  bug. Document the finding in the completion note; do not widen scope.
- **Risk**: Fix #2 may need to translate `:schema` / `:table` → `$1` / `$2`
  for asyncpg, OR use safe identifier quoting. Prefer the parameterised route
  to keep SQL injection hygiene consistent; only fall back to inlining if the
  asyncdb API rejects the translation.
- **Risk**: Warm-up currently tolerates silent failure (just logs warning).
  After Fix #2, a genuinely-missing table must still warn (not raise) — keep
  the existing try/except in `_build_table_metadata`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `asyncdb` | pinned | Provides `pg` driver + `engine()` alias. No version bump needed. |
| `asyncpg` | via asyncdb | Raw connection methods `fetch / fetchrow / execute`. |

---

## 8. Open Questions

- [ ] Should Fix #2 translate `:name` → `$N` (keeping asyncdb/asyncpg
      parameterisation) or safely inline quoted identifiers? — *Owner: jleon*
- [ ] Should `_acquire_asyncdb_connection` be refactored in a future spec to
      always yield the unwrapped asyncpg connection (removing the need for
      per-callsite unwrap)? — *Owner: jleon* (out of scope here)

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (all tasks sequential in one worktree).
- Worktree branch: `feat-112-postgres-toolkit-asyncdb-conn-unwrap`
- No cross-feature dependencies. Branches off `dev`.

```bash
git worktree add -b feat-112-postgres-toolkit-asyncdb-conn-unwrap \
  .claude/worktrees/feat-112-postgres-toolkit-asyncdb-conn-unwrap HEAD
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-20 | Javier León | Initial draft — regression fix for FEAT-107 migration. |

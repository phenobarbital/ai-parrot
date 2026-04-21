# Feature Specification: PostgresToolkit — Raw asyncpg + Deprecate SQLAlchemy Path

**Feature ID**: FEAT-112
**Date**: 2026-04-20
**Author**: Javier León
**Status**: draft (lead-review incorporated)
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

After the FEAT-107 migration (commit `c1e93b8d`, TASK-743), NavigatorToolkit
tools routed through `PostgresToolkit.execute_sql` / `select_rows` fail at
runtime with:

```
pg.fetch() takes from 1 to 2 positional arguments but 3 were given
```

Reproduced in production (Telegram agent → `nav_list_modules` /
`nav_list_programs` / `nav_search`).

Investigation surfaced three tightly-coupled defects in the
database-toolkit stack:

1. **`_run_on_conn` invokes asyncpg-style API on an asyncdb wrapper.**
   `_acquire_asyncdb_connection` yields the asyncdb `pg` driver — whose
   `fetch(self, number=1)` is a cursor-advance helper, not `fetch(sql, *args)`.

2. **Query builders emit SQLAlchemy-style `:name` placeholders for queries
   that run through the asyncdb/asyncpg path.** `_execute_asyncdb` drops the
   params dict before calling `conn.query(sql)`, so warm-up silently skips
   every table in the whitelist (`0/13 warmed` in observed logs).

3. **The `backend="sqlalchemy"` branch is dead code.** A repo-wide search
   finds zero callers instantiating any toolkit with `backend="sqlalchemy"`;
   the only references live in docstrings and init-validation unit tests.
   Its continued existence forces query builders to use a non-native
   placeholder style and leaks SQLAlchemy imports into the critical path.

Lead-developer directive (Jesús Lara, 2026-04-20):
> *"si usas uno, es uno para todo. No crees query sqlalchemy pa correrlos con
> asyncdb. Pasa naked el asyncpg y no uses asyncdb para simplificar el uso de
> transacciones. Pasa de cualquier driver el `engine()` y con el `engine()`
> ejecuta una transacción con savepoints de asyncpg."*

### Goals

- Restore NavigatorToolkit functionality (list/search/read tools) by making
  the asyncdb-connection boundary yield a **raw `asyncpg.Connection`**.
- Commit to a **single SQL-parameter style** in the asyncdb path: asyncpg
  native `$1, $2, …` everywhere.
- Reimplement `PostgresToolkit.transaction()` on top of
  `asyncpg.Connection.transaction()` — gains native savepoint support with
  less indirection.
- Remove the SQLAlchemy backend and its surface area from
  `DatabaseToolkit` / `SQLToolkit` / `PostgresToolkit` / `BigQueryToolkit`.
- Add regression tests that would have caught all three defects.

### Non-Goals

- Rewiring non-SQL toolkits (InfluxDB, Elasticsearch, DocumentDB,
  BigQuery execution path for non-postgres drivers). Only the
  `pg`-backed path is in scope for the connection-unwrap work; the
  SQLAlchemy removal, however, is cross-cutting across all SQL toolkits
  because the base-class `backend` param is shared.
- Introducing a new abstraction over asyncpg (we use it directly).
- Changing NavigatorToolkit tool signatures.

---

## 2. Architectural Design

### Overview

Three coordinated changes, one bugfix spec:

1. **Move the asyncdb→asyncpg unwrap to the boundary.**
   `_acquire_asyncdb_connection` (and the pool path) yield the raw
   `asyncpg.Connection` obtained via `driver.engine()` (alias of
   `get_connection()`, `asyncdb/interfaces/abstract.py:66-69`).
   Every downstream consumer (`_run_on_conn`, `transaction()`,
   `_execute_asyncdb`, CRUD helpers) drops the wrapper layer and works
   against asyncpg verbatim.

2. **Normalise query builders to `$1, $2, …`.**
   `_get_information_schema_query`, `_get_columns_query`,
   `_get_primary_keys_query`, `_get_unique_constraints_query`, and
   `_get_sample_data_query` return SQL with asyncpg placeholders + a
   positional `tuple` (not a dict). `_execute_asyncdb` accepts
   `params: tuple[Any, ...]` and forwards them.

3. **Delete the SQLAlchemy path.**
   Remove `backend` parameter, `_connect_sqlalchemy`,
   `_execute_sqlalchemy`, `_build_sqlalchemy_dsn` (and subclass
   overrides), and all `if self.backend == "asyncdb"` branches. Update
   tests that merely validated `backend="sqlalchemy"` init (replace with
   asserts that the `backend` kwarg no longer exists or keep init-only
   coverage via a dedicated xfail-until-removed shim if needed).

### Component Diagram

```
NavigatorToolkit.list_programs / list_modules / search_database
        │
        ▼
PostgresToolkit.execute_sql / select_rows / CRUD helpers
        │
        ▼
PostgresToolkit._execute_crud  ─────► asyncpg.Connection.fetch/fetchrow/execute
        ▲                                   ▲
        │                                   │
 PostgresToolkit.transaction()  ◄────── asyncpg.Connection.transaction()  (native savepoints)
        │                                   ▲
        ▼                                   │
 BaseDatabaseToolkit._acquire_asyncdb_connection
        │   yield driver.engine()  ◄─── NEW boundary: yields RAW asyncpg conn
        ▼
 asyncdb.drivers.pg.pg (AsyncDB / AsyncPool)  ── wrapper acquired, unwrapped immediately
```

### Integration Points

| Component | Change | Notes |
|---|---|---|
| `DatabaseToolkit.__init__` | breaking | `backend` parameter **removed**. Callers who passed `backend="asyncdb"` work unchanged (it was the default). Callers who passed `backend="sqlalchemy"` must be deleted (none in the codebase). |
| `DatabaseToolkit._engine`, `_connect_sqlalchemy`, `_build_sqlalchemy_dsn` | removed | Along with all `if self.backend == …` branches in `health_check`, `stop`, `execute_query`, `_search_in_database`, `_build_table_metadata`. |
| `BaseDatabaseToolkit._acquire_asyncdb_connection` | behaviour change | Yields `driver.engine()` (raw asyncpg.Connection) instead of the asyncdb wrapper. |
| `SQLToolkit._execute_asyncdb` | signature change | `(self, sql, params: tuple = (), limit=1000, timeout=30)` — forwards `*params` to `conn.fetch(sql, *params)`. |
| `SQLToolkit._get_*_query` (x5) | contract change | Return `(sql, tuple)` with `$1, $2, …` placeholders instead of `(sql, dict)` with `:name`. |
| `PostgresToolkit._get_information_schema_query`, `_get_columns_query` | contract change | Same as above (postgres-specific overrides). |
| `BigQueryToolkit._get_*_query` | contract change | Keep `:name` **only if** BigQuery driver (which does not use asyncpg) requires it. If BigQuery stays on asyncdb, also normalise to `$1` (asyncdb `bigquery` driver parameter style TBD — open question). |
| `PostgresToolkit._run_on_conn` | simplified | Directly `conn.fetch / fetchrow / execute`; no unwrap guard needed. |
| `PostgresToolkit.transaction()` | rewritten | `async with raw_conn.transaction():` (asyncpg native — supports savepoints and nested transactions). |
| `pyproject.toml` | dependency review | If `sqlalchemy` is only pulled in for this path, move to dev-only or remove. |

### Data Models

No new Pydantic models. The internal `TableMetadata` shape is unchanged.

### New Public Interfaces

None. All signature changes are to private `_` methods except the removal
of the `backend=` init kwarg from `DatabaseToolkit`, which is a **breaking
change for external subclasses only** — no in-repo caller is affected.

---

## 3. Module Breakdown

### Module 1 — Connection boundary (yield raw asyncpg)
- **Path**: `packages/ai-parrot/src/parrot/bots/database/toolkits/base.py`
- **Responsibility**: `_acquire_asyncdb_connection` yields the
  `asyncpg.Connection` obtained via `driver.engine()`. Maintain pool
  acquire/release semantics (call `engine()` on the acquired wrapper,
  release the **wrapper** back to the pool on exit).
- **Depends on**: `asyncdb.interfaces.abstract.AbstractDriver.engine` (alias of `get_connection`).

### Module 2 — Remove SQLAlchemy backend
- **Path**: `packages/ai-parrot/src/parrot/bots/database/toolkits/base.py`,
  `sql.py`, `postgres.py`, `bigquery.py`.
- **Responsibility**:
  - Drop `backend` field + constructor kwarg from `DatabaseToolkit`.
  - Delete `_connect_sqlalchemy`, `_build_sqlalchemy_dsn`, `_engine` attr,
    and the `execute_query` / `health_check` / `stop` / `_search_in_database`
    / `_build_table_metadata` branches gated on `self.backend == "sqlalchemy"`.
  - Delete `SQLToolkit._execute_sqlalchemy`.
  - Delete subclass overrides of `_build_sqlalchemy_dsn`
    (`postgres.py:149`, `bigquery.py:117`).
  - Update docstrings that still mention a SQLAlchemy alternative.
- **Depends on**: Module 1 (clean single-path execution).

### Module 3 — Query-builder param style
- **Path**: `sql.py`, `postgres.py`, `bigquery.py` (re-evaluate after Module 2).
- **Responsibility**: Convert all `_get_*_query` builders to emit
  `$1, $2, …` placeholders and return `(sql, tuple)`. Update
  `_execute_asyncdb` to accept and forward a positional tuple.
  Update `_build_table_metadata` / `_search_in_database` call sites.
- **Depends on**: Module 2.

### Module 4 — Rewrite `transaction()` on asyncpg native
- **Path**: `postgres.py`.
- **Responsibility**: Re-base `PostgresToolkit.transaction()` on
  `asyncpg.Connection.transaction()` (sync context manager, supports
  savepoints). Yield the raw `asyncpg.Connection` as `conn` so callers
  can chain `execute_sql(..., conn=tx)` seamlessly.
- **Depends on**: Module 1.

### Module 5 — Tests + dependency hygiene
- **Path**: `tests/unit/test_sql_toolkit.py`,
  `tests/unit/test_postgres_toolkit.py`,
  `tests/unit/test_database_toolkit_base.py`,
  new `tests/unit/bots/database/toolkits/test_postgres_run_on_conn.py`,
  `tests/unit/bots/database/toolkits/test_warm_cache_params.py`.
- **Responsibility**:
  - Remove or re-purpose existing `backend="sqlalchemy"` init tests.
  - Add regression tests for `_run_on_conn` against a raw-asyncpg stub.
  - Add regression test for warm-up populating metadata cache (params
    forwarded → `columns` non-empty).
  - Add transaction + savepoint smoke test (may require a live test DB;
    gate behind `POSTGRES_TEST_DSN` env fixture).
  - Audit `pyproject.toml` for `sqlalchemy` — if unused elsewhere, move
    to dev-deps or remove entirely.
- **Depends on**: Modules 1–4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_acquire_asyncdb_yields_raw_asyncpg` | Module 1 | Mocks asyncdb driver with `engine()` returning a stub; asserts the stub is what `_acquire_asyncdb_connection` yields. |
| `test_acquire_asyncdb_pool_release_wrapper` | Module 1 | Pool path: `acquire()` returns wrapper → `engine()` yielded → wrapper is released on exit. |
| `test_run_on_conn_fetch` | Module 1 | `_run_on_conn` with `returning=True, single_row=False` calls `conn.fetch(sql, *args)` on the raw stub. |
| `test_run_on_conn_fetchrow` | Module 1 | `single_row=True` → `fetchrow`. |
| `test_run_on_conn_execute_only` | Module 1 | `returning=False` → `execute`. |
| `test_backend_kwarg_removed` | Module 2 | `DatabaseToolkit(dsn=..., backend="sqlalchemy")` raises `TypeError` (unknown kwarg). |
| `test_no_sqlalchemy_imports_in_hot_path` | Module 2 | Static check: `sqlalchemy` not imported by `base.py`, `sql.py`, `postgres.py`, `bigquery.py` at module top level. |
| `test_columns_query_emits_dollar_placeholders` | Module 3 | `_get_columns_query("auth", "programs")` → `(sql, ("auth", "programs"))` where sql contains `$1` / `$2`. |
| `test_execute_asyncdb_forwards_tuple_params` | Module 3 | `_execute_asyncdb("SELECT $1", (42,))` dispatches `.fetch("SELECT $1", 42)` on the stub. |
| `test_build_table_metadata_populates_columns` | Module 3 | Fake asyncpg returns 3 rows → `TableMetadata.columns` length == 3. |
| `test_transaction_yields_asyncpg_conn` | Module 4 | `async with toolkit.transaction() as tx:` — `tx.fetch(...)` is an asyncpg coroutine. |
| `test_transaction_savepoint_rollback` | Module 4 | Nested `async with tx.transaction():` rolls back inner while preserving outer (requires live DB). |

### Integration Tests

| Test | Description |
|---|---|
| `test_navigator_list_programs_no_pgfetch_error` | `NavigatorToolkit.list_programs()` against a live PG test DB returns a list without raising `pg.fetch()` TypeError. |
| `test_warmup_populates_cache_against_live_db` | Warm-up over a real `auth.programs` table → `0/N warmed` becomes `N/N warmed`. |

### Test Data / Fixtures

```python
@pytest.fixture
def fake_asyncpg_conn():
    class Raw:
        calls: list[tuple] = []
        async def fetch(self, sql, *args):
            Raw.calls.append(("fetch", sql, args))
            return [{"ok": 1}]
        async def fetchrow(self, sql, *args):
            Raw.calls.append(("fetchrow", sql, args))
            return {"ok": 1}
        async def execute(self, sql, *args):
            Raw.calls.append(("execute", sql, args))
            return "OK"
    return Raw()

@pytest.fixture
def fake_asyncdb_driver(fake_asyncpg_conn):
    class Wrapper:
        def engine(self):
            return fake_asyncpg_conn
    return Wrapper()
```

---

## 5. Acceptance Criteria

- [ ] `_acquire_asyncdb_connection` yields a raw `asyncpg.Connection`
      (pool and direct paths).
- [ ] `PostgresToolkit._run_on_conn` calls asyncpg APIs directly (no unwrap
      guard, no wrapper method dispatch).
- [ ] `PostgresToolkit.transaction()` uses
      `async with raw_conn.transaction():` and yields the raw asyncpg
      connection; savepoints work via nested `tx.transaction()`.
- [ ] All `_get_*_query` builders return `(sql, tuple)` with `$N`
      placeholders; `_execute_asyncdb` accepts and forwards the tuple.
- [ ] No module under `parrot/bots/database/toolkits/` imports `sqlalchemy`
      at top level. `backend` kwarg is removed from `DatabaseToolkit.__init__`.
- [ ] Warm-up log for NavigatorToolkit shows **N/N warmed** (not 0/N) for
      a whitelist pointed at an existing schema.
- [ ] `pytest tests/unit/bots/database/ -v` is green (including Module 5
      additions).
- [ ] `pytest tests/unit/test_database_toolkit_base.py tests/unit/test_sql_toolkit.py tests/unit/test_postgres_toolkit.py -v`
      passes after test-suite updates (no `backend="sqlalchemy"` assertions).
- [ ] Smoke: `NavigatorToolkit.list_programs` + `list_modules` + `nav_search`
      execute against a live DB without the `pg.fetch()` TypeError.
- [ ] No regression in existing CRUD tests (insert/update/delete/upsert).
- [ ] `pyproject.toml` audit: if `sqlalchemy` is unused after the change,
      remove from runtime deps (move to `[project.optional-dependencies]`
      if any downstream still needs it, else drop).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-04-20 against `dev` HEAD (commit `76f0d6c4`) + `.venv` asyncdb 2.x.

### Verified Imports

```python
# No new imports required for Module 1 beyond existing:
from contextlib import asynccontextmanager            # base.py / postgres.py
from typing import Any, AsyncIterator, Dict, List, Optional  # base.py / postgres.py

# Module 4 — asyncpg.Connection is exposed only transitively; we use the
# value returned by asyncdb's engine() without importing asyncpg directly
# (keeps asyncpg a transitive dep, same as today).

# Tests:
import pytest
import pytest_asyncio
```

### Existing Class Signatures (pre-change)

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/base.py
class DatabaseToolkit(AbstractToolkit, ABC):
    def __init__(
        self,
        dsn: str,
        allowed_schemas: Optional[List[str]] = None,
        primary_schema: Optional[str] = None,
        tables: Optional[List[str]] = None,
        read_only: bool = True,
        backend: str = "asyncdb",                  # line 115 — REMOVED by Module 2
        cache_partition: Optional[CachePartition] = None,
        retry_config: Optional[QueryRetryConfig] = None,
        database_type: str = "postgresql",
        use_pool: bool = False,
        pool_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None: ...                                 # line 108
    async def _connect_asyncdb(self) -> None: ...  # line 357
    async def _connect_sqlalchemy(self) -> None: ...  # line 401 — DELETED
    def _build_sqlalchemy_dsn(self, raw_dsn: str) -> str: ...  # line 424 — DELETED
    @asynccontextmanager
    async def _acquire_asyncdb_connection(self) -> AsyncIterator[Any]: ...  # line 378 — REWORKED
```

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py
class SQLToolkit(DatabaseToolkit):
    async def _execute_asyncdb(                    # line 487 — SIGNATURE CHANGE
        self, sql: str, limit: int = 1000, timeout: int = 30,
    ) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]: ...

    async def _execute_sqlalchemy(                 # line 510 — DELETED
        self, sql: str, limit: int = 1000, timeout: int = 30,
    ) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]: ...

    def _get_information_schema_query(self, search_term: str, schemas: list[str]) -> tuple[str, Dict[str, Any]]: ...  # line 382 — CHANGE return Dict → tuple
    def _get_columns_query(self, schema: str, table: str) -> tuple[str, Dict[str, Any]]: ...  # line 413 — CHANGE
    def _get_primary_keys_query(self, schema: str, table: str) -> tuple[str, Dict[str, Any]]: ...  # line 424 — CHANGE
    def _get_unique_constraints_query(self, schema: str, table: str) -> tuple[str, Dict[str, Any]]: ...  # line 439 — CHANGE
    def _get_sample_data_query(self, schema: str, table: str, limit: int = 5) -> str: ...  # line 475 — no param change
```

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py
class PostgresToolkit(SQLToolkit):
    def _get_information_schema_query(self, search_term: str, schemas: list[str]) -> tuple[str, Dict[str, Any]]: ...  # line 96 — CHANGE
    def _get_columns_query(self, schema: str, table: str) -> tuple[str, Dict[str, Any]]: ...  # line 127 — CHANGE
    def _build_sqlalchemy_dsn(self, raw_dsn: str) -> str: ...  # line 149 — DELETED
    @staticmethod
    async def _run_on_conn(                         # line 772 — simplified body
        sql: str, args: tuple[Any, ...],
        returning: Optional[List[str]], conn: Any, single_row: bool,
    ) -> Any: ...
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]: ...  # line 795 — REWRITTEN on asyncpg native
```

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/bigquery.py
class BigQueryToolkit(SQLToolkit):
    def _get_information_schema_query(...)            # line 56 — CHANGE (pending Q1)
    def _get_columns_query(...)                       # line 80 — CHANGE (pending Q1)
    def _build_sqlalchemy_dsn(self, raw_dsn: str)     # line 117 — DELETED
```

### External dependency — verified (asyncdb)

```python
# .venv/lib/python3.11/site-packages/asyncdb/interfaces/abstract.py
class AbstractDriver:
    def get_connection(self): ...                     # line 66
    engine = get_connection                           # line 69  ← relied upon

# .venv/lib/python3.11/site-packages/asyncdb/drivers/pg.py
class pg(SQLDriver, DBCursorBackend, ModelBackend):
    async def connection(self): ...                   # line 625 — sets self._connection to asyncpg.Connection
    async def execute(self, sentence, *args, **kwargs): ...  # line 813
    async def fetch_all(self, sentence, *args, **kwargs): ...  # line 889
    async def fetch_one(self, sentence, *args, **kwargs): ...  # line 912
    async def fetch(self, number=1): ...              # line 981  (cursor-advance; DO NOT call with SQL)
    async def fetchrow(self): ...                     # line 988  (cursor-advance)

class pgPool(BasePool):
    async def acquire(self) -> pg: ...                # line 321
    async def release(self, connection=None, ...)     # line 356 — accepts pg wrapper OR raw asyncpg
```

Sample-of-truth dead-code census (verified via `grep -rn 'backend="sqlalchemy"' --include=*.py`):

| File | Line | Type |
|---|---|---|
| `packages/ai-parrot/.../base.py` | 214 | docstring only |
| `tests/unit/test_sql_toolkit.py` | 36 | init-only assertion |
| `tests/unit/test_database_toolkit_base.py` | 56 | init-only assertion |
| `tests/unit/test_postgres_toolkit.py` | 81, 85 | init-only assertion |

**No production callers.**

### Integration Points

| New Code | Connects To | Via | Verified At |
|---|---|---|---|
| `_acquire_asyncdb_connection` | `AbstractDriver.engine()` | method call | `asyncdb/interfaces/abstract.py:66-69` |
| `_run_on_conn` | `asyncpg.Connection.fetch / fetchrow / execute` | direct call | `asyncdb/drivers/pg.py:625-660` (asyncpg connect) |
| `transaction()` | `asyncpg.Connection.transaction()` | native context manager | asyncpg docs — sync cm with optional savepoints |

### Does NOT Exist (Anti-Hallucination)

- ~~`asyncdb.drivers.pg.pg.raw_connection()`~~ — not a method; use `engine()` / `get_connection()`.
- ~~`PostgresToolkit._unwrap_conn()`~~ — do NOT invent a helper; unwrap happens once at `_acquire_asyncdb_connection`.
- ~~`asyncpg.Connection.savepoint()`~~ — savepoints are nested
  `transaction()` contexts (asyncpg does NOT expose a separate
  `savepoint` API).
- ~~`DatabaseToolkit.backend` attribute (post-Module 2)~~ — will not exist; do not reference.
- ~~`self._engine` (post-Module 2)~~ — will not exist; health-check and stop() must not reference it.
- ~~Keep a `backend="asyncdb"` kwarg "for compatibility"~~ — explicitly rejected by lead. Remove cleanly.
- ~~`SQLAlchemy-style placeholders on the asyncdb path~~ — explicitly rejected: "no crees query sqlalchemy pa correrlos con asyncdb".

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Single execution path: asyncpg native. Parametrise with `$N`.
- Keep `_run_on_conn` a `@staticmethod`.
- Preserve existing result shapes (`dict(row)` / `[dict(r) for r in rows]` / `{"status": "ok"}`).
- Call `driver.engine()` exactly once per checkout; never hold both the
  wrapper and the raw conn simultaneously in downstream code.
- When releasing to the pool, pass the **wrapper** back (`pgPool.release` already handles the unwrap, see `pg.py:364-366`).

### Known Risks / Gotchas

- **Risk — hidden SQLAlchemy consumer**: an external caller could be
  subclassing `DatabaseToolkit(backend="sqlalchemy")`. Mitigation: search
  `agents/` and `tests/` (done — none); bump a minor version and note in
  CHANGELOG; add a `TypeError` migration note.
- **Risk — BigQuery placeholder style**: `asyncdb.drivers.bigquery`
  may not accept `$N` placeholders. Mitigation: verify with a smoke test
  before converting the BigQuery builders; if incompatible, keep `:name`
  only for BigQuery **and** keep the params dict path there. Captured as Q1.
- **Risk — `transaction()` yielding raw asyncpg changes caller assumptions**:
  in-repo callers pass `conn=tx` to CRUD methods; after Module 1 those
  methods already accept raw asyncpg. No regression expected, but add a
  focused test (`test_transaction_yields_asyncpg_conn`).
- **Risk — init-validation tests**: the three `test_*.py` files assert
  successful init with `backend="sqlalchemy"`. Re-purpose them to assert
  the kwarg is **removed** (raises `TypeError`).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `asyncdb` | pinned | Provides `pg` driver + `engine()` alias. |
| `asyncpg` | via asyncdb | Raw connection APIs + native transaction/savepoint. |
| `sqlalchemy` | removable | Audit & drop unless used elsewhere (proposals mention BigQuery may still pull it transitively). |

---

## 8. Open Questions

- [ ] **Q1 — BigQuery placeholder style**: does `asyncdb.drivers.bigquery`
      accept `$N` placeholders, or must BigQuery builders keep `:name`?
      If the latter, split `_execute_asyncdb` into a small dispatch that
      preserves per-driver placeholder style. — *Owner: jleon*
- [ ] **Q2 — sqlalchemy in `pyproject.toml`**: is it a runtime dep solely
      because of the paths we are deleting, or does another module in
      AI-Parrot import it? (Grep before final cleanup.) — *Owner: jleon*
- [ ] **Q3 — External subclass compatibility**: confirm with lead that
      removing `backend=` without a deprecation cycle is acceptable
      (consensus today: yes — it is internal-only). — *Owner: jleon*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (sequential tasks, one worktree).
- Worktree branch: `feat-112-postgres-toolkit-asyncdb-conn-unwrap`.
- No cross-feature dependencies; branches off `dev`.

```bash
git worktree add -b feat-112-postgres-toolkit-asyncdb-conn-unwrap \
  .claude/worktrees/feat-112-postgres-toolkit-asyncdb-conn-unwrap HEAD
```

Task ordering inside the worktree:

```
Module 1 (boundary unwrap)
   └── Module 4 (transaction on asyncpg)
         └── Module 2 (delete SQLAlchemy path)
               └── Module 3 (query-builder params)
                     └── Module 5 (tests + dep hygiene)
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-20 | Javier León | Initial draft — regression fix for FEAT-107 migration. |
| 0.2 | 2026-04-20 | Javier León | Lead-review incorporated: move unwrap to boundary; remove SQLAlchemy path; normalise query builders to `$N`; rewrite `transaction()` on asyncpg native. |

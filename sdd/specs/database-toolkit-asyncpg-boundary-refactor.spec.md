# Feature Specification: Database Toolkit — asyncpg Native Boundary Refactor

**Feature ID**: FEAT-118
**Date**: 2026-04-21
**Author**: Javier León
**Status**: **draft — awaiting lead review (Jesús Lara)**
**Target version**: TBD (not scheduled)

> ⚠️ **DO NOT IMPLEMENT YET.** This spec captures a framework-level
> refactor proposal discovered while fixing FEAT-117. It is frozen as a
> design document pending explicit sign-off from the lead developer.
> Autonomous agents MUST NOT pick up tasks from this spec until the
> status is changed to `approved`.

---

## 1. Motivation & Business Requirements

### Problem Statement

While investigating the NavigatorToolkit runtime failure fixed by
FEAT-117 (`pg.fetch() takes from 1 to 2 positional arguments but 3 were
given`), a deeper set of design inconsistencies surfaced in the shared
database-toolkit stack under
`packages/ai-parrot/src/parrot/bots/database/toolkits/`.

FEAT-117 patches **one subclass** (`NavigatorToolkit`) so the Telegram
agent can ship. The underlying defects remain in the framework and will
resurface on any other `PostgresToolkit` / `SQLToolkit` consumer.

Verified defects (all as of `dev` @ commit `e36acaa0`, 2026-04-21):

| # | Defect | Location | Impact |
|---|---|---|---|
| D1 | `_run_on_conn` calls asyncpg-style API (`fetch(sql, *args)`) on the asyncdb `pg` driver wrapper yielded by `_acquire_asyncdb_connection` | `postgres.py:772` | Any CRUD or `execute_sql` call outside a transaction fails with `TypeError` in any `PostgresToolkit` subclass that does not locally override (FEAT-117 is the current workaround for `NavigatorToolkit` only). |
| D2 | `_execute_asyncdb` ignores the `params` dict returned by `_get_*_query` builders; calls `conn.query(sql)` with a bare SQL string that still contains `:schema` / `:table` / `:term` / `:limit` placeholders | `sql.py:487` | Metadata warm-up silently skips every whitelisted table (`0/N warmed`); metadata is built lazily on first CRUD call, which hides the bug until a rare code-path triggers it. |
| D3 | SQL-query builders emit SQLAlchemy-style `:name` placeholders even for asyncdb/asyncpg execution paths | `sql.py:382-468`, `postgres.py:96-147`, `bigquery.py:56-107` | Inconsistent parameter styles. Lead: *"si usas uno, es uno para todo. No crees query sqlalchemy pa correrlos con asyncdb."* |
| D4 | `backend="sqlalchemy"` is dead code (zero production callers; only 4 init-validation unit tests and one docstring reference) | `base.py:58, 115, 214, 401-425`; `sql.py:510-536`; subclass overrides in `postgres.py:149`, `bigquery.py:117` | Deuda técnica; fuerza a mantener dos rutas de ejecución y dos estilos de parametrización sin beneficio real. |
| D5 | `PostgresToolkit.transaction()` calls `async with conn.transaction():` where `conn` is the asyncdb `pg` wrapper and `conn.transaction()` is an `async def` that returns `self` — not a proper async context manager | `postgres.py:822-823` | Latent; unverified whether currently exercised. If called, should either raise or silently do the wrong thing. |

### Lead-developer directive (verbatim, 2026-04-20 22:02–22:06 UTC-3, Telegram)

> **Jesús Lara Giménez**:
> - *"empezando, por qué usar sqlalchemy? no lo pillo, si usas uno, es uno para todo"*
> - *"no creas query sqlalchemy pa correrlos con asyncdb"*
> - *"y lo segundo, lo que está diciendo aquí es de pasar naked el asyncpg y no usar asyncdb, para simplificar el uso de transacciones"*
> - *"pasar de cualquier driver el engine()"*
> - *"y con el engine() ejecutar una transacción con savepoints de asyncpg"*
> - *"pero hablamos de ejecutar una sentencia parametrizada con placeholders de asyncpg en una transacción con savepoints"*
> - *"soportado?, si, but more verbose"*
> - *"y te tocaría revolver el código del driver pg pa encontrarlo xD"*

### Goals

- Unwrap the asyncdb wrapper **once at the boundary**
  (`_acquire_asyncdb_connection`) so every downstream consumer works
  against raw `asyncpg.Connection`.
- Reimplement `PostgresToolkit.transaction()` on top of
  `asyncpg.Connection.transaction()` (native; supports nested
  savepoints).
- Commit to a **single parameter style** (`$1, $2, …` asyncpg native)
  for every SQL query emitted by the toolkit stack.
- Delete the SQLAlchemy backend branch entirely.
- Remove the `NavigatorToolkit._run_on_conn` override introduced by
  FEAT-117 (it becomes redundant once the boundary unwrap lands).

### Non-Goals

- Non-SQL toolkits (InfluxDB, Elasticsearch, DocumentDB, MongoDB).
  Their connection abstractions are separate.
- BigQuery — per user directive (2026-04-21): *"solo usaremos
  postgresql no necesitamos bigquery"*. Treat `BigQueryToolkit` as
  **not-in-scope**. It may remain on the existing SQLAlchemy/asyncdb
  paths OR be deleted in a follow-up; that decision is explicitly
  deferred.
- New public APIs. All signature changes are to private helpers or to
  the `DatabaseToolkit.__init__` kwarg `backend` (which currently has
  zero production callers — see D4).
- Performance work. Refactor should be cost-neutral.

---

## 2. Architectural Design

### Overview

Four coordinated modules, one framework refactor:

1. **Boundary unwrap** — `_acquire_asyncdb_connection` yields
   `driver.engine()` (raw `asyncpg.Connection`). Pool and direct paths
   both unwrap once; the wrapper is released to the pool on exit.

2. **`transaction()` on asyncpg native** — replace the current
   `async with conn.transaction():` (broken against wrapper) with a
   proper `asyncpg` native transaction block. Supports
   nested/savepoint via `async with raw_conn.transaction():` inside.

3. **Query builders → `$N` + positional tuple** — convert all
   `_get_*_query` builders in `sql.py` and `postgres.py` to emit
   asyncpg placeholders and return `(sql, tuple)` instead of
   `(sql, dict)`. Update `_execute_asyncdb` to accept a positional
   tuple and forward via `*args`.

4. **Delete SQLAlchemy path** — remove `backend` kwarg,
   `_connect_sqlalchemy`, `_execute_sqlalchemy`, `_build_sqlalchemy_dsn`,
   and all `if self.backend == "sqlalchemy":` / `elif ...:` branches.
   Update affected unit tests.

After Modules 1–4 land, a cleanup commit **removes the
`NavigatorToolkit._run_on_conn` override** (the FEAT-117 workaround)
and leaves a migration note in the Navigator docstring.

### Component Diagram

```
┌──────────────────────────────────────────────────────────────┐
│ Any SQLToolkit subclass (PostgresToolkit, NavigatorToolkit,  │
│   future-BigQueryToolkit if kept)                            │
└──────────────────┬───────────────────────────────────────────┘
                   │
                   ▼
     execute_sql / select_rows / CRUD / transaction()
                   │
                   ▼
     _execute_crud  ──►  asyncpg.Connection.fetch / fetchrow / execute
                                          ▲
     transaction()  ──►  asyncpg.Connection.transaction()  (native savepoints)
                                          ▲
                   ┌──────────────────────┘
                   │
     _acquire_asyncdb_connection
        │  yield driver.engine()   ◄── NEW: raw asyncpg at the boundary
        ▼
     asyncdb.drivers.pg  (wrapper acquired, immediately unwrapped)
```

### Integration Points (summary table)

| Component | Change | Risk |
|---|---|---|
| `DatabaseToolkit.__init__` | Remove `backend` kwarg | Low — zero production callers verified |
| `DatabaseToolkit._engine`, `_connect_sqlalchemy`, `_build_sqlalchemy_dsn` | Removed | Low |
| `BaseDatabaseToolkit._acquire_asyncdb_connection` | Yield raw asyncpg via `engine()` | Medium — downstream consumers assumed wrapper |
| `SQLToolkit._execute_asyncdb` | Accept positional tuple params | Medium |
| `SQLToolkit._get_*_query` (×4) | Emit `$N`, return `(sql, tuple)` | Low |
| `PostgresToolkit._get_*_query` overrides | Same | Low |
| `PostgresToolkit._run_on_conn` | Simplify body (no unwrap; just call asyncpg) | Low |
| `PostgresToolkit.transaction()` | Rewrite on asyncpg native CM | Medium — latent bug being fixed |
| `NavigatorToolkit._run_on_conn` | **Removed** (inherit parent again) | Low |
| Tests | Update init-validation tests; add boundary + transaction tests | Medium |
| `pyproject.toml` | Audit `sqlalchemy` runtime dep | Low |

---

## 3. Module Breakdown

### Module 1 — Connection boundary (yield raw asyncpg)
- **Path**: `packages/ai-parrot/src/parrot/bots/database/toolkits/base.py`
- **Responsibility**: `_acquire_asyncdb_connection` calls
  `driver.engine()` on the acquired asyncdb `pg` wrapper and yields the
  raw `asyncpg.Connection`. For the pool path, the wrapper is released
  (not the raw conn) on exit — `pgPool.release` already handles this
  (`asyncdb/drivers/pg.py:364-366`).

### Module 2 — Delete SQLAlchemy backend
- **Path**: `base.py`, `sql.py`, `postgres.py` (and `bigquery.py` if
  kept — TBD, see Non-Goals).
- **Responsibility**:
  - Drop `backend` field + constructor kwarg.
  - Delete `_connect_sqlalchemy`, `_build_sqlalchemy_dsn`, `_engine` attr.
  - Delete all `if self.backend == …:` branches in `execute_query`,
    `health_check`, `stop`, `_search_in_database`, `_build_table_metadata`.
  - Delete `SQLToolkit._execute_sqlalchemy`.
  - Delete subclass `_build_sqlalchemy_dsn` overrides.
  - Remove SQLAlchemy-mentioning docstrings.

### Module 3 — Query-builder parameter normalisation
- **Path**: `sql.py`, `postgres.py`.
- **Responsibility**: Convert all `_get_*_query` methods to emit
  `$1, $2, …` placeholders and return `(sql, tuple)`. Update
  `_execute_asyncdb` signature to accept positional tuple params and
  dispatch `await raw.fetch(sql, *params)`. Update all call sites
  (`_build_table_metadata`, `_search_in_database`).

### Module 4 — `transaction()` on asyncpg native
- **Path**: `postgres.py`.
- **Responsibility**: Rewrite `PostgresToolkit.transaction()` to:
  ```python
  async with self._acquire_asyncdb_connection() as raw_conn:
      async with raw_conn.transaction():
          yield raw_conn
  ```
  This gains native savepoint support (nested `raw_conn.transaction()`)
  at zero cost.

### Module 5 — Remove FEAT-117 override + tests + dep audit
- **Path**:
  - `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`
    → **delete** the `_run_on_conn` override added by FEAT-117.
  - `tests/unit/test_sql_toolkit.py`,
    `tests/unit/test_postgres_toolkit.py`,
    `tests/unit/test_database_toolkit_base.py` → update
    `backend="sqlalchemy"` assertions to assert the kwarg no longer
    exists (raises `TypeError`).
  - New: `tests/unit/bots/database/toolkits/test_acquire_conn_boundary.py`.
  - New: `tests/unit/bots/database/toolkits/test_transaction_savepoint.py`
    (live-DB gated).
  - New: `tests/unit/bots/database/toolkits/test_warm_cache_params.py`.
  - `pyproject.toml`: audit `sqlalchemy` runtime dep.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_acquire_asyncdb_yields_raw_asyncpg` | 1 | Mock driver with `engine()` → raw stub; assert raw stub is yielded. |
| `test_acquire_asyncdb_pool_releases_wrapper` | 1 | Pool path: `release()` receives the asyncdb wrapper, not the raw asyncpg conn. |
| `test_backend_kwarg_removed` | 2 | `DatabaseToolkit(dsn=..., backend="sqlalchemy")` raises `TypeError`. |
| `test_no_sqlalchemy_imports_at_module_level` | 2 | Static check: `sqlalchemy` not imported at top of `base.py`/`sql.py`/`postgres.py`. |
| `test_columns_query_emits_dollar_placeholders` | 3 | `_get_columns_query("auth", "programs")` → SQL contains `$1, $2` and params is `("auth", "programs")`. |
| `test_execute_asyncdb_forwards_tuple_params` | 3 | `_execute_asyncdb("SELECT $1", (42,))` calls `raw.fetch("SELECT $1", 42)`. |
| `test_build_table_metadata_populates_columns` | 3 | Warm-up returns `TableMetadata` with non-empty `columns`. |
| `test_transaction_yields_raw_asyncpg` | 4 | `async with toolkit.transaction() as tx:` → `tx.fetch` is asyncpg coroutine. |
| `test_transaction_savepoint_rollback` | 4 | Nested `async with tx.transaction():` rolls back inner, preserves outer (live DB gated). |
| `test_navigator_toolkit_no_local_override` | 5 | Assert `NavigatorToolkit.__dict__` does NOT contain `_run_on_conn` (inherits from parent). |

### Integration Tests

| Test | Description |
|---|---|
| `test_navigator_list_programs_live_db` | End-to-end: `NavigatorToolkit.list_programs()` against live PG test DB, no TypeError, returns list. |
| `test_warmup_populates_cache_live_db` | Warm-up over `auth.programs` → N/N warmed in logs. |

---

## 5. Acceptance Criteria

- [ ] `_acquire_asyncdb_connection` yields raw `asyncpg.Connection`.
- [ ] `PostgresToolkit._run_on_conn` calls asyncpg APIs directly (no unwrap guard).
- [ ] `PostgresToolkit.transaction()` yields raw asyncpg, supports nested savepoints.
- [ ] All `_get_*_query` builders return `(sql, tuple)` with `$N` placeholders.
- [ ] `backend` kwarg removed from `DatabaseToolkit.__init__`. No SQLAlchemy imports at module level.
- [ ] `NavigatorToolkit._run_on_conn` override (FEAT-117) deleted.
- [ ] Warm-up log shows `N/N warmed` (not `0/N`).
- [ ] Unit + integration tests green.
- [ ] No regressions in CRUD tests (insert/update/delete/upsert/transaction).
- [ ] `pyproject.toml` SQLAlchemy dependency audited (moved to optional or removed).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> All references verified 2026-04-21 against `dev` @ `e36acaa0`.
> **DO NOT IMPLEMENT WITHOUT LEAD APPROVAL** — verify again at implementation time (state may drift).

### Files to modify (verified paths + lines)

```
packages/ai-parrot/src/parrot/bots/database/toolkits/base.py
  - line 58         backend: str = Field(default="asyncdb", ...)
  - line 115        backend: str = "asyncdb",  (in __init__)
  - line 133        self.backend = backend
  - line 144        self._engine: Any = None
  - line 214-230    docstring + branches in _connect_asyncdb
  - line 248-253    _engine disposal in stop()
  - line 271-281    backend branches in health_check
  - line 378-399    _acquire_asyncdb_connection (Module 1 target)
  - line 401-426    _connect_sqlalchemy, _build_sqlalchemy_dsn (DELETE)

packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py
  - line 66, 78     backend param in __init__
  - line 195-198    backend branch in execute_query
  - line 242-245    backend branch in _explain
  - line 382-474    _get_*_query builders (Module 3 target)
  - line 487-508    _execute_asyncdb (Module 3 target — signature change)
  - line 510-536    _execute_sqlalchemy (DELETE)
  - line 550-595    backend branches in _search_in_database, _build_table_metadata
  - line 609-625    same

packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py
  - line 48, 82     backend param
  - line 96-147     _get_*_query overrides (Module 3)
  - line 149-155    _build_sqlalchemy_dsn (DELETE)
  - line 752-789    _execute_crud, _run_on_conn (simplify)
  - line 795-830    transaction() (Module 4 target — rewrite)

packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py
  - _run_on_conn override added by FEAT-117 (DELETE in Module 5)

tests/unit/test_sql_toolkit.py:36
tests/unit/test_database_toolkit_base.py:56
tests/unit/test_postgres_toolkit.py:81, 85

pyproject.toml (audit sqlalchemy runtime dep)
```

### asyncdb external dependency

```python
# .venv/lib/python3.11/site-packages/asyncdb/interfaces/abstract.py
class AbstractDriver:
    def get_connection(self): ...                   # line 66
    engine = get_connection                         # line 69

# .venv/lib/python3.11/site-packages/asyncdb/drivers/pg.py
class pg(SQLDriver, DBCursorBackend, ModelBackend):
    async def connection(self): ...                 # line 625 — sets self._connection to asyncpg.Connection
class pgPool(BasePool):
    async def acquire(self) -> pg: ...              # line 321
    async def release(self, connection=None, ...)   # line 356 — accepts wrapper or raw
```

### Dead-code census (verified)

`backend="sqlalchemy"` production callers: **0** (confirmed via `grep -rn`
excluding `.venv`, `.claude/worktrees`, test files, SDD docs).

```
packages/ai-parrot/.../base.py:214             docstring only
tests/unit/test_sql_toolkit.py:36              init-only test
tests/unit/test_database_toolkit_base.py:56    init-only test
tests/unit/test_postgres_toolkit.py:81, 85     init-only test
```

### Does NOT Exist (Anti-Hallucination)

- ~~`asyncpg.Connection.savepoint()`~~ — savepoints are nested `transaction()` blocks.
- ~~`asyncdb.drivers.pg.pg.raw_connection()`~~ — use `engine()` alias.
- ~~Keeping a `backend="asyncdb"` kwarg "for backward compatibility"~~ — lead rejects.
- ~~Translating `:name` → `$N` at execute time~~ — normalise at builder time (Module 3).

---

## 7. Implementation Notes & Constraints

### Patterns

- Unwrap once, at the boundary. Downstream consumers never see the wrapper.
- Single parameter style (`$N`) on the asyncdb path.
- Native asyncpg transactions with savepoints.
- No compatibility shims. If an external caller is using the old
  `backend=` kwarg, let it fail loudly; the fix is to stop passing it.

### Known Risks

- **Hidden external consumer of `backend="sqlalchemy"`**: repo-wide grep
  is clean, but external packages could theoretically import the
  toolkits. Mitigation: bump a minor version; CHANGELOG note.
- **Latent `transaction()` callers**: if any in-repo code called
  `transaction()` and relied on its current (broken?) behaviour, Module
  4 will reveal it. Audit before implementing.
- **`pgPool.release` receiving the raw conn instead of wrapper**:
  `pgPool.release` handles both (checks `isinstance(conn, pg)` at
  `pg.py:364`), but verify with a pool-path test.
- **BigQuery divergence**: if we decide to keep BigQuery, it may require
  a different placeholder style. Per Non-Goals, punt.

### External Dependencies

| Package | Status after refactor |
|---|---|
| `asyncdb` | unchanged (still used — we just unwrap earlier) |
| `asyncpg` | same (transitive via asyncdb) |
| `sqlalchemy` | **candidate for removal from runtime deps** |

---

## 8. Open Questions (for lead review)

- [ ] **Q-A**: BigQueryToolkit — keep, delete, or defer? User said
      postgres-only is fine; if BigQuery is truly unused, deleting it
      would remove the last obstacle to full SQLAlchemy removal. —
      *Owner: jleon + Jesús*
- [ ] **Q-B**: Remove `backend=` kwarg without a deprecation cycle, or
      keep a one-release grace with a `DeprecationWarning`? Jesús'
      preference seemed absolute ("one for everything") — implies hard
      remove. — *Owner: Jesús*
- [ ] **Q-C**: Should `transaction()` return the raw asyncpg conn
      directly, or wrap it in a lightweight `Transaction` helper that
      intercepts `execute_sql(conn=tx)` calls and auto-routes? Current
      code paths pass the `conn` through unchanged, so raw is simpler.
      — *Owner: Jesús*
- [ ] **Q-D**: Convert SDD task generation for this spec only after
      approval (current state: frozen as draft). No tasks should exist
      in `sdd/tasks/active/` for FEAT-118 until `status: approved`.
      — *Owner: jleon*

---

## Worktree Strategy

Not applicable until approved. When status → `approved`:

```bash
git worktree add -b feat-118-database-toolkit-asyncpg-boundary-refactor \
  .claude/worktrees/feat-118-database-toolkit-asyncpg-boundary-refactor HEAD
```

Task ordering inside the worktree (draft):

```
Module 1 (boundary unwrap)
   └── Module 4 (transaction on asyncpg native)
         └── Module 2 (delete SQLAlchemy path)
               └── Module 3 (query-builder param normalisation)
                     └── Module 5 (remove FEAT-117 override + tests + dep audit)
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-21 | Javier León | Initial draft — captures the framework-wide proposal that was considered and deferred during FEAT-117. Frozen as `draft — awaiting lead review` pending Jesús Lara sign-off. Includes verbatim Telegram feedback. |

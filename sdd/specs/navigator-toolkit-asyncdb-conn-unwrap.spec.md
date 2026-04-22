# Feature Specification: NavigatorToolkit — Local asyncpg Conn Unwrap

**Feature ID**: FEAT-117
**Date**: 2026-04-21
**Author**: Javier León
**Status**: approved
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

Reproduced in production on the Telegram agent:

- `nav_list_modules` → `Error in nav_list_modules: pg.fetch() takes …`
- `nav_list_programs` → same
- `nav_search` → same

Root cause (verified): `PostgresToolkit._run_on_conn`
(`packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py:772`)
calls `conn.fetch(sql, *args)` / `conn.fetchrow(sql, *args)` /
`conn.execute(sql, *args)` assuming `conn` is a raw `asyncpg.Connection`.
In reality `BaseDatabaseToolkit._acquire_asyncdb_connection`
(`.../base.py:378`) yields the asyncdb `pg` driver wrapper, whose
`fetch(self, number=1)` is a cursor-advance helper that does not accept
SQL text.

### Constraint

**We will NOT modify the AI-Parrot framework in this spec.** The framework
is consumed by multiple toolkits and a rewrite there needs its own spec
and review cycle (see `Revision History → 0.2` where a broader
framework-level rewrite was considered and deferred). This feature keeps
all changes inside the Navigator toolkit package so the fix can ship
independently and without coordinating a framework release.

### Goals

- Restore NavigatorToolkit tool functionality (`nav_list_modules`,
  `nav_list_programs`, `nav_search`, and every NavigatorToolkit method
  that routes through `execute_sql` / `select_rows` / CRUD helpers).
- Do so **only** by overriding behaviour inside
  `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`.
- Leave the framework (`packages/ai-parrot/…/bots/database/toolkits/`)
  untouched.
- Add a regression test under
  `tests/unit/.../navigator/` that would have caught this defect.

### Non-Goals

- Any change to `PostgresToolkit`, `SQLToolkit`, or `BaseDatabaseToolkit`.
- Any change to asyncdb integration for other toolkits (BigQuery, Influx,
  Elastic, DocumentDB, etc.).
- Fixing the adjacent `_execute_asyncdb` warm-up bug (metadata warm-up
  logs `Warm-up skipped <schema>.<table>`; non-fatal — metadata is
  built lazily on first CRUD call). Documented as "Known limitation"
  for a future framework spec.
- Rewriting `PostgresToolkit.transaction()` to use asyncpg native
  savepoints. Out of scope; lives in framework.
- Deprecating the SQLAlchemy backend path in the framework. Out of scope.
- BigQuery / non-postgres driver work — Navigator is PostgreSQL only.

---

## 2. Architectural Design

### Overview

NavigatorToolkit inherits `PostgresToolkit` (verified: `toolkit.py:40`
`class NavigatorToolkit(PostgresToolkit):`).

`PostgresToolkit._execute_crud` calls `self._run_on_conn(...)`
(`postgres.py:767, 770`). Because Python method resolution follows MRO,
**any `_run_on_conn` defined on `NavigatorToolkit` overrides the parent
implementation** — even though it is declared `@staticmethod`.

The fix is therefore a single local override: unwrap the asyncdb `pg`
driver to a raw `asyncpg.Connection` via `driver.engine()` (alias of
`get_connection()`, verified at
`.venv/.../asyncdb/interfaces/abstract.py:66-69`) and then call asyncpg's
native `.fetch / .fetchrow / .execute` with positional SQL args.

### Component Diagram

```
NavigatorToolkit.list_programs / list_modules / search_database / CRUD
        │
        ▼
(inherited) PostgresToolkit.execute_sql / select_rows
        │
        ▼
(inherited) PostgresToolkit._execute_crud
        │
        ▼ self._run_on_conn(...)   ◄── resolved via MRO to NavigatorToolkit override
        ▼
NavigatorToolkit._run_on_conn   ◄── NEW local override
        │   conn = driver.engine()  (unwrap asyncdb → raw asyncpg.Connection)
        ▼
asyncpg.Connection.fetch / fetchrow / execute
```

### Integration Points

| Component | Change | Notes |
|---|---|---|
| `NavigatorToolkit` | **add method** `_run_on_conn` | Static method, identical signature to parent. Overrides via MRO. |
| `PostgresToolkit._run_on_conn` | **no change** | Stays broken for other subclasses; their fix is out of scope. |
| `PostgresToolkit._execute_crud` | **no change** | Already calls `self._run_on_conn` — dispatches to override automatically. |
| `BaseDatabaseToolkit._acquire_asyncdb_connection` | **no change** | Keeps yielding the asyncdb wrapper. Unwrap is local to the override. |
| Tests | **new file** | `tests/unit/parrot_tools/navigator/test_toolkit_run_on_conn.py`. |

### Data Models

None. No new Pydantic models, no new schemas.

### New Public Interfaces

None. `_run_on_conn` is private (leading underscore) and the
override is signature-compatible with the parent.

---

## 3. Module Breakdown

### Module 1 — `NavigatorToolkit._run_on_conn` override

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`
- **Responsibility**: Unwrap the asyncdb `pg` wrapper yielded by
  `_acquire_asyncdb_connection` to a raw `asyncpg.Connection` via
  `driver.engine()` before dispatching. Preserve the exact same
  result shapes as the parent (`dict(row)`, list-of-dict, `{"status": "ok"}`).
- **Depends on**:
  - `asyncdb.interfaces.abstract.AbstractDriver.engine` (alias of
    `get_connection`, `interfaces/abstract.py:66-69`).
  - Parent contract: `_execute_crud` continues to pass `conn` through as
    the last-yielded value of `_acquire_asyncdb_connection` (which is the
    asyncdb wrapper today).

Implementation sketch (for reference; final code belongs in tasks):

```python
# NavigatorToolkit (packages/ai-parrot-tools/.../navigator/toolkit.py)

@staticmethod
async def _run_on_conn(sql, args, returning, conn, single_row):
    """Navigator-local override — unwrap asyncdb pg wrapper to raw asyncpg.

    Parent PostgresToolkit._run_on_conn calls asyncpg-style APIs on an
    asyncdb wrapper, which fails with:
      `pg.fetch() takes from 1 to 2 positional arguments but 3 were given`.
    Fix is local (scope-bounded to Navigator) via MRO override.
    """
    raw = conn.engine() if hasattr(conn, "engine") and callable(conn.engine) else conn
    if not returning:
        await raw.execute(sql, *args)
        return {"status": "ok"}
    if single_row:
        row = await raw.fetchrow(sql, *args)
        return dict(row) if row else {}
    rows = await raw.fetch(sql, *args)
    return [dict(r) for r in rows] if rows else []
```

### Module 2 — Regression test for `_run_on_conn`

- **Path**:
  `tests/unit/test_navigator_toolkit_run_on_conn.py` (new).
- **Responsibility**: Lock down the override. Three tests:
  1. Called with an asyncdb-wrapper stub (exposing `engine()` → raw stub) →
     dispatches to raw stub's `fetch`, not the wrapper's.
  2. Called with a raw asyncpg-style stub (no `engine`) → dispatches
     directly to that stub (fallback path).
  3. `returning=False` path → calls `execute`, returns `{"status": "ok"}`.
- **Depends on**: Module 1.

### Module 3 — `_build_table_metadata` override (added v0.4)

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`
- **Responsibility**: Override `_build_table_metadata` on
  `NavigatorToolkit`. Run columns / PK / UNIQUE introspection queries
  directly against raw asyncpg with positional `$1 / $2` placeholders.
  Populates `cache_partition` correctly during warm-up so downstream
  `_resolve_table` calls find the metadata.
- **Depends on**: Module 1 (same asyncdb → asyncpg unwrap pattern).
- **Retroactive task**: TASK-824. Shipped in commit `adad570d`.

### Module 4 — `transaction()` override (added v0.4)

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`
- **Responsibility**: Override `PostgresToolkit.transaction()` to run
  on raw `asyncpg.Connection.transaction()` (a proper async context
  manager). Yields the raw asyncpg connection so downstream CRUD
  calls (via `_run_on_conn`) treat `conn` as already-unwrapped.
- **Depends on**: Module 1.
- **Retroactive task**: TASK-825. Shipped in commit `4a55dd1f`.

### Module 5 — Regression tests for Modules 3 + 4 (added v0.4)

- **Path**: `tests/unit/test_navigator_toolkit_metadata_and_tx.py`
  (new).
- **Responsibility**: Lock down both overrides:
  1. `_build_table_metadata` runs the three introspection queries
     with positional params, produces a populated `TableMetadata`.
  2. `transaction()` acquires a raw asyncpg and yields it inside a
     proper CM (the asyncdb wrapper's broken `transaction()` is never
     invoked — wrapper stub raises if called).
- **Depends on**: Modules 3 + 4.
- **New task**: TASK-826.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_run_on_conn_unwraps_asyncdb_wrapper` | Module 2 | Wrapper's `engine()` is called; raw stub's `fetch(sql, *args)` receives both sql and positional params. Wrapper's own `fetch` must NOT be invoked (it would raise cursor-signature error). |
| `test_run_on_conn_passes_raw_conn_when_no_engine` | Module 2 | Graceful fallback — object without `engine` attribute is used directly. |
| `test_run_on_conn_fetchrow_single_row` | Module 2 | `single_row=True` returns `dict(row)` or `{}`. |
| `test_run_on_conn_execute_only` | Module 2 | `returning=False` returns `{"status": "ok"}`. |
| `test_run_on_conn_multi_row` | Module 2 | Default path returns `[dict(r) for r in rows]`. |

### Integration Tests

| Test | Description |
|---|---|
| `test_list_programs_against_live_db` (optional, gated by `POSTGRES_TEST_DSN`) | `NavigatorToolkit.list_programs()` against a real test DB completes without raising the `pg.fetch()` TypeError. |

### Test Data / Fixtures

```python
@pytest.fixture
def fake_raw_asyncpg_conn():
    class Raw:
        calls: list[tuple] = []
        async def fetch(self, sql, *args):
            Raw.calls.append(("fetch", sql, args))
            return [{"program_id": 1, "program_name": "demo"}]
        async def fetchrow(self, sql, *args):
            Raw.calls.append(("fetchrow", sql, args))
            return {"program_id": 1}
        async def execute(self, sql, *args):
            Raw.calls.append(("execute", sql, args))
            return "OK"
    return Raw()

@pytest.fixture
def fake_asyncdb_wrapper(fake_raw_asyncpg_conn):
    class Wrapper:
        def engine(self):
            return fake_raw_asyncpg_conn
        # These mirror the asyncdb pg.fetch / pg.fetchrow cursor-advance
        # signatures — they must NOT be called by the override.
        async def fetch(self, number=1):
            raise AssertionError("wrapper.fetch should not be called")
        async def fetchrow(self):
            raise AssertionError("wrapper.fetchrow should not be called")
    return Wrapper()
```

---

## 5. Acceptance Criteria

- [ ] `NavigatorToolkit` defines a local `_run_on_conn` that unwraps the
      asyncdb `pg` wrapper via `engine()` before calling asyncpg APIs.
- [ ] All unit tests in Module 2 pass.
- [ ] Manual smoke test: Telegram agent → `"necesito me digas el último
      módulo creado …"` no longer logs the `pg.fetch()` TypeError;
      `nav_list_modules` / `nav_list_programs` / `nav_search` return
      results.
- [ ] No file under `packages/ai-parrot/` is modified in this feature.
- [ ] No file under `packages/ai-parrot-tools/src/parrot_tools/` other
      than `navigator/toolkit.py` (and the new test file) is modified.
- [ ] Existing NavigatorToolkit write/CRUD tests (if any) still pass.
- [ ] A brief note is added to the NavigatorToolkit class docstring
      explaining why the override exists (points to this FEAT-117 spec
      so a future framework fix can remove it).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-04-21 against `dev` HEAD (commit `90d7051c`, post-v0.1
> of this spec) and `.venv/…/asyncdb` installed copy.

### Verified Imports

```python
# Already imported at the top of navigator/toolkit.py — no new imports required.
from parrot.bots.database.toolkits.postgres import PostgresToolkit  # line 21
from parrot.tools.decorators import tool_schema                     # line 22
from typing import Any, Dict, List, Optional                        # line 20

# Test-side (new file):
import pytest
import pytest_asyncio
```

### Existing Class Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py
class NavigatorToolkit(PostgresToolkit):                    # line 40
    """FEAT-106 / TASK-744: inherits PostgresToolkit."""
    # <40 public tool methods: create_program, list_programs,
    #  create_module, list_modules, create_dashboard, create_widget,
    #  search (nav_search), etc. — all inherited-execute_sql-bound.>
```

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py
class PostgresToolkit(SQLToolkit):
    async def execute_sql(...) -> Any:             # line 682 — consumed as-is
    async def select_rows(...) -> List[Dict]:      # line 616 — consumed as-is
    async def _execute_crud(...) -> Any:           # line 752 — consumed as-is
    @staticmethod
    async def _run_on_conn(                         # line 772 — OVERRIDDEN via MRO
        sql: str,
        args: tuple[Any, ...],
        returning: Optional[List[str]],
        conn: Any,
        single_row: bool,
    ) -> Any: ...
```

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/base.py
class BaseDatabaseToolkit:
    @asynccontextmanager
    async def _acquire_asyncdb_connection(          # line 378 — consumed as-is
        self,
    ) -> AsyncIterator[Any]:
        """Yields the asyncdb pg driver wrapper (pool or direct path)."""
```

### asyncdb external dependency — verified

```python
# .venv/lib/python3.11/site-packages/asyncdb/interfaces/abstract.py
class AbstractDriver:
    def get_connection(self): ...                  # line 66 — returns raw asyncpg
    engine = get_connection                        # line 69 — alias used by override
```

```python
# .venv/lib/python3.11/site-packages/asyncdb/drivers/pg.py
class pg(SQLDriver, DBCursorBackend, ModelBackend):
    async def fetch(self, number=1): ...           # line 981 — cursor-advance (DO NOT call with sql)
    async def fetchrow(self): ...                  # line 988 — cursor-advance
    # engine() inherited from AbstractDriver — returns self._connection (asyncpg.Connection)
```

### Does NOT Exist (Anti-Hallucination)

- ~~`NavigatorToolkit._unwrap_conn()` helper method~~ — do not invent.
  The unwrap is inline inside the `_run_on_conn` override (≤2 lines).
- ~~Modifying `PostgresToolkit._run_on_conn` directly~~ — explicitly
  out of scope per user directive (no framework changes).
- ~~Modifying `SQLToolkit._execute_asyncdb` to fix warm-up~~ — out of scope.
  Warm-up is non-fatal (fallback: lazy metadata on first CRUD).
- ~~Overriding `PostgresToolkit.transaction()` in NavigatorToolkit~~ —
  NavigatorToolkit does not currently call `transaction()` in any write
  tool that is reachable from the LLM (writes use the parent's transaction
  helper via inherited CRUD). Verified via grep: `transaction(` appears
  in `toolkit.py` but only as `async with self.transaction():` which
  inherits the parent implementation. If `transaction()` is ALSO broken
  on the asyncdb wrapper, that is a latent framework bug captured in the
  follow-up framework spec, not here.
- ~~`conn.raw_connection()`~~ — not a method; use `engine()` / `get_connection()`.
- ~~Catching and re-raising `TypeError` as a workaround~~ — fix the
  call shape, do not paper over it.

### Integration Points

| New Code | Connects To | Via | Verified At |
|---|---|---|---|
| `NavigatorToolkit._run_on_conn` | `asyncdb.AbstractDriver.engine()` | method call | `asyncdb/interfaces/abstract.py:66-69` |
| `NavigatorToolkit._run_on_conn` | raw `asyncpg.Connection.fetch / fetchrow / execute` | method call | `asyncdb/drivers/pg.py:625-660` (asyncpg connection is stored in `self._connection` and exposed via `engine()`) |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Keep the override a `@staticmethod` — matches the parent signature and
  avoids an accidental change to how `_execute_crud` dispatches.
- Preserve return shapes **byte-for-byte** from the parent:
  - `returning=False` → `{"status": "ok"}`
  - `single_row=True` → `dict(row) if row else {}`
  - otherwise → `[dict(r) for r in rows] if rows else []`
- Use the `hasattr(conn, "engine") and callable(conn.engine)` guard so
  the override also works if a future framework fix starts yielding raw
  asyncpg directly (graceful forward compatibility).
- Reference this spec in the override's docstring so a future framework
  fix can remove the override cleanly.

### ⚠️ Premise Corrections (v0.4 — 2026-04-21)

v0.3 of this spec assumed two things that were **wrong**:

1. **Warm-up failure is non-fatal** — WRONG.
   Premise: metadata is "built lazily on first CRUD call". Reality:
   `PostgresToolkit._resolve_table` (`postgres.py:213`) *raises*
   `RuntimeError("No cached metadata for <table>. Call await
   toolkit.start() first")` when the cache entry is missing. There
   is no lazy rebuild path. After TASK-822 landed, the very first
   `nav_list_clients` call in production failed with that
   `RuntimeError`, surfacing the defect.
2. **`transaction()` is out of scope** — WRONG.
   Premise: "not exercised by the failing tools". Reality:
   `nav_create_dashboard` uses `async with self.transaction():`
   which immediately failed with
   `'coroutine' object does not support the asynchronous context
   manager protocol` because `conn.transaction()` on the asyncdb
   `pg` wrapper is an `async def` (returns `self`), not a context
   manager.

Both defects share the same root cause as TASK-822 — the asyncdb
driver wrapper masquerading where raw asyncpg was expected. They
are therefore **in-scope for FEAT-117** as additional modules, with
retroactive tasks TASK-824 (`_build_table_metadata` override),
TASK-825 (`transaction()` override), and TASK-826 (tests).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `asyncdb` | pinned (no bump) | Provides the `engine()` alias. |
| `asyncpg` | via asyncdb (no bump) | Raw connection APIs. |

---

## 8. Open Questions

- [x] **Q1 — Follow-up framework spec**: RESOLVED 2026-04-21.
      Framework-wide fix captured as **FEAT-118**
      (`sdd/specs/database-toolkit-asyncpg-boundary-refactor.spec.md`),
      status `draft — awaiting lead review`. Generated in parallel with
      FEAT-117 so the diagnostic context is preserved. Autonomous agents
      must NOT implement FEAT-118 until the lead approves it. FEAT-118
      Module 5 includes a task to **remove the
      `NavigatorToolkit._run_on_conn` override** introduced here.
- [ ] **Q2 — Warm-up visibility**: should NavigatorToolkit suppress or
      downgrade the `Warm-up skipped …` warnings for its whitelist until
      the framework fix lands (they're noisy and non-actionable at the
      toolkit level)? *Owner: jleon*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (two tasks, sequential).
- Worktree branch: `feat-117-navigator-toolkit-asyncdb-conn-unwrap`.
- No cross-feature dependencies; branches off `dev`.

```bash
git worktree add -b feat-117-navigator-toolkit-asyncdb-conn-unwrap \
  .claude/worktrees/feat-117-navigator-toolkit-asyncdb-conn-unwrap HEAD
```

Task ordering: Module 1 → Module 2 → Module 3 (retroactive) → Module 4 (retroactive) → Module 5.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-20 | Javier León | Initial draft — regression fix scoped to `PostgresToolkit._run_on_conn` + warm-up fix. |
| 0.2 | 2026-04-20 | Javier León | Lead-review v1: proposed framework-wide rewrite (yield raw asyncpg, deprecate SQLAlchemy, rewrite `transaction()`, normalise query builders). |
| 0.3 | 2026-04-21 | Javier León | Scope reduced per user directive: **no framework changes**. Fix is a local `_run_on_conn` override inside `NavigatorToolkit`. Framework-level work deferred to a follow-up spec (Q1). |
| 0.4 | 2026-04-21 | Javier León | Premise corrections: warm-up failure IS fatal (no lazy rebuild in `_resolve_table`) and `transaction()` is also broken. Added Modules 3 + 4 (retroactive overrides, shipped as commits `adad570d` + `4a55dd1f`) and Module 5 (tests to land under TASK-826). |

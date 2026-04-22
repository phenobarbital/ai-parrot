# TASK-833: NavigatorToolkit `_run_on_conn` override — unwrap asyncdb to raw asyncpg

**Feature**: FEAT-117 — Navigator Toolkit asyncdb Connection Unwrap
**Spec**: `sdd/specs/navigator-toolkit-asyncdb-conn-unwrap.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-107 (`c1e93b8d`, TASK-743) migrated NavigatorToolkit CRUD onto
`PostgresToolkit.execute_sql` / `select_rows`, which bottom out in
`PostgresToolkit._run_on_conn`. That method assumes `conn` is a raw
`asyncpg.Connection` and calls `conn.fetch(sql, *args)` — but
`_acquire_asyncdb_connection` actually yields the **asyncdb `pg` driver
wrapper**, whose `fetch(self, number=1)` is a cursor-advance helper that
does not accept SQL text.

Observed failure in production (Telegram agent):

```
[ERROR] nav_list_modules.Tool(abstract.py:478) :: Error in nav_list_modules:
  pg.fetch() takes from 1 to 2 positional arguments but 3 were given
```

Same error reproduces on `nav_list_programs`, `nav_search`, and every
NavigatorToolkit tool that routes through `execute_sql` / `select_rows`.

**Scope constraint**: FEAT-117 must NOT modify the AI-Parrot framework
(`packages/ai-parrot/`). The framework-level fix is tracked separately
as **FEAT-118** (status `draft — awaiting lead review`). This task
implements the minimal, scope-bounded workaround: a local override of
`_run_on_conn` inside `NavigatorToolkit` that unwraps the asyncdb
wrapper via `driver.engine()` and dispatches to raw asyncpg.

Implements **Module 1** of the spec.

---

## Scope

- Add a `@staticmethod` `_run_on_conn` to `NavigatorToolkit`
  (`packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`).
- The override MUST:
  - Have identical signature to
    `PostgresToolkit._run_on_conn(sql, args, returning, conn, single_row)`.
  - Unwrap via `conn.engine()` when `conn` exposes a callable `engine`
    attribute (the asyncdb path).
  - Fall through to using `conn` directly when no `engine` attribute is
    present (forward-compat with a future framework fix that yields raw
    asyncpg from the boundary).
  - Preserve byte-for-byte the parent's return shapes:
    - `returning=False` → `{"status": "ok"}`
    - `returning=<cols>, single_row=True` → `dict(row) if row else {}`
    - `returning=<cols>, single_row=False` → `[dict(r) for r in rows] if rows else []`
- Add a docstring to the override that:
  - States why the override exists (references the spec by ID/path).
  - Flags it as **temporary** (to be removed when FEAT-118 lands).

**NOT in scope**:
- Any change under `packages/ai-parrot/` (framework).
- Any change to `SQLToolkit._execute_asyncdb` (warm-up fix — framework).
- Any change to `PostgresToolkit.transaction()` — framework.
- Any change to query builders (SQLAlchemy-style `:name` placeholders) — framework.
- Unit tests — those land in TASK-834.
- Silencing the `Warm-up skipped ...` log warnings (Q2 in the spec).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` | MODIFY | Add `_run_on_conn` `@staticmethod` override on `NavigatorToolkit`. Add a brief note to the class docstring pointing at FEAT-117. |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-04-21 against `dev` @ commit `25122b41`.

### Verified Imports

Already present in `navigator/toolkit.py` — **no new imports required**:

```python
from parrot.bots.database.toolkits.postgres import PostgresToolkit  # line 21
from parrot.tools.decorators import tool_schema                     # line 22
from typing import Any, Dict, List, Optional                        # line 20
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py
class NavigatorToolkit(PostgresToolkit):   # line 40
    """FEAT-106 / TASK-744: inherits PostgresToolkit.
    DB plumbing delegated to parent (asyncdb pool via
    _acquire_asyncdb_connection)."""
```

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py
class PostgresToolkit(SQLToolkit):
    async def _execute_crud(                         # line 752
        self, sql: str, args: tuple[Any, ...],
        returning: Optional[List[str]],
        conn: Optional[Any], single_row: bool,
    ) -> Any:
        if conn is not None:
            return await self._run_on_conn(sql, args, returning, conn, single_row)   # line 767
        async with self._acquire_asyncdb_connection() as acquired_conn:
            return await self._run_on_conn(sql, args, returning, acquired_conn, single_row)   # line 770

    @staticmethod
    async def _run_on_conn(                           # line 772 — BEING OVERRIDDEN via MRO
        sql: str, args: tuple[Any, ...],
        returning: Optional[List[str]],
        conn: Any, single_row: bool,
    ) -> Any:
        """Execute on a concrete connection object."""
        if not returning:
            await conn.execute(sql, *args)
            return {"status": "ok"}
        if single_row:
            row = await conn.fetchrow(sql, *args)
            return dict(row) if row else {}
        rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows] if rows else []
```

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/base.py
class BaseDatabaseToolkit:
    @asynccontextmanager
    async def _acquire_asyncdb_connection(            # line 378
        self,
    ) -> AsyncIterator[Any]:
        """Yields the asyncdb pg driver wrapper (pool or direct path)."""
```

### asyncdb external API — verified

```python
# .venv/lib/python3.11/site-packages/asyncdb/interfaces/abstract.py
class AbstractDriver:
    def get_connection(self): ...     # line 66 — returns raw asyncpg.Connection
    engine = get_connection           # line 69 — alias used by this override
```

```python
# .venv/lib/python3.11/site-packages/asyncdb/drivers/pg.py
class pg(SQLDriver, DBCursorBackend, ModelBackend):
    async def fetch(self, number=1): ...   # line 981 — cursor-advance (NOT to be called with sql+args)
    async def fetchrow(self): ...          # line 988 — cursor-advance (NOT to be called with sql+args)
```

### Does NOT Exist

- ~~`NavigatorToolkit._unwrap_conn()`~~ helper method — do not invent.
  The unwrap is inline inside `_run_on_conn` (≤2 lines, trivial).
- ~~`conn.raw_connection()`~~ — not a method; asyncdb exposes `engine()`
  / `get_connection()`.
- ~~Overriding `PostgresToolkit._run_on_conn` directly in the framework~~
  — explicitly out of scope. That's FEAT-118 territory.
- ~~Overriding `_execute_crud` instead of `_run_on_conn`~~ — unnecessarily
  broader surface; MRO on `_run_on_conn` is sufficient and minimal.
- ~~Wrapping the call in try/except `TypeError`~~ — do not paper over
  the shape bug; fix the call.

---

## Implementation Notes

### Pattern to Follow

Drop-in override on `NavigatorToolkit` — place immediately after
`__init__` or as the first method block for discoverability. Must be
marked `@staticmethod` to match the parent signature and ensure
`self._run_on_conn(...)` dispatch from `_execute_crud` resolves
cleanly via MRO.

```python
class NavigatorToolkit(PostgresToolkit):
    # ... existing class body ...

    @staticmethod
    async def _run_on_conn(sql, args, returning, conn, single_row):
        """Navigator-local override — unwrap asyncdb pg wrapper to raw asyncpg.

        The parent ``PostgresToolkit._run_on_conn`` calls asyncpg-style
        APIs on a ``conn`` that is actually the asyncdb ``pg`` driver
        wrapper yielded by ``_acquire_asyncdb_connection``.  That fails
        at runtime with::

            pg.fetch() takes from 1 to 2 positional arguments but 3 were given

        This override unwraps the driver via ``engine()`` (alias of
        ``get_connection()``; ``asyncdb/interfaces/abstract.py:66-69``)
        before dispatching.

        TEMPORARY — remove when FEAT-118 lands (framework-level fix:
        ``sdd/specs/database-toolkit-asyncpg-boundary-refactor.spec.md``).
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

### Key Constraints

- `@staticmethod` — **required**. The parent is static; do not introduce
  a `self` parameter (it would not break MRO, but would drift from the
  parent signature).
- Do not import `asyncpg` — we rely only on asyncdb's `engine()` alias
  and duck-typed `fetch / fetchrow / execute` calls.
- Do not log from inside this override — the parent doesn't, and adding
  logging would change behaviour on every CRUD call.
- Keep the override under 20 lines of code (excluding docstring) — it
  is meant to be trivially auditable.

### Brief docstring note on the class

At the top of `NavigatorToolkit`'s docstring (around lines 41-50 of
`toolkit.py`), add a one-line note pointing at FEAT-117:

> *Temporary `_run_on_conn` override (FEAT-117) unwraps the asyncdb `pg`
> wrapper to raw `asyncpg`. Remove once FEAT-118 lands.*

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py:772-789`
  — the parent implementation being overridden (do not modify).
- `packages/ai-parrot/src/parrot/bots/database/toolkits/base.py:378-399`
  — the async context manager whose yielded value needs unwrapping.
- `.venv/.../asyncdb/interfaces/abstract.py:66-69` — `engine()` alias contract.

---

## Acceptance Criteria

- [ ] `NavigatorToolkit` defines `_run_on_conn` as a `@staticmethod`
      with exactly the signature `(sql, args, returning, conn, single_row)`.
- [ ] The override calls `conn.engine()` via a
      `hasattr(conn, "engine") and callable(conn.engine)` guard before
      dispatching to `fetch / fetchrow / execute`.
- [ ] Return shapes match the parent byte-for-byte (same three branches).
- [ ] Docstring references FEAT-117 and states the override is temporary
      (to be removed when FEAT-118 lands).
- [ ] Class docstring gains a one-line note about the override.
- [ ] **No file under `packages/ai-parrot/` is modified.**
- [ ] **No file under `packages/ai-parrot-tools/src/parrot_tools/` other
      than `navigator/toolkit.py` is modified.**
- [ ] Python import still resolves: `from parrot_tools.navigator.toolkit
      import NavigatorToolkit` works.
- [ ] Linting: `ruff check packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` passes.

---

## Test Specification

Unit tests land in TASK-834. For THIS task the smoke validation is
import-only:

```python
# quick sanity check (not a formal test — TASK-834 covers that)
from parrot_tools.navigator.toolkit import NavigatorToolkit
assert "_run_on_conn" in NavigatorToolkit.__dict__, \
    "Override must be defined directly on NavigatorToolkit (not inherited)."
assert isinstance(NavigatorToolkit.__dict__["_run_on_conn"], staticmethod), \
    "_run_on_conn must be a @staticmethod (matches parent)."
```

---

## Agent Instructions

1. Read the spec: `sdd/specs/navigator-toolkit-asyncdb-conn-unwrap.spec.md`.
2. No dependencies — start immediately.
3. Verify the codebase contract:
   - `grep -n "class NavigatorToolkit" packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`
     → expect a hit around line 40.
   - `grep -n "_run_on_conn\|_execute_crud" packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py`
     → expect lines 752/767/770/772.
4. Update `sdd/tasks/.index.json` → this task to `in-progress`.
5. Implement the override per the pattern above. Keep it under 20 LOC.
6. Verify acceptance criteria.
7. Move this file to `sdd/tasks/completed/`.
8. Update index → `done`.
9. Fill in the Completion Note.

---

## Completion Note

**Completed by**: Claude Code (Opus 4.7) via /sdd-start
**Date**: 2026-04-21
**Commit**: `f5def1e5` on branch `feat-117-navigator-toolkit-asyncdb-conn-unwrap`

**Notes**:
- Added `@staticmethod _run_on_conn` on `NavigatorToolkit`
  (`packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py:181-212`).
- Signature matches parent exactly: `(sql, args, returning, conn, single_row)`.
- Unwraps asyncdb `pg` wrapper via `conn.engine()` guarded by
  `hasattr(conn, "engine") and callable(conn.engine)`; falls through to
  raw `conn` when the attribute is absent (forward-compat with FEAT-118).
- Return shapes byte-identical to parent: `{"status": "ok"}` /
  `dict(row) if row else {}` / `[dict(r) for r in rows] if rows else []`.
- Class docstring gains a one-line note pointing at FEAT-117 and flagging
  the override as temporary (to be removed when FEAT-118 lands).
- Body is 9 LOC (well under the 20-LOC target in the implementation notes).

**Verification performed**:
- AST-level check: `_run_on_conn` present on `NavigatorToolkit`, is
  `@staticmethod`, args match.
- `python -m compileall` clean.
- Standalone behavioural smoke test (6 cases, all passing) with stub
  classes mirroring the asyncdb wrapper / raw asyncpg contract:
  multi-row unwrap, raw-conn fallback, single_row, single_row→None→{},
  returning=False→execute, multi-row empty→[].
- Scope boundary: only `navigator/toolkit.py` modified; zero changes
  under `packages/ai-parrot/`.

**Deviations from spec**: none.

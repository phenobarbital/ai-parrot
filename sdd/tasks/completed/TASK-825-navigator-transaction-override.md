# TASK-825: NavigatorToolkit `transaction()` override — run on raw asyncpg

**Feature**: FEAT-117 — Navigator Toolkit asyncdb Connection Unwrap
**Spec**: `sdd/specs/navigator-toolkit-asyncdb-conn-unwrap.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-822, TASK-824
**Assigned-to**: Claude Code (hotfix, retroactive)

---

## Context

After TASK-824 landed, `nav_create_dashboard` failed with::

    'coroutine' object does not support the asynchronous context manager protocol

because `PostgresToolkit.transaction()` (`postgres.py:795-830`) does::

    async with self._acquire_asyncdb_connection() as conn:
        async with conn.transaction():   # ← fails
            yield conn

`conn` here is the asyncdb `pg` driver wrapper, whose `transaction()`
is an `async def` coroutine (returns `self`), NOT an async context
manager. Entering the `async with` is illegal and raises `TypeError`.

Same root cause family as TASK-822 / TASK-824 — asyncdb wrapper vs
raw asyncpg mismatch. Originally flagged in the v0.3 spec as "Known
Risk — may be latent"; turned out to be exercised by the first
write tool that batched multiple statements.

Implements **Module 4** of the revised (v0.4) spec.

---

## Scope

- Override `transaction()` on `NavigatorToolkit`.
- Same `_in_transaction` guard as the parent (no nested
  transactions; inherit the instance attribute from
  `PostgresToolkit.__init__`).
- Acquire an asyncdb connection, unwrap to raw `asyncpg.Connection`
  via `engine()`, enter `raw.transaction()` (asyncpg's native async
  context manager; also supports nested savepoint transactions if
  called recursively).
- **Yield the raw asyncpg connection** (not the wrapper). Downstream
  CRUD calls route through `_run_on_conn` (TASK-822 override) which
  see `conn=raw_asyncpg` and fall through the `hasattr(conn,
  "engine")` guard — correct semantics.

**NOT in scope**:
- Any change under `packages/ai-parrot/` (framework).
- Unit tests — those land in TASK-826.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` | MODIFY | Add `transaction()` override (with `@asynccontextmanager`) on `NavigatorToolkit`; extend imports with `asynccontextmanager` and `AsyncIterator`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (added by this task)

```python
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional  # extended
```

### Existing Signatures Used

```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py
class PostgresToolkit(SQLToolkit):
    def __init__(self, ...):
        ...
        self._in_transaction: bool = False           # line 57 — inherited

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]: ...  # line 795 — OVERRIDDEN

# asyncpg:
asyncpg.Connection.transaction()   # native sync context manager, supports savepoints
```

### Does NOT Exist

- ~~`_acquire_asyncdb_connection` yielding raw asyncpg directly~~
  — that's future framework-level work (FEAT-118); today it yields
  the wrapper.
- ~~Nested `self.transaction()` calls~~ — explicitly rejected with
  `RuntimeError`. Matches parent behaviour.
- ~~`_end_transaction` / `_commit` methods~~ — asyncpg's context
  manager handles commit/rollback automatically on exit.

---

## Implementation Notes

```python
@asynccontextmanager
async def transaction(self) -> AsyncIterator[Any]:
    if self._in_transaction:
        raise RuntimeError("Nested transactions are not supported. ...")
    self._in_transaction = True
    try:
        async with self._acquire_asyncdb_connection() as conn:
            raw = conn.engine() if hasattr(conn, "engine") and callable(conn.engine) else conn
            async with raw.transaction():
                yield raw
    finally:
        self._in_transaction = False
```

Note: yielding `raw` (not `conn`) means downstream CRUD calls route
through `_run_on_conn` with `conn=raw_asyncpg`; the `hasattr(conn,
"engine")` guard in that override falls through to the raw path
verbatim — no double-unwrap, no re-wrap.

---

## Acceptance Criteria

- [x] `NavigatorToolkit.transaction` is an `@asynccontextmanager`.
- [x] Inside, `async with raw.transaction():` uses asyncpg native.
- [x] Yields the raw asyncpg connection (verified via integration with
      `nav_create_dashboard`).
- [x] Nested calls raise `RuntimeError` (inherits parent semantics).
- [x] `_in_transaction` flag is toggled safely in `try/finally`.
- [x] No file under `packages/ai-parrot/` modified.
- [x] `compileall` clean.
- [x] Existing regression tests pass (20/20).

---

## Completion Note

**Completed by**: Claude Code (Opus 4.7), hotfix mode
**Date**: 2026-04-21
**Commits**:
- Worktree: `4a55dd1f`
- Merge to dev: `b8cd48b7` (via `git merge --no-ff`)

**Notes**:
- Retroactive SDD task — code was implemented and merged during
  a live-debug cycle to unblock production write tools.
- 52 LOC added (including docstring).
- Validated live: `nav_create_dashboard` now executes the plan-then-
  confirm cycle and the atomic INSERT without the `'coroutine' object
  does not support the asynchronous context manager protocol` error.

**Deviations from spec**: none.

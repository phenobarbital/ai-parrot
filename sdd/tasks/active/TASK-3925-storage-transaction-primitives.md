# TASK-3925: Storage transaction primitives: studio_transaction and _exec

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W0 — Repositories (M3, part 1: studio_transaction + _exec — pulled forward because M1 apply uses it)
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3922
**Assigned-to**: unassigned

---

## Context

Spec §2.5 (`studio_transaction`, `_exec`), §2.5a (the verified asyncdb 2.16.2 `pg` API), v0.2.2 note
("asyncdb-vs-raw-asyncpg transaction note + executable fixture test"). The §7 wave table lists these under W1
"Repositories", but M1's `apply_studio_migrations` (W0) runs each file through `studio_transaction`, so the two
primitives are split out and land first.

---

## Scope

- Create `storage/repositories.py` with `NAVIGATOR_SCHEMA = "navigator"`, `studio_transaction(pool)` and
  `_exec(conn, sql, *args)`, plus `_fetch_all` (normalises asyncdb's `None` to `[]`).
- `studio_transaction`: `async with pool.acquire() as conn` → `await conn.transaction()` → yield conn →
  `await conn.commit()`; on ANY exception incl. `CancelledError`: `await conn.rollback()` and re-raise.
- `_exec`: call `conn.execute`; when the returned `[result, error]` has an error, raise `StudioStorageError`.
- Tests: `test_exec_raises_on_error_tuple` (driver double with the real asyncdb shape) and the executable fixture
  test of `studio_transaction` commit/rollback against a real Postgres (`TEST_STUDIO_PG_DSN`).

**NOT in scope**: Repository classes (TASK-3928/08/09); COPY helpers (never used inside a Studio transaction).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/repositories.py` | CREATE | studio_transaction, _exec, _fetch_all, schema constant |
| `packages/ai-parrot-server/tests/studio/storage/test_transaction.py` | CREATE | error-tuple unit test + real-PG commit/rollback fixture test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.handlers.studio.storage.models import StudioStorageError   # TASK-3922
from asyncdb import AsyncPool                                           # pool used by the spec §4 fixture
```

### Existing Signatures to Use (asyncdb 2.16.2 `asyncdb/drivers/pg.py`, verified by the spec §6)
```python
class pgPool:  def acquire(self) -> _pgAcquireContext        # :443  (async with / await / async with await)
class pg:
    async def execute(self, sentence, *args, **kwargs)       # :937  returns [result, error]; raises only
                                                             #       Unique/FK/NotNull/Statement/QueryCanceled
    async def fetch_all(self, sentence, *args)               # :1013 None for zero rows
    async def fetch_one(self, sentence, *args)               # :1036
    async def transaction(self)                              # :1069 starts it; RETURNS THE DRIVER, not a ctx manager
    async def commit(self) / rollback(self)                  # :1076 / :1083
```
The repo has no checked-in venv: re-verify these lines in the worktree's installed asyncdb before coding.

### Does NOT Exist
- ~~`async with conn.transaction():` on the asyncdb `pg` driver~~ — that is raw asyncpg
  (`task_memory/store/postgres.py`); do NOT copy it.
- ~~isolation / read-only arguments on `pg.transaction()`~~.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/repositories.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_transaction.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: imports StudioStorageError from TASK-3922 (storage/models.py); creates storage/repositories.py, which TASK-3926 (apply) imports and TASK-3928/08/09 extend
- Cross-feature ordering: none — STORAGE W1 is in X16's early subset; FEAT-605 W2.1 waits for STORAGE W0+W1.
- Mutation to verify: make `_exec` ignore the error slot ⇒ `test_exec_raises_on_error_tuple` RED; make
  `studio_transaction` commit in `finally` ⇒ the rollback fixture test RED.

### Common constraints (all FEAT-621 tasks)
- Contract verified against `dev` @ `32b1a45d4` (2026-09-30). Earlier FEAT-621 tasks shift line numbers:
  re-run every `grep -c` before editing and fix this file first if an anchor moved.
- Async throughout; the pool is the host's `app["database"]` (asyncdb `pg` pool); no sync driver, no second pool.
- Raw parametrised SQL (`$1…$n`), never value interpolation; schema literal `navigator`.
- Transactions only through `studio_transaction`; statements only through `_exec` (spec §2.5a).
- Pydantic for payloads, frozen dataclasses for records; `self.logger` in views,
  `logging.getLogger("Parrot.AgentStudio.Storage")` in storage/services/runtime.
- ARCHITECTURE Rule 4: functions ≤ 60 lines, cyclomatic complexity ≤ 10, modules ≤ 500 lines.
- **Database rule** (spec §4): integration tests read `TEST_STUDIO_PG_DSN` and `pytest.skip` with a reason when it is
  unset. Point it at a PostgreSQL ≥ 14 database dedicated to this worktree — the fixtures truncate `navigator.ai_*`.
- **Request/session rule** (spec §4, ARCHITECTURE R6): handler tests use `aiohttp_client` with the real session
  middleware or `make_mocked_request(..., app=app)` + `request["NAV_SESSION"] = SessionData(...)`; never a `Mock`
  with a hand-set `.session`. Each new assertion is mutation-checked (revert the guarded line ⇒ RED).
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src` as needed;
  never `uv sync` inside a worktree.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name or file path the blueprint fixes (they come from spec §2.4/§2.5/§3 skeletons).

### Steps (in order)
1. Write the module below — *why*: every later repository and the migration runner route through these two.
2. Write the unit test with a driver double whose `execute` returns `[None, "Postgres Error: …"]`.
3. Write the PG fixture test: insert into a temp table inside `studio_transaction`, raise, assert rolled back;
   repeat without raising, assert committed.

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/repositories.py` (CREATE)
```python
"""Agent Studio repositories (spec §2.5/§2.5a). Raw parametrised SQL over the host asyncdb pool."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from .models import StudioStorageError

logger = logging.getLogger("Parrot.AgentStudio.Storage")
NAVIGATOR_SCHEMA = "navigator"


@asynccontextmanager
async def studio_transaction(pool: Any) -> AsyncIterator[Any]:
    """The ONLY way repositories open a transaction (asyncdb pg: transaction()/commit()/rollback())."""
    async with pool.acquire() as conn:
        await conn.transaction()
        try:
            yield conn
        except BaseException:
            await conn.rollback()
            raise
        await conn.commit()


async def _exec(conn: Any, sql: str, *args: Any) -> Any:
    """conn.execute wrapper: raise StudioStorageError when asyncdb returns an error tuple."""
    result = await conn.execute(sql, *args)
    # FILL IN: unpack [result, error] (tolerate a non-sequence result); error ⇒ raise StudioStorageError(str(error))
    #   — bounded by test_exec_raises_on_error_tuple.
    return result


async def _fetch_all(conn: Any, sql: str, *args: Any) -> list[Any]:
    rows = await conn.fetch_all(sql, *args)
    return list(rows or [])
```
**Why this shape**: `BaseException` catches `CancelledError` (spec §2.5a: rollback then re-raise on ANY exception).

### `packages/ai-parrot-server/tests/studio/storage/test_transaction.py` (CREATE)
```python
"""FEAT-621 §2.5a — transaction primitives."""
import os

import pytest

from parrot.handlers.studio.storage.models import StudioStorageError
from parrot.handlers.studio.storage.repositories import _exec, studio_transaction


class _DriverDouble:
    """Stands in for the asyncdb pg driver (a third-party DB we cannot run here), not request/session plumbing."""
    def __init__(self):
        self.calls: list[str] = []
    async def transaction(self):
        self.calls.append("transaction"); return self
    async def commit(self):
        self.calls.append("commit")
    async def rollback(self):
        self.calls.append("rollback")
    async def execute(self, sql, *args):
        return [None, "Postgres Error: check constraint violated"]
# FILL IN: _PoolDouble.acquire() async context manager yielding the driver.


async def test_exec_raises_on_error_tuple() -> None:
    # FILL IN: inside studio_transaction(_PoolDouble()) call _exec ⇒ StudioStorageError; calls == [transaction, rollback]
    ...


async def test_studio_transaction_real_postgres() -> None:
    dsn = os.environ.get("TEST_STUDIO_PG_DSN")
    if not dsn:
        pytest.skip("TEST_STUDIO_PG_DSN not set; needs a real Postgres")
    # FILL IN: AsyncPool("pg", dsn=dsn); temp table; rollback path and commit path.
```

### FILL IN checklist
- [ ] `_exec` error-slot handling.
- [ ] pool double; both test bodies.

---

## Acceptance Criteria

- [ ] `_exec` raises `StudioStorageError` on an error tuple and `studio_transaction` then calls `rollback`, never `commit` (`test_exec_raises_on_error_tuple`, AC8 groundwork).
- [ ] Commit and rollback verified against a real Postgres (executable fixture test; skipped with reason when `TEST_STUDIO_PG_DSN` is unset).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_transaction.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_exec_raises_on_error_tuple` | §2.5a (mutation: ignore error slot ⇒ RED) |
| `test_studio_transaction_real_postgres` | §2.5a executable fixture test (v0.2.2) |

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-db-storage --feature-id FEAT-621`).
2. Read the spec sections cited in Context; check every `Depends-on` task is `"done"` in
   `sdd/tasks/index/agentstudio-db-storage.json`.
3. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
4. Set this task `"in-progress"` in the index (with `started_at`) and commit only the index.
5. Implement exactly the files listed, starting from the Blueprint; no refactors outside scope.
6. `ruff check --fix` the touched Python files; run the Validation Commands.
7. Commit code only (never `git add .`/`-A`):
   `feat(agentstudio-db-storage): TASK-3925 — Storage transaction primitives: studio_transaction and _exec`.
8. Close with `scripts/sdd/close_task.sh TASK-3925 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, deviations, issues.

**Deviations from spec**: none | describe if any

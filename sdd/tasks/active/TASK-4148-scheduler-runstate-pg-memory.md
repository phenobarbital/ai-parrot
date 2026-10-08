# TASK-4148: RunStateStore protocol with PostgresRunState and MemoryRunState

**Feature**: FEAT-644 — SchedulerManager base (db | redis | code backends)
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4147
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. Run state moves out of `metadata` into a per-backend store with ONE contract, so `get_last_result`,
`list_jobs` and auto-disable behave identically for db/redis/code jobs (spec AC9, AC11). The failure transition must
be atomic across workers (design research S4): today `_update_schedule_run` is read-modify-write
(`packages/ai-parrot-server/src/parrot/scheduler/manager.py:977-1036`).

This task creates the protocol, the Postgres store (one `UPDATE … RETURNING` statement per transition) and the
in-memory store used for `code` jobs. TASK-4149 adds the Redis store in the same file.

---

## Scope

- Create `runstate.py` with the `RunStateStore` Protocol (spec §2 New Public Interfaces, exact signatures).
- Implement `MemoryRunState` (dict-backed; same semantics as the others).
- Implement `PostgresRunState(acquire)` with single-statement atomic transitions against `navigator.service_scheduler`.
- Implement the shared semantics: success resets `consecutive_failures` and clears `last_error`/`last_error_at`; `status='lock_unavailable'` stamps but never touches the counter; `stamp_failure` returns `(RunState, crossed_threshold)` with `crossed_threshold` true for exactly one caller; `set_enabled(True)` resets the counter.
- Truncate `last_result` and every outcome `error` to 10_000 chars + `'…(truncated)'` (same cap as `manager.py` `_LAST_RESULT_MAX_CHARS`).
- Write `tests/scheduler/test_runstate.py` for Memory + Postgres (fake connection).

**NOT in scope**: `RedisRunState` (TASK-4149); deciding WHEN to stamp or alert (TASK-4157); disabling the APScheduler job (TASK-4157).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/runstate.py` | CREATE | RunStateStore protocol, PostgresRunState, MemoryRunState |
| `packages/ai-parrot-server/tests/scheduler/test_runstate.py` | CREATE | Tests for Memory + Postgres stores |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase (verified on `dev` @ `3555841e9`, 2026-10-08).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.scheduler.models import RunState, FireContext, utcnow   # created by TASK-4147 (models.py)
from typing import Any, Awaitable, Callable, Optional, Protocol, runtime_checkable
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:977 — the read-modify-write this replaces (do not import; behaviour reference only)
async def _update_schedule_run(self, schedule_id, success=True, error=None, result=None):
    async with await self._pool.acquire() as conn:   # line 999 — the connection idiom PostgresRunState reuses
        ...

# packages/ai-parrot-server/src/parrot/scheduler/manager.py:750 — delivery status reducer to replicate inside stamp_delivery
@staticmethod
def _aggregate_delivery_status(outcomes: List[Dict[str, Any]]) -> Optional[str]:
    # {sent,saved} ⊇ statuses → "ok"; statuses == {"failed"} → "failed"; else "partial"; [] → None

# asyncdb pg connection (venv asyncdb/drivers/pg.py:1036) — parameterized single-row fetch:
async def fetch_one(self, sentence: str, *args, **kwargs)   # returns an asyncpg Record or None; raises on SQL error
```
`PostgresRunState.__init__(acquire)` receives the bound `pool.acquire` so it can do
`async with await self._acquire() as conn:` exactly like manager.py:999.

### Does NOT Exist
- ~~`parrot.scheduler.runstate`~~ — created here.
- ~~`RedisRunState`~~ — TASK-4149.
- ~~asyncdb `conn.fetchrow(sql, *args)` on the driver~~ — the driver method is `fetch_one`; `fetchrow()` takes no SQL.
- ~~a `run_state` column or table~~ — run state is columns on `navigator.service_scheduler` (spec §2).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/scheduler/runstate.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/scheduler/test_runstate.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._update_schedule_run",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._stamp_delivery_outcome",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._aggregate_delivery_status"
  ]
}
```

---

## Implementation Notes

### Atomic Postgres transitions (spec §3 M2)
Failure (`error` / `target_missing` / `incompatible`), one statement:
```sql
UPDATE navigator.service_scheduler
   SET last_run = $1, run_count = run_count + 1, last_status = $2, last_error = $3, last_error_at = $1,
       consecutive_failures = consecutive_failures + 1,
       enabled = (consecutive_failures + 1 < $4) AND enabled
 WHERE schedule_id = $5
RETURNING *
```
`crossed_threshold = row["consecutive_failures"] == threshold` — Postgres row-locks the UPDATE, so exactly one
worker sees the crossing value. `lock_unavailable` uses a different statement that sets only `last_status`,
`last_error`, `last_error_at` (no `run_count`, no counter — the job did not run).

Success: `last_run=$1, run_count=run_count+1, last_status='success', last_result=$2, last_result_at=$1,
last_error=NULL, last_error_at=NULL, consecutive_failures=0, next_run=$3`.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/scheduler/manager.py:950-976` — delivery-outcome truncation to copy.

### Key Constraints
- Async-first; never block the event loop. `self.logger` / module `logger`, never `print`.
- Google-style docstrings and strict type hints; 120-column lines; `ruff check` (TID251) must pass on every touched file.
- Every timestamp the scheduler writes goes through `utcnow()` (UTC-aware) — never `datetime.now()` (spec AC7).
- Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim, then complete every
> `# FILL IN:` marker. Never change a signature, class name, or file path the blueprint fixes (they come from the
> spec's §3 Interface Skeletons). Anchors were re-verified with `grep -c` at task-generation time.

### Steps (in order)
1. Write the `RunStateStore` Protocol with the exact spec signatures — *why*: TASK-4155/4157 type against it and TASK-4149 implements it.
2. Implement `MemoryRunState` first — *why*: it is the executable spec of the semantics; the Postgres and Redis stores must pass the same tests.
3. Implement `PostgresRunState` with the SQL in Implementation Notes — *why*: one statement per transition is what makes the threshold crossing race-free (S4).
4. Map a returned row to `RunState` in one helper `_row_to_state(row)` — *why*: `read()`, `stamp_success` and `stamp_failure` all return the same shape.
5. Write the tests (fake connection records SQL + returns canned rows) and run them.

### `packages/ai-parrot-server/src/parrot/scheduler/runstate.py` (CREATE)
```python
"""Run-state persistence for scheduled jobs (FEAT-644 spec §3 Module 2)."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional, Protocol, runtime_checkable

from .models import FireContext, RunState, utcnow

logger = logging.getLogger("Parrot.Scheduler.runstate")

LAST_RESULT_MAX_CHARS: int = 10_000
STATUS_LOCK_UNAVAILABLE = "lock_unavailable"


def truncate(text: Optional[str]) -> Optional[str]:
    """Cap a stored string at ``LAST_RESULT_MAX_CHARS`` with a ``'…(truncated)'`` suffix."""
    if text is None or len(text) <= LAST_RESULT_MAX_CHARS:
        return text
    return text[:LAST_RESULT_MAX_CHARS] + "…(truncated)"


def aggregate_delivery_status(outcomes: list[dict[str, Any]]) -> Optional[str]:
    """Reduce outcomes to ``ok`` / ``partial`` / ``failed`` (mirror of manager.py:750)."""
    # FILL IN: exact copy of AgentSchedulerManager._aggregate_delivery_status semantics.


@runtime_checkable
class RunStateStore(Protocol):
    """Backend contract for per-job run state (spec §2)."""

    async def stamp_success(self, job_id: str, *, result_text: str | None, fire: FireContext,
                            next_run: Any | None) -> RunState: ...
    async def stamp_failure(self, job_id: str, *, status: str, error: str, fire: FireContext,
                            threshold: int) -> tuple[RunState, bool]: ...
    async def stamp_delivery(self, job_id: str, outcomes: list[dict[str, Any]]) -> None: ...
    async def read(self, job_id: str) -> RunState | None: ...
    async def set_enabled(self, job_id: str, enabled: bool) -> None: ...
    async def clear(self, job_id: str) -> None: ...


class MemoryRunState:
    """Process-local store for ``code`` jobs."""

    def __init__(self, backend: str = "code") -> None:
        self._backend = backend
        self._states: dict[str, RunState] = {}

    # FILL IN: the 6 protocol methods; stamp_failure crossed = (new counter == threshold);
    #          lock_unavailable never touches run_count/counter; success clears last_error/last_error_at.
```
**Why**: the module-level `truncate` / `aggregate_delivery_status` are reused by TASK-4149 and TASK-4157 so the three
stores and the manager cannot drift.

```python
# (continued, same file)
class PostgresRunState:
    """Run state as columns of ``navigator.service_scheduler`` (single-statement transitions)."""

    _FAILURE_SQL = """
        # FILL IN: the failure UPDATE … RETURNING * from Implementation Notes
    """
    _LOCK_SQL = """
        # FILL IN: UPDATE setting only last_status/last_error/last_error_at … RETURNING *
    """
    _SUCCESS_SQL = """
        # FILL IN: the success UPDATE … RETURNING * from Implementation Notes
    """

    def __init__(self, acquire: Callable[[], Awaitable[Any]]) -> None:
        """``acquire`` is the bound ``pool.acquire`` (used as ``async with await acquire() as conn``)."""
        self._acquire = acquire

    async def _one(self, sql: str, *args: Any) -> Any:
        async with await self._acquire() as conn:  # pylint: disable=no-member
            return await conn.fetch_one(sql, *args)

    def _row_to_state(self, row: Any) -> RunState:
        """Map a ``service_scheduler`` row to ``RunState(backend='db')``."""
        # FILL IN: str(row["schedule_id"]); last_callbacks default [].

    async def stamp_failure(self, job_id: str, *, status: str, error: str, fire: FireContext,
                            threshold: int) -> tuple[RunState, bool]:
        """Atomic failure transition; ``crossed`` is true only for the update that reaches ``threshold``."""
        # FILL IN: lock_unavailable → _LOCK_SQL, crossed=False; else _FAILURE_SQL with utcnow(), truncate(error).

    # FILL IN: stamp_success, stamp_delivery (UPDATE last_callbacks/last_delivery_status/last_delivery_at),
    #          read (SELECT … WHERE schedule_id=$1), set_enabled (enabled=$1, and counter=0 when enabled),
    #          clear (no-op for db: the row is deleted by the manager).
```
**Why**: `job_id` is the row's UUID as a string; pass `uuid.UUID(job_id)` as the parameter. Never raise from
`stamp_*` for a missing row — log a warning and return `(None-safe)` default state; the caller decides.

### FILL IN checklist
- [ ] `aggregate_delivery_status` — identical semantics to manager.py:750.
- [ ] `MemoryRunState` — 6 methods; counter + crossed semantics; lock_unavailable leaves counter.
- [ ] `PostgresRunState._FAILURE_SQL` / `_LOCK_SQL` / `_SUCCESS_SQL` — Implementation Notes.
- [ ] `PostgresRunState._row_to_state` and remaining methods; missing row → warning, never raise.

---

## Acceptance Criteria

- [ ] `from parrot.scheduler.runstate import RunStateStore, PostgresRunState, MemoryRunState, truncate, aggregate_delivery_status` works.
- [ ] Memory: three failures with threshold 3 → `crossed_threshold` true exactly on the third call; success afterwards → counter 0, `last_error is None`.
- [ ] Memory + Postgres: `status='lock_unavailable'` leaves `consecutive_failures` and `run_count` unchanged.
- [ ] Postgres: each transition executes exactly one SQL statement (asserted on the fake connection).
- [ ] Every timestamp written is UTC-aware.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

- `pytest packages/ai-parrot-server/tests/scheduler/test_runstate.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/scheduler/test_runstate.py
import pytest
from parrot.scheduler.models import FireContext, utcnow
from parrot.scheduler.runstate import MemoryRunState, PostgresRunState

class FakeConn:            # records (sql, args); fetch_one returns the next canned row
    ...
class FakeAcquire:         # `async with await acquire() as conn` → FakeConn
    ...

@pytest.fixture
def fire():
    return FireContext.for_fire("job-1", utcnow())

async def test_memory_threshold_crossed_once(fire): ...
async def test_memory_success_resets_counter_and_clears_error(fire): ...
async def test_lock_unavailable_does_not_count_memory(fire): ...
async def test_pg_stamp_failure_single_statement_threshold(fire): ...   # crossed from RETURNING row
async def test_pg_stamp_success_resets_counter_and_clears_error(fire): ...
async def test_pg_lock_unavailable_uses_lock_sql(fire): ...
async def test_truncate_caps_long_results(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug scheduler-manager-base --feature-id FEAT-644 --spec sdd/specs/scheduler-manager-base.spec.md --index sdd/tasks/index/scheduler-manager-base.json`)
2. **Read the spec** at `sdd/specs/scheduler-manager-base.spec.md` (§2 Overview, the CRUD matrix, Data Models, and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/scheduler-manager-base.json`
4. **Verify the Codebase Contract** — re-`grep` every anchor and signature before writing code; if one moved, fix
   the contract in this file first; never reference anything listed under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:` marker
7. **Verify** — `ruff check` the touched files and run every Validation Command
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`):
   `feat(scheduler-manager-base): TASK-4148 — RunStateStore protocol with PostgresRunState and MemoryRunState`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4148 scheduler-manager-base verified` (never move the file by hand)
10. **Fill in the Completion Note** below, then commit the staged SDD state: `sdd: complete TASK-4148 — RunStateStore protocol with PostgresRunState and MemoryRunState`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

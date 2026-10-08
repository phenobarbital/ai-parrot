# TASK-4165: Backend-parity, Redis restart and ledger-regression integration tests; close ledger issues

**Feature**: FEAT-644 — SchedulerManager base (db | redis | code backends)
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4163, TASK-4164
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests, design research S12, AC8, AC11, AC14, AC17. End-to-end evidence that the three backends
behave the same, that a Redis-only job survives a restart and catches up once, that two managers on one Redis do not
see each other, and that the three ledger regressions stay fixed — then close the ledger issues.

Redis-backed tests use the `scheduler_redis` / `scheduler_redis_sync` fixtures from `packages/ai-parrot-server/tests/scheduler/conftest.py` (created by TASK-4149): a REAL Redis at `CACHE_HOST:CACHE_PORT`, logical db 15, a unique `registered_name` per test, keys deleted by that prefix on teardown, and `pytest.skip` when Redis is unreachable. `fakeredis` is NOT installed in the workspace venv and is not declared in any `pyproject.toml` (spec §4/§7 assumed it was — this is the recorded deviation); do not import it.

---

## Scope

- `test_base_parity.py`: `test_three_backends_same_list_payload`, `test_db_schedule_end_to_end` (fake pool), `test_runstate_parity_matrix` across stores via the manager.
- `test_redis_backend.py`: `test_redis_job_survives_restart` (manager A adds, `stop_headless`, manager B same `registered_name` starts with `use_redis=True` → listed, fires, run state readable), `test_redis_job_catchup_once_after_outage` (`misfire_grace_time=None` → exactly one run with `scheduled_at` = last due time; `misfire_grace_time=600` + 2 h gap → none), `test_jobstore_and_coordinator_keys_namespaced`, `test_multiworker_threshold_race` (two managers, three failing fires → one disable, one alert), `test_headless_startup_order`.
- `test_ledger_regressions.py`: one test per ledger issue (`aa813ccc1927`, `7b5d75d2c81d`, `37f02d3c2474`) through public/manager entry points.
- After all tests pass and the code is committed, close the three issues: `wikitoolkit ledger close <id> --reason "fixed by FEAT-644" --resolved-by task:TASK-4165`.

**NOT in scope**: code changes — if a test exposes a defect, record it (done-with-issues) and open a ledger issue instead of fixing it here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/scheduler/test_base_parity.py` | CREATE | Backend parity integration tests |
| `packages/ai-parrot-server/tests/scheduler/test_redis_backend.py` | CREATE | Redis restart, catch-up, namespacing, threshold race |
| `packages/ai-parrot-server/tests/scheduler/test_ledger_regressions.py` | CREATE | Ledger regression tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase (verified on `dev` @ `3555841e9`, 2026-10-08).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.scheduler import SchedulerManager, JobDefinition, ServiceSchedule        # lazy exports, TASK-4163
from parrot.scheduler.base import SchedulerUnavailableError, TargetMissingError       # TASK-4154
from parrot.scheduler.runstate import RedisRunState, MemoryRunState                   # TASK-4148/4149
from parrot.scheduler.coordination import CURRENT_RUN_TIME, manager_prefix            # TASK-4151
```
Ledger CLI (verified `wikitoolkit ledger close --help`): `wikitoolkit ledger close ISSUE_ID --reason TEXT [--actor TEXT] [--resolved-by commit:<sha>|task:TASK-<NNN>]`.

### Does NOT Exist
- ~~`fakeredis`~~ — use the conftest real-Redis fixtures.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/tests/scheduler/test_base_parity.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/scheduler/test_redis_backend.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/scheduler/test_ledger_regressions.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/base.py#SchedulerManager",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/coordination.py#RedisFireCoordinator"
  ]
}
```

---

## Implementation Notes

Catch-up test: drive time with an `interval` trigger of 1 s and `stop_headless` for ~3 s, or set `next_run_time` in the past on the persisted job before restart — prefer the latter (deterministic). Never `time.sleep`; use `asyncio.sleep` with small bounds.

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
1. Write the three files using the conftest fixtures.
2. Run them; on a real defect stop and report.
3. Commit, then close the three ledger issues with `--resolved-by task:TASK-4165`.

### `packages/ai-parrot-server/tests/scheduler/test_redis_backend.py` (CREATE)
```python
"""FEAT-644 Redis backend integration tests (real Redis, db 15)."""
import pytest

from parrot.scheduler import SchedulerManager


@pytest.fixture
def redis_db_15(monkeypatch):
    """Point SCHEDULER_REDIS_DB at 15 for the manager under test."""
    # FILL IN: monkeypatch navconfig.config.get to return "15" for SCHEDULER_REDIS_DB.


async def test_redis_job_survives_restart(scheduler_namespace, scheduler_redis, redis_db_15): ...   # FILL IN
async def test_redis_job_catchup_once_after_outage(scheduler_namespace, scheduler_redis, redis_db_15): ...   # FILL IN
async def test_jobstore_and_coordinator_keys_namespaced(scheduler_redis, redis_db_15): ...   # FILL IN
async def test_multiworker_threshold_race(scheduler_namespace, scheduler_redis, redis_db_15): ...   # FILL IN
async def test_headless_startup_order(scheduler_namespace, scheduler_redis, redis_db_15): ...   # FILL IN
```
### `packages/ai-parrot-server/tests/scheduler/test_base_parity.py`, `packages/ai-parrot-server/tests/scheduler/test_ledger_regressions.py` (CREATE)
```python
# FILL IN: the test names listed in Scope.
```

### FILL IN checklist
- [ ] Each integration test body.
- [ ] Ledger close commands after commit.

---

## Acceptance Criteria

- [ ] All three files pass with Redis reachable and skip cleanly without it.
- [ ] Ledger issues `aa813ccc1927`, `7b5d75d2c81d`, `37f02d3c2474` are closed with `--resolved-by task:TASK-4165` (AC17).

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

- `pytest packages/ai-parrot-server/tests/scheduler/test_base_parity.py -q`
- `pytest packages/ai-parrot-server/tests/scheduler/test_redis_backend.py -q`
- `pytest packages/ai-parrot-server/tests/scheduler/test_ledger_regressions.py -q`

---

## Test Specification

See Scope — every listed test name must exist.

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
   `feat(scheduler-manager-base): TASK-4165 — Backend-parity, Redis restart and ledger-regression integration tests; close ledger issues`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4165 scheduler-manager-base verified` (never move the file by hand)
10. **Fill in the Completion Note** below, then commit the staged SDD state: `sdd: complete TASK-4165 — Backend-parity, Redis restart and ledger-regression integration tests; close ledger issues`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

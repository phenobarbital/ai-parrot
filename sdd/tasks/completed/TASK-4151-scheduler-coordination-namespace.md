# TASK-4151: Namespaced coordination prefix, SCHEDULER_REDIS_DB, and redis coordinator forced by a Redis jobstore

**Feature**: FEAT-644 — SchedulerManager base (db | redis | code backends)
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (coordination half) and spec §2 Redis layout. Every Redis key must carry the manager's
`registered_name` (design research S3): today fire claims use the global `parrot:scheduler:fire:...`
(`packages/ai-parrot-server/src/parrot/scheduler/coordination.py:24,101`), so two managers sharing Redis collide. The logical db comes from the new
`SCHEDULER_REDIS_DB` (default 6). And a Redis jobstore must always imply the `redis` coordinator: an explicit
`none` (env or argument) is overridden with a WARNING (spec AC14) — otherwise N workers loading the same Redis jobs
would fire N times.

---

## Scope

- Add `manager_prefix(registered_name: str) -> str` returning `f"parrot:scheduler:{registered_name}:"`.
- Add `redis_db() -> int` reading `SCHEDULER_REDIS_DB` via `nav_config.get`, sanitized to 0..15, default `DEFAULT_REDIS_JOBSTORE_DB` (6).
- Change `build_fire_coordinator(mode=None, *, use_redis=False, prefix=DEFAULT_PREFIX)`: `use_redis=True` ⇒ always `RedisFireCoordinator` (WARNING if mode/env said `none`); pass `prefix` to it; use `redis_db()`.
- Add `CURRENT_RUN_TIME: ContextVar[Optional[datetime]]` and set it in `CoordinatedAsyncIOExecutor._claimed_run` to `run_times[-1]` right before `run_coroutine_job` (reset in `finally`) — the job coroutine runs in the same task, so `SchedulerManager` (TASK-4157) can build `fire_id` from the exact run time the claim used (ledger `aa813ccc1927`).
- Update `test_build_fire_coordinator_modes` (line 99 currently asserts the opposite) and add tests.

**NOT in scope**: jobstore key names (TASK-4155 builds the RedisJobStore with `manager_prefix`); removing `DEFAULT_PREFIX` (kept as the no-name default for backward-compatible construction).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/coordination.py` | MODIFY | manager_prefix, redis_db, build_fire_coordinator(prefix=) + forced redis |
| `packages/ai-parrot-server/tests/scheduler/test_coordination.py` | MODIFY | Update modes test, add prefix/db/forced tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase (verified on `dev` @ `3555841e9`, 2026-10-08).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# packages/ai-parrot-server/src/parrot/scheduler/coordination.py:13-20 (existing)
import redis.asyncio as aioredis
from parrot.conf import CACHE_HOST, CACHE_PORT
from .sanitize import DEFAULT_REDIS_JOBSTORE_DB, SchedulerConfigError, sanitize_redis_settings
from navconfig import config as nav_config      # imported lazily inside build_fire_coordinator (line 149)
```

### Existing Signatures to Use
```python
DEFAULT_PREFIX = "parrot:scheduler:"                                           # line 24
class RedisFireCoordinator:
    def __init__(self, client, *, worker_id=None, fire_ttl=DEFAULT_FIRE_TTL,
                 run_now_ttl=DEFAULT_RUN_NOW_TTL, prefix=DEFAULT_PREFIX)        # line 84
    async def claim(self, job_id, run_time) -> bool   # key f"{prefix}fire:{job_id}:{run_time.isoformat()}" line 101
def build_fire_coordinator(mode: Optional[str] = None, *, use_redis: bool = False) -> FireCoordinator:  # line 139
    raw = mode or nav_config.get("SCHEDULER_COORDINATION") or ("redis" if use_redis else "none")   # line 151
# packages/ai-parrot-server/tests/scheduler/test_coordination.py:86-104 — test_build_fire_coordinator_modes
#   line 99: assert isinstance(coord.build_fire_coordinator("none", use_redis=True), coord.NullFireCoordinator)  ← must flip
```

### Does NOT Exist
- ~~`manager_prefix`~~, ~~`redis_db`~~, ~~`SCHEDULER_REDIS_DB` reads~~ — created here.
- ~~a `registered_name` parameter on `RedisFireCoordinator`~~ — pass the already-built `prefix`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/scheduler/coordination.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/scheduler/test_coordination.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/coordination.py#build_fire_coordinator",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/coordination.py#RedisFireCoordinator",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/coordination.py#NullFireCoordinator"
  ]
}
```

---

## Implementation Notes

`redis_db()`: `raw = nav_config.get("SCHEDULER_REDIS_DB")`; reuse `sanitize_redis_settings(host=CACHE_HOST, port=CACHE_PORT, db=raw)["db"]`
so the 0..15 range check and the WARNING-and-fallback policy are shared (it already range-checks `db`). Import
`nav_config` lazily like line 149 so tests can monkeypatch `navconfig.config.get`.

Forced coordinator: compute `normalized` as today; if `use_redis` and `normalized == "none"`: `logger.warning(
"SCHEDULER_COORDINATION=none ignored: a Redis jobstore is attached, fires must be claimed (FEAT-644)")` and treat as
`"redis"`. Unknown values still raise `SchedulerConfigError`.

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
1. Add `manager_prefix` and `redis_db` near the constants — *why*: TASK-4155 and TASK-4157 build every Redis key from them.
2. Change `build_fire_coordinator` signature and body — *why*: AC14 (forced coordination, namespaced claims).
3. Flip line 99 of the modes test and add new tests; run the file.

### `packages/ai-parrot-server/src/parrot/scheduler/coordination.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^DEFAULT_PREFIX = "parrot:scheduler:"' packages/ai-parrot-server/src/parrot/scheduler/coordination.py)
# AFTER `DEFAULT_RUN_NOW_TTL = 3600` (verified: coordination.py:26) — insert:


def manager_prefix(registered_name: str) -> str:
    """Return the Redis key prefix owned by one scheduler manager (``parrot:scheduler:<name>:``)."""
    return f"{DEFAULT_PREFIX}{registered_name}:"


def redis_db() -> int:
    """Logical Redis db for jobstore, run state and coordination (``SCHEDULER_REDIS_DB``, default 6)."""
    from navconfig import config as nav_config

    # FILL IN: sanitize via sanitize_redis_settings(host=CACHE_HOST, port=CACHE_PORT, db=raw)["db"].
```
```python
# occurrences: 1 (verified: grep -c '^def build_fire_coordinator(' packages/ai-parrot-server/src/parrot/scheduler/coordination.py)
# REPLACE the signature line (coordination.py:139) and body:
def build_fire_coordinator(
    mode: Optional[str] = None, *, use_redis: bool = False, prefix: str = DEFAULT_PREFIX
) -> FireCoordinator:
    """Resolve and build the fire coordinator.

    A Redis jobstore (``use_redis=True``) always yields ``RedisFireCoordinator``: ``none`` from the argument or
    ``SCHEDULER_COORDINATION`` is overridden with a WARNING (FEAT-644 AC14). ``prefix`` namespaces the claim keys.

    Raises:
        SchedulerConfigError: If the resolved mode is unknown.
    """
    # FILL IN: as today, plus the forced-redis rule; RedisFireCoordinator(client, ..., prefix=prefix);
    #          client db = redis_db() instead of DEFAULT_REDIS_JOBSTORE_DB.
```
```python
# occurrences: 1 (verified: grep -c '        return await run_coroutine_job(job, job._jobstore_alias, run_times, self._logger.name)' packages/ai-parrot-server/src/parrot/scheduler/coordination.py)
# module level, after the imports — add:
from contextvars import ContextVar

CURRENT_RUN_TIME: ContextVar[Optional[datetime]] = ContextVar("scheduler_current_run_time", default=None)
# Scheduled run time of the fire being executed; set by CoordinatedAsyncIOExecutor (FEAT-644, aa813ccc1927).

# REPLACE the last line of _claimed_run (coordination.py:198):
        token = CURRENT_RUN_TIME.set(run_times[-1])
        try:
            return await run_coroutine_job(job, job._jobstore_alias, run_times, self._logger.name)
        finally:
            CURRENT_RUN_TIME.reset(token)
```
**Why**: keeping `DEFAULT_PREFIX` as the default parameter means the legacy manager (still calling
`build_fire_coordinator(coordination, use_redis=use_redis)` until TASK-4158) keeps working unchanged.

### FILL IN checklist
- [ ] `CURRENT_RUN_TIME` set/reset around `run_coroutine_job` in `_claimed_run`.
- [ ] `redis_db` — shared range check through `sanitize_redis_settings`.
- [ ] `build_fire_coordinator` — forced redis + WARNING, prefix passthrough, `redis_db()`.

---

## Acceptance Criteria

- [ ] `build_fire_coordinator('none', use_redis=True)` returns a `RedisFireCoordinator` and logs a WARNING.
- [ ] `build_fire_coordinator(use_redis=True, prefix=manager_prefix('x'))` claims keys starting `parrot:scheduler:x:fire:`.
- [ ] `SCHEDULER_REDIS_DB=3` → `redis_db() == 3`; `SCHEDULER_REDIS_DB=99` → WARNING + 6.
- [ ] Inside a job coroutine dispatched by `CoordinatedAsyncIOExecutor`, `CURRENT_RUN_TIME.get()` equals the run time passed to `claim()`; outside it is `None`.
- [ ] Without `use_redis`, `none`/`redis`/unknown behave as before.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

- `pytest packages/ai-parrot-server/tests/scheduler/test_coordination.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/scheduler/test_coordination.py
def test_build_fire_coordinator_modes(monkeypatch): ...      # line 99 now expects RedisFireCoordinator
def test_forced_redis_logs_warning(monkeypatch, caplog): ...
def test_manager_prefix_namespaces_claim_keys(): ...           # inspect coordinator._prefix
def test_redis_db_env_and_fallback(monkeypatch): ...
async def test_current_run_time_matches_claim(): ...           # executor with a recording coordinator
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
   `feat(scheduler-manager-base): TASK-4151 — Namespaced coordination prefix, SCHEDULER_REDIS_DB, and redis coordinator forced by a Redis jobstore`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4151 scheduler-manager-base verified` (never move the file by hand)
10. **Fill in the Completion Note** below, then commit the staged SDD state: `sdd: complete TASK-4151 — Namespaced coordination prefix, SCHEDULER_REDIS_DB, and redis coordinator forced by a Redis jobstore`

---

## Completion Note

**Completed by**: sdd-worker (coder seat: sonnet-native)
**Date**: 2026-10-08
**Notes**: Implemented as specified and merged into the feature branch. Direct run of packages/ai-parrot-server/tests/scheduler passed. The merge-tier validation was red only because of an unrelated pre-existing studio test collection error (ledger issue:d5a7c625fbe7); closed on direct test evidence.

**Deviations from spec**: none

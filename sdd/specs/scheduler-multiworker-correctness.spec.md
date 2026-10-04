---
type: feature
base_branch: dev
projects: [ai-parrot-server, ai-parrot-integrations]
tags: [scheduler, apscheduler, multi-worker, redis-lock, listeners, gunicorn]
---

# Feature Specification: Scheduler multi-worker correctness

**Feature ID**: FEAT-631
**Date**: 2026-10-05
**Author**: Jesus Lara (spec drafted by Claude)
**Status**: approved
**Target version**: ai-parrot-server 0.28.0
**Source**: GitHub issue [phenobarbital/ai-parrot#1573](https://github.com/phenobarbital/ai-parrot/issues/1573) · proposal `sdd/proposals/gh-1573-scheduler-multiworker-correctness.proposal.md` (research audit `sdd/state/GH-1573/`)

---

## 1. Motivation & Business Requirements

### Problem Statement

`AgentSchedulerManager` (`packages/ai-parrot-server/src/parrot/scheduler/manager.py`) is not correct once
ai-parrot-server runs under gunicorn with more than one aiohttp worker. An external integrator reported three
defects, and all three were confirmed in code:

1. **Listeners are off on the aiohttp path.** `on_startup` calls `start_headless(use_redis=True, register_listeners=False)`.
   The success half of every DB schedule therefore never runs: no `last_run`/`run_count`/`last_result`/`next_run`
   stamping, no `send_result` email and no `CALLBACK_REGISTRY` callbacks. The failure half *does* stamp the row,
   so the DB records errors but never successes. `_job_context` entries also leak, because only the listener pops them.
2. **Duplicate firing.** Each worker builds its own `AsyncIOScheduler`, loads every enabled row and fires it, so N
   workers deliver N times. `delete_schedule`/`pause_schedule`/`update_schedule` change only the local scheduler of
   the worker that served the HTTP request, and `_execute_agent_job` never re-reads the row. The run-now 409 guard
   (`_run_now_active`) is also per process.
3. **The Redis jobstore cannot serialize jobs.** Every `add_job` passes a bound method of the manager.
   APScheduler 3.11.2 serializes an instance method by pickling `func.__self__`, which raises
   `TypeError: Schedulers cannot be serialized` (reproduced 2026-10-05). `add_schedule` also puts an arbitrary
   `success_callback` callable into job kwargs.

### Goals
- **G1**: The aiohttp path wires the listeners by default, so success stamping, `send_result` and callbacks run
  exactly as they do on the headless/agentd path.
- **G2**: When N workers share one Redis, each scheduled fire (DB-backed *and* decorator `auto_*` jobs) executes in
  exactly one worker, and its listeners, emails and DB stamps happen exactly once.
- **G3**: Each fire re-reads its schedule row. A missing or disabled row skips the fire and drops the local job;
  a changed trigger config reschedules the local job and skips this fire. Delete, pause and update made in any
  worker therefore take effect in every worker by its next fire.
- **G4**: Every job function is a picklable module-level coroutine, and every job's kwargs are plain
  `str` values. `scheduler_type="redis"` schedules can be added, loaded and run.
- **G5**: If Redis is unreachable at fire time the fire is **skipped (fail closed)**, logged at error level, and
  DB-backed rows get `metadata.last_status = "lock_unavailable"`.
- **G6**: Single-process deployments can opt out of coordination with `SCHEDULER_COORDINATION=none`.

### Non-Goals (explicitly out of scope)
- Migrating to APScheduler 4.x (its data-store layer has native multi-node coordination). That deserves its own brainstorm.
- Leader election. It was rejected in the proposal Q&A in favour of a per-fire lock (see the proposal §5).
- A Postgres claim column on `navigator.agents_scheduler` (rejected: no DDL change, and it would leave `auto_*` jobs uncovered).
- A pub/sub invalidation channel or a periodic reconcile loop. The fire-time re-check (G3) covers delete, pause and
  update; a schedule *added* in worker A fires only from A until the other workers restart, which is correct under the lock.
- Changing the `/api/v1/parrot/scheduler/restart` semantics (open question §8 Q2).

---

## 2. Architectural Design

### Overview

There are four cooperating changes. All of them are in `ai-parrot-server`; `ai-parrot-integrations` (agentd) needs no
code change and only has to keep working.

1. **Picklable trampolines** (`parrot/scheduler/jobs.py`, new). Module-level coroutines `run_db_schedule`,
   `run_db_schedule_now` and `run_auto_schedule` take `str`-only kwargs (`manager_name`, `schedule_id` or `job_id`, and
   `fingerprint`) and resolve the live manager from a process-local registry (`register_manager`/`get_manager`).
   APScheduler then stores a textual `module:function` reference, so the Redis jobstore can serialize the job.
   Code-only callables (an `add_schedule(success_callback=...)` callable and the bound methods of `auto_*` jobs) move
   out of job kwargs into process-local dicts on the manager.
2. **Fire-time re-check** (`AgentSchedulerManager._run_db_schedule`, new). It loads the row; then:
   - row missing, or `enabled=False` on a non-run-now fire → remove the local job and return the `SKIPPED` sentinel;
   - `schedule_fingerprint(row)` ≠ the job's `fingerprint` → `reschedule_job` with the new trigger and return `SKIPPED`;
   - otherwise → call the existing `_execute_agent_job` with fields read **from the row**, so edits made in other
     workers (prompt, metadata, callbacks, recipients) are picked up.
3. **Per-fire coordination** (`parrot/scheduler/coordination.py`, new).
   - A `FireCoordinator` protocol with `RedisFireCoordinator` (`SET <prefix>{job_id}:{run_time_iso} <worker_id> NX EX <ttl>`)
     and `NullFireCoordinator`.
   - `CoordinatedAsyncIOExecutor(AsyncIOExecutor)` overrides `_do_submit_job(job, run_times)`. That is the only
     APScheduler 3.x hook that sees the *scheduled* run time, which every worker computes identically. It claims
     `run_times[-1]`, the latest time, which matches `coalesce=True`.
   - A lost claim returns `[]` events, so `_run_job_success(job.id, [])` dispatches **nothing**: no listener, no stamp, no email.
   - A Redis error is treated as a lost claim plus a `lock_unavailable` stamp (fail closed).
   - The run-now 409 guard moves into the coordinator: `try_acquire_running` / `release_running`.
4. **Listeners on**. `on_startup` passes `register_listeners=True`. The latent bugs this exposes get fixed:
   - `job_status` crashes on `get_job() is None`;
   - `scheduler_status` calls `print(event)`;
   - `job_success` must ignore the `SKIPPED` sentinel;
   - `next_run` is refreshed after each fire and on load.

### Component Diagram
```
APScheduler loop (per worker)
   │ due job (func = "parrot.scheduler.jobs:run_db_schedule", kwargs = {manager_name, schedule_id, fingerprint})
   ▼
CoordinatedAsyncIOExecutor._do_submit_job(job, run_times)
   │ coordinator.claim(job.id, run_times[-1])
   ├── lost / Redis error ──→ return [] events (nothing dispatched)   [Redis error → stamp lock_unavailable]
   └── won ──→ run_coroutine_job(...) ──→ jobs.run_db_schedule(...)
                                              │ get_manager(manager_name)
                                              ▼
                              AgentSchedulerManager._run_db_schedule(schedule_id, fingerprint)
                                ├─ row missing/disabled ─→ remove local job, return SKIPPED
                                ├─ fingerprint changed ──→ reschedule_job, return SKIPPED
                                └─ _execute_agent_job(**fields from row)
                                              │ EVENT_JOB_EXECUTED (winner only)
                                              ▼
                              job_success (now wired on aiohttp) ─→ _process_job_success
                                                                     (DB stamp + next_run, send_result, callbacks)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AgentSchedulerManager.__init__` | modifies | registers the manager in `jobs`, installs `CoordinatedAsyncIOExecutor` as the `default` executor |
| `AgentSchedulerManager.start_headless` / `stop_headless` | modifies | build and attach the coordinator; close its Redis client |
| `AgentSchedulerManager.on_startup` | modifies | `register_listeners=True` |
| `add_schedule`, `load_schedules_from_db`, `update_schedule`, `run_schedule_now`, `register_bot_schedules`, `SchedulerHandler.patch` | modifies | every `add_job` switches to a trampoline plus `str`-only kwargs |
| `job_success`, `job_status`, `scheduler_status`, `_update_schedule_run` | modifies | latent fixes, `SKIPPED` handling, `next_run` refresh |
| `parrot.integrations.agentd.service` (`start_headless(dsn=..., use_redis=...)`) | unchanged caller | must keep working: listeners already on; coordination resolves to `none` unless configured |
| `apscheduler.executors.asyncio.AsyncIOExecutor` (pinned `apscheduler==3.11.2`) | subclasses | private `_do_submit_job` override; a guard test pins the signature |
| `redis.asyncio` | uses | same client idiom as `parrot/autonomous/redis_jobs.py:6` |

### Data Models

No DDL change. `navigator.agents_scheduler.metadata` (JSONB) gains one more value for the existing key
`last_status`: `"lock_unavailable"` (beside `"success"` / `"error"`).

```python
# parrot/scheduler/jobs.py
SKIPPED: Final[object]  # sentinel returned by a trampoline when a fire is intentionally skipped
```

### New Public Interfaces
See the per-module Interface Skeletons in §3. The public surface is: `parrot.scheduler.jobs` (`SKIPPED`,
`register_manager`, `get_manager`, `run_db_schedule`, `run_db_schedule_now`, `run_auto_schedule`) and
`parrot.scheduler.coordination` (`FireCoordinator`, `RedisFireCoordinator`, `NullFireCoordinator`,
`CoordinatedAsyncIOExecutor`, `build_fire_coordinator`, `FireCoordinationError`).

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Job trampolines | yes | file layout, names, kwargs and sentinel fixed below | — |
| M2: Fire coordination | yes | protocol, key format, TTL, fail-closed semantics and executor hook fixed below; the hook was verified against apscheduler 3.11.2 source | — |
| M3: Manager re-check + trampoline wiring | no | — | it touches 7 `add_job` sites plus `job_success` context recovery, and needs judgment on keeping `_execute_agent_job` backward-compatible |
| M4: Listeners on + latent fixes | yes | exact edits listed below | — |
| M5: Tests + docs | yes | test matrix in §4 | — |

### Module 1: Job trampolines
- **Path**: `packages/ai-parrot-server/src/parrot/scheduler/jobs.py` (new)
- **Responsibility**: picklable module-level job entrypoints, plus the process-local manager registry and the `SKIPPED` sentinel.
- **Depends on**: none (it uses `AgentSchedulerManager` only under `TYPE_CHECKING`, to avoid a circular import)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/scheduler/jobs.py  (new)
  from __future__ import annotations
  from typing import TYPE_CHECKING, Any, Dict, Final
  if TYPE_CHECKING:
      from .manager import AgentSchedulerManager

  SKIPPED: Final[object] = ...
  """Sentinel a trampoline returns when a fire was intentionally skipped (row gone/disabled/rescheduled).
  ``job_success`` must treat it as a no-op (no DB stamp, no callbacks, no email)."""

  _MANAGERS: Dict[str, "AgentSchedulerManager"] = {}

  def register_manager(manager: "AgentSchedulerManager") -> None:
      """Register ``manager`` under ``manager.registered_name`` (last registration wins; logged at debug)."""

  def unregister_manager(name: str) -> None:
      """Remove a registration; no error when absent (used by stop_headless and tests)."""

  def get_manager(name: str) -> "AgentSchedulerManager":
      """Return the registered manager; raise ``LookupError`` naming ``name`` when none is registered in this process."""

  async def run_db_schedule(manager_name: str, schedule_id: str, fingerprint: str) -> Any:
      """APScheduler entrypoint for DB-backed schedules → ``manager._run_db_schedule(schedule_id, fingerprint)``."""

  async def run_db_schedule_now(manager_name: str, schedule_id: str) -> Any:
      """Entrypoint for run-now one-shots → ``manager._run_db_schedule(schedule_id, None, run_now=True)``,
      releasing the run-now guard in ``finally`` (replaces ``_run_now_wrapper``)."""

  async def run_auto_schedule(manager_name: str, job_id: str) -> Any:
      """Entrypoint for decorator ``auto_*`` jobs → ``manager._run_auto_task(job_id)``."""
  ```

### Module 2: Fire coordination
- **Path**: `packages/ai-parrot-server/src/parrot/scheduler/coordination.py` (new)
- **Responsibility**: a per-fire, cross-worker claim and a cross-worker run-now guard, plus the executor hook that applies the claim.
- **Depends on**: none from this spec. It uses `redis.asyncio`, `sanitize_redis_settings` and apscheduler internals.
- **Config** (read with `from navconfig import config`, the same idiom as `manager.py:299`):
  - `SCHEDULER_COORDINATION`: `redis` | `none`.
  - `SCHEDULER_FIRE_LOCK_TTL`: int seconds, default `86400`.
  - `SCHEDULER_RUN_NOW_LOCK_TTL`: int seconds, default `3600`.
  - Redis connection: `sanitize_redis_settings(host=CACHE_HOST, port=CACHE_PORT, db=DEFAULT_REDIS_JOBSTORE_DB)`,
    the same server and db as the Redis jobstore, but a separate key prefix `parrot:scheduler:`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/scheduler/coordination.py  (new)
  from datetime import datetime
  from typing import Awaitable, Callable, Optional, Protocol
  import redis.asyncio as aioredis                                   # idiom verified: parrot/autonomous/redis_jobs.py:6
  from apscheduler.executors.asyncio import AsyncIOExecutor          # verified: apscheduler/executors/asyncio.py (3.11.2)
  from apscheduler.executors.base import run_coroutine_job           # verified: apscheduler/executors/base.py:161
  from apscheduler.util import iscoroutinefunction_partial           # verified: apscheduler/util.py:468

  class FireCoordinationError(Exception):
      """The coordination backend could not answer (e.g. Redis down). Callers MUST fail closed."""

  class FireCoordinator(Protocol):
      worker_id: str
      async def claim(self, job_id: str, run_time: datetime) -> bool:
          """True iff this worker won the fire ``(job_id, run_time)``; raises FireCoordinationError on backend failure."""
      async def try_acquire_running(self, schedule_id: str) -> bool:
          """Cross-worker run-now guard; False when another run-now for ``schedule_id`` is in flight."""
      async def release_running(self, schedule_id: str) -> None:
          """Release the run-now guard; never raises (logs)."""
      async def close(self) -> None: ...

  class NullFireCoordinator:
      """Single-process coordinator: claim() always True; the run-now guard is an in-process set (today's behaviour)."""

  class RedisFireCoordinator:
      """Claim = ``SET parrot:scheduler:fire:{job_id}:{run_time.isoformat()} {worker_id} NX EX {fire_ttl}``;
      run-now guard = ``SET parrot:scheduler:running:{schedule_id} {worker_id} NX EX {run_now_ttl}`` / ``DEL``."""
      def __init__(self, client: "aioredis.Redis", *, worker_id: Optional[str] = None,
                   fire_ttl: int = 86400, run_now_ttl: int = 3600, prefix: str = "parrot:scheduler:") -> None: ...

  def build_fire_coordinator(mode: Optional[str] = None, *, use_redis: bool = False) -> FireCoordinator:
      """Resolve the mode: explicit ``mode`` > ``SCHEDULER_COORDINATION`` > (``"redis"`` if use_redis else ``"none"``).
      Unknown values raise ``SchedulerConfigError`` (never silently coerced)."""

  class CoordinatedAsyncIOExecutor(AsyncIOExecutor):
      """AsyncIOExecutor whose coroutine jobs first claim ``(job.id, run_times[-1])`` from a coordinator."""
      def __init__(self, coordinator: Optional[FireCoordinator] = None,
                   on_unavailable: Optional[Callable[[str, BaseException], Awaitable[None]]] = None) -> None: ...
      def set_coordinator(self, coordinator: FireCoordinator) -> None:
          """Swap the coordinator (start_headless builds it after __init__)."""
      def _do_submit_job(self, job, run_times):  # overrides apscheduler/executors/asyncio.py:31
          """Wrap the coroutine: claim → (won) ``run_coroutine_job`` | (lost) ``[]`` | (FireCoordinationError)
          ``on_unavailable(job.id, exc)`` then ``[]``. Non-coroutine jobs: delegate to super() unchanged."""
  ```

### Module 3: Manager re-check and trampoline wiring
- **Path**: `packages/ai-parrot-server/src/parrot/scheduler/manager.py` (modifies)
- **Responsibility**:
  - Route every `add_job` through an M1 trampoline with `str`-only kwargs.
  - Re-check the row at fire time.
  - Keep code-only callables process-local.
  - Wire M2 into the scheduler lifecycle.
  - Move the run-now guard into the coordinator.
- **Depends on**: M1 (`jobs.*`), M2 (`CoordinatedAsyncIOExecutor`, `build_fire_coordinator`)
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-server/src/parrot/scheduler/manager.py
  def schedule_fingerprint(schedule: AgentSchedule) -> str:
      """sha256 hex of normalize_schedule_type(schedule_type) + json.dumps(sanitize_schedule_config(...), sort_keys=True,
      default=str) + normalized scheduler_type. Module-level; stable across processes."""

  class AgentSchedulerManager:
      def __init__(self, bot_manager: Any = None, **kwargs):          # verified: manager.py:338
          """+ ``self._fire_coordinator: FireCoordinator = NullFireCoordinator()``;
          + ``self._local_callbacks: Dict[str, Callable] = {}`` (schedule_id → add_schedule success_callback);
          + ``self._auto_tasks: Dict[str, Dict[str, Any]] = {}`` (job_id → method/agent_name/success_callback/send_result/callbacks);
          executors = {"default": CoordinatedAsyncIOExecutor(on_unavailable=self._on_coordination_unavailable)};
          ``jobs.register_manager(self)`` after registered_name is set (line 355).
          ``_run_now_active`` (line 354) is removed — superseded by the coordinator guard."""

      async def start_headless(self, *, dsn: Optional[str] = None, use_redis: bool = False,
                               register_listeners: bool = True,
                               coordination: Optional[str] = None) -> None:   # verified: manager.py:1720
          """+ ``coordination``: passed to ``build_fire_coordinator(coordination, use_redis=use_redis)`` and
          installed on the executor BEFORE ``scheduler.start()``."""

      async def stop_headless(self, *, wait: bool = True) -> None:      # verified: manager.py:1770
          """+ ``await self._fire_coordinator.close()`` (suppressed) and ``jobs.unregister_manager(...)``."""

      async def _run_db_schedule(self, schedule_id: str, fingerprint: Optional[str], *, run_now: bool = False) -> Any:
          """Fire-time re-check. Missing row → remove local job (suppress JobLookupError), return SKIPPED.
          ``enabled=False`` and not run_now → remove local job, return SKIPPED (run-now still runs a paused schedule,
          FEAT-467 contract). Fingerprint mismatch (not run_now) → ``reschedule_job`` with the row's new trigger,
          return SKIPPED. Else → ``await self._execute_agent_job(**fields from row,
          success_callback=self._local_callbacks.get(schedule_id))``."""

      async def _run_auto_task(self, job_id: str) -> Any:
          """Look up ``self._auto_tasks[job_id]`` and delegate to the existing ``_execute_agent_task``
          (verified: manager.py:1098); LookupError when unknown."""

      async def _on_coordination_unavailable(self, job_id: str, exc: BaseException) -> None:
          """Log error; for DB-backed jobs (job_id is a schedule UUID or ``run_now:<uuid>``) stamp
          ``metadata.last_status='lock_unavailable'`` + ``last_error`` via ``_update_schedule_run``-style write
          WITHOUT incrementing run_count."""

      async def run_schedule_now(self, schedule_id: str) -> AgentSchedule:   # verified: manager.py:1521
          """Guard via ``await self._fire_coordinator.try_acquire_running(schedule_id)`` (False → raise
          SchedulerRunNowConflictError, unchanged 409 contract); job func = ``jobs.run_db_schedule_now``,
          kwargs ``{manager_name, schedule_id}``; job id stays ``f"{_RUN_NOW_JOB_PREFIX}{schedule_id}"``."""
  ```
  - `_run_now_wrapper` (verified at `manager.py:1582`) is **removed**; its `finally` release moves into `jobs.run_db_schedule_now`.
  - `_job_kwargs_from_schedule` (verified at `manager.py:1322`) changes to return
    `{"manager_name", "schedule_id", "fingerprint"}`. The full field dict moves into a new private helper,
    `_execution_fields(schedule)`, which feeds `_execute_agent_job`.
  - `job_success` must still recover `agent_name`, `send_result` and `callbacks` from `_job_context`. That already
    works, because `_execute_agent_job` writes the context on success. The `job_kwargs.get(...)` fallbacks become dead
    and are removed.

### Module 4: Listeners on and latent listener fixes
- **Path**: `packages/ai-parrot-server/src/parrot/scheduler/manager.py` (modifies)
- **Responsibility**: turn the listeners on for aiohttp, and fix what that exposes.
- **Depends on**: M1 (`jobs.SKIPPED`)
- **Changes**:
  - `on_startup` (`manager.py:1853`) calls `start_headless(use_redis=True, register_listeners=True)`. Replace the
    FEAT-422 comment block (lines 1838-1852) with a short explanation that cites FEAT-631.
  - `scheduler_status` (`manager.py:456-459`) removes `print(event)`.
  - `job_status` (`manager.py:471`): when `get_job(job_id)` is `None`, use `job_name = job_id`, the same recovery
    `job_success` uses. It must never raise.
  - `job_success` (`manager.py:515`): `if getattr(event, "retval", None) is jobs.SKIPPED:` pop `_job_context`,
    return `True`, and do nothing else.
  - `_update_schedule_run` (`manager.py:863`): on success *and* error, set
    `schedule.next_run = job.next_run_time` when the local job exists.
  - `load_schedules_from_db`: after `add_job`, stamp `next_run` in a single batched pass. One `UPDATE … SET next_run`
    per loaded row is acceptable.

### Module 5: Tests and docs
- **Path**: `packages/ai-parrot-server/tests/scheduler/test_jobs.py`, `test_coordination.py`, `test_multiworker.py` (new);
  `docs/scheduler/multi-worker.md` (new)
- **Responsibility**: the test matrix in §4; operator documentation; a release note (CHANGELOG entry or PR body)
  calling out the behaviour change: on aiohttp, `send_result` emails and callbacks start firing for existing DB schedules.
- **Depends on**: M1–M4

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_trampoline_job_is_picklable` | M1/M3 | a job added via `load_schedules_from_db` path pickles: `pickle.dumps(job.__getstate__())` succeeds; `job.func_ref == "parrot.scheduler.jobs:run_db_schedule"` |
| `test_redis_jobstore_add_schedule_roundtrip` | M1/M3 | `add_schedule(scheduler_type="redis")` with a fake/in-memory Redis jobstore does not hit the rollback branch |
| `test_get_manager_unknown_raises` | M1 | `LookupError` naming the manager |
| `test_claim_once_across_two_coordinators` | M2 | two `RedisFireCoordinator`s (distinct worker_id) on one fake Redis: exactly one `claim()` is True for the same `(job_id, run_time)`; a different run_time is claimable again |
| `test_claim_redis_error_raises_coordination_error` | M2 | client raising `ConnectionError` → `FireCoordinationError` |
| `test_executor_lost_claim_dispatches_nothing` | M2 | `CoordinatedAsyncIOExecutor` with a coordinator returning False → job coroutine never awaited, no `EVENT_JOB_EXECUTED` |
| `test_executor_unavailable_fails_closed` | M2/M3 | coordinator raising → coroutine not run, `on_unavailable` awaited, `last_status=lock_unavailable` stamped, `run_count` unchanged |
| `test_executor_hook_signature_guard` | M2 | asserts `AsyncIOExecutor._do_submit_job` signature is `(self, job, run_times)` and `run_coroutine_job` is importable — fails loudly on an apscheduler upgrade |
| `test_build_fire_coordinator_modes` | M2 | explicit > `SCHEDULER_COORDINATION` > use_redis default; unknown value → `SchedulerConfigError` |
| `test_fire_skips_deleted_row` | M3 | row missing → returns `SKIPPED`, local job removed, agent never called |
| `test_fire_skips_disabled_row_but_run_now_runs` | M3 | disabled row: scheduled fire skipped; `run_schedule_now` still executes once |
| `test_fire_reschedules_on_fingerprint_change` | M3 | changed `schedule_config` → `reschedule_job` called with new trigger, fire skipped |
| `test_fire_uses_row_fields` | M3 | prompt edited in DB after load → execution uses the new prompt |
| `test_run_now_conflict_across_workers` | M3 | two managers sharing a Redis coordinator: second `run_schedule_now` raises `SchedulerRunNowConflictError`; released after completion and on failure |
| `test_on_startup_registers_listeners` | M4 | after `on_startup`, `EVENT_JOB_EXECUTED` listener present |
| `test_job_status_tolerates_missing_job` | M4 | `get_job() → None` with `EVENT_JOB_ERROR` does not raise |
| `test_job_success_ignores_skipped` | M4 | retval `SKIPPED` → no `_update_schedule_run`, no callbacks |
| `test_success_stamps_next_run` | M4 | success updates `next_run` from the local job |

### Integration Tests
| Test | Description |
|---|---|
| `test_two_workers_one_fire` | Two `AgentSchedulerManager` instances (two schedulers, one fake Redis, one fake pool) load the same interval row; drive one due fire → agent called once, `run_count` +1 once, success callback once |
| `test_delete_in_one_worker_stops_other` | worker A `delete_schedule`; worker B's next fire returns `SKIPPED` and drops its local job |
| `test_agentd_headless_unchanged` | existing `tests/scheduler/test_headless.py` and the agentd scheduler tests pass unchanged (coordination resolves to `none` without config) |

Existing `packages/ai-parrot-server/tests/scheduler/test_run_now.py` must pass after it is adapted to the removal of
`_run_now_wrapper` and `_run_now_active`. The adaptation may change only how the guard is reached, never the asserted
409, release and success-path behaviour.

### Test Data / Fixtures
```python
@pytest.fixture
def fake_redis():
    """In-memory async Redis double supporting SET NX EX / DEL (fakeredis.aioredis if available, else a minimal AsyncMock-backed dict)."""

@pytest.fixture
def two_managers(fake_redis, fake_pool):
    """Two managers with distinct registered_name, sharing fake_redis via RedisFireCoordinator and one fake row store."""
```

---

## 5. Acceptance Criteria

- [ ] **AC1 (G1)**: `on_startup` registers the listeners; a successful DB-schedule fire on the aiohttp path stamps `last_run`, `run_count`, `metadata.last_result`, `metadata.last_status="success"` and `next_run`, and runs `send_result` / `callbacks`.
- [ ] **AC2 (G2)**: with two managers sharing one Redis coordinator, one due fire executes the agent exactly once, and listeners, DB stamp and callbacks run exactly once. This holds for DB-backed jobs and `auto_*` jobs.
- [ ] **AC3 (G3)**: deleting or disabling a row in one manager makes the other manager's next fire return `SKIPPED` and remove its local job; changing `schedule_config` reschedules and skips; prompt/metadata edits are used by the next fire.
- [ ] **AC4 (G3, FEAT-467 contract)**: run-now still executes a paused schedule once and leaves it paused; a concurrent run-now in *another* worker gets 409.
- [ ] **AC5 (G4)**: every `scheduler.add_job` call in `manager.py` passes a function from `parrot.scheduler.jobs` and kwargs whose values are all `str`. `grep -n "add_job(\s*self\._" manager.py` returns nothing, and every job pickles.
- [ ] **AC6 (G5)**: with Redis raising on `claim`, no agent call happens, an error is logged, a DB-backed row gets `metadata.last_status="lock_unavailable"`, and `run_count` is unchanged.
- [ ] **AC7 (G6)**: `SCHEDULER_COORDINATION=none` uses `NullFireCoordinator`. An unknown value raises `SchedulerConfigError` at `start_headless`.
- [ ] **AC8**: `job_status` never raises on a missing job; `print(` no longer appears in `scheduler/manager.py`.
- [ ] **AC9**: the agentd headless path (`parrot/integrations/agentd/service.py:526`) works with no code change, and its existing tests pass.
- [ ] **AC10**: all §4 tests pass: `pytest packages/ai-parrot-server/tests/scheduler/ -v`. `ruff check` is clean on the changed files.
- [ ] **AC11**: `docs/scheduler/multi-worker.md` documents the coordination modes, the config keys, the fail-closed behaviour, the fact that the `redis` jobstore gives persistence but not coordination, and the listener behaviour change. The PR body carries the release note.

---

## 6. Codebase Contract

Verified against `479042d3e` (dev, 2026-10-05).

### Verified Imports
```python
from parrot.scheduler.manager import AgentSchedulerManager, SchedulerRunNowConflictError  # verified: tests/scheduler/test_run_now.py:31
from parrot.scheduler.models import AgentSchedule                 # verified: scheduler/models.py:7 (imported as .models in manager.py:42)
from parrot.scheduler.sanitize import SchedulerConfigError, sanitize_redis_settings, DEFAULT_REDIS_JOBSTORE_DB  # verified: sanitize.py:236, :88; manager.py:43-52
from parrot.scheduler.sanitize import normalize_schedule_type, sanitize_schedule_config, normalize_jobstore_alias  # verified: manager.py:43-52
from parrot.conf import default_dsn, CACHE_HOST, CACHE_PORT        # verified: manager.py:41
from navconfig import config as nav_config                         # verified: manager.py:299 (local import idiom)
import redis.asyncio as aioredis                                   # verified: parrot/autonomous/redis_jobs.py:6
from apscheduler.executors.asyncio import AsyncIOExecutor          # verified: manager.py:28
from apscheduler.executors.base import run_coroutine_job           # verified: apscheduler 3.11.2 executors/base.py:161
from apscheduler.util import iscoroutinefunction_partial           # verified: apscheduler 3.11.2 util.py:468
from apscheduler.jobstores.base import JobLookupError              # verified: manager.py:29
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/scheduler/manager.py
_RUN_NOW_JOB_PREFIX = "run_now:"                                                     # line 86
class SchedulerRunNowConflictError(Exception): ...                                   # line 74
class AgentSchedulerManager:                                                         # line 324
    registered_name: str = "scheduler_manager"                                       # line 336
    def __init__(self, bot_manager: Any = None, **kwargs): ...                       # line 338
        self._job_context: Dict[str, Dict[str, Any]]                                 # line 348
        self._run_now_active: Set[str]                                               # line 354
        executors = {"default": AsyncIOExecutor()}                                   # line 365
        job_defaults = {"coalesce": True, "max_instances": 2, "misfire_grace_time": 300}  # lines 366-370
    def define_listeners(self): ...                                                  # line 447
    def scheduler_status(self, event): ...  # print(event) at line 457              # line 456
    def job_status(self, event: JobExecutionEvent): ...  # job.name on possibly-None job at 484   # line 471
    def job_success(self, event: JobExecutionEvent): ...                             # line 515
    async def _execute_agent_job(self, schedule_id: str, agent_name: str, prompt: Optional[str] = None,
        method_name: Optional[str] = None, metadata: Optional[Dict] = None, *, is_crew: bool = False,
        success_callback: Optional[Callable] = None, send_result: Optional[Dict[str, Any]] = None,
        callbacks: Optional[List[Dict[str, Any]]] = None): ...                       # line 609
    async def _process_job_success(self, schedule_id, agent_name, result, success_callback, send_result,
        callbacks=None, *, persist: bool = True) -> None: ...                        # line 791
    async def _update_schedule_run(self, schedule_id: str, success: bool = True,
        error: Optional[str] = None, result: Any = None): ...                        # line 863
    def _create_trigger(self, schedule_type: str, config: Dict[str, Any]): ...       # line 920
    async def add_schedule(self, agent_name, schedule_type, schedule_config, prompt=None, method_name=None,
        created_by=None, created_email=None, metadata=None, agent_id=None, *, is_crew=False, send_result=None,
        success_callback=None, scheduler_type="default", callbacks=None) -> AgentSchedule: ...  # line 975
    async def _execute_agent_task(self, job_id: str, agent_name: str, method: Callable, *,
        success_callback=None, send_result=None, callbacks=None) -> Any: ...         # line 1098
    def register_bot_schedules(self, bot: Any) -> int: ...                           # line 1146
    async def remove_schedule(self, schedule_id: str): ...                           # line 1219
    async def load_schedules_from_db(self): ...                                      # line 1237
    async def restart_scheduler(self): ...                                           # line 1302
    def _job_kwargs_from_schedule(self, schedule: AgentSchedule) -> Dict[str, Any]: ...  # line 1322
    async def get_schedule(self, schedule_id: str) -> AgentSchedule: ...             # line 1419
    async def pause_schedule(self, schedule_id: str) -> AgentSchedule: ...           # line 1431
    async def update_schedule(self, schedule_id: str, updates: Dict[str, Any]) -> AgentSchedule: ...  # line 1443
    async def delete_schedule(self, schedule_id: str) -> None: ...                   # line 1509
    async def run_schedule_now(self, schedule_id: str) -> AgentSchedule: ...         # line 1521
    async def _run_now_wrapper(self, schedule_id: str, **kwargs) -> Any: ...         # line 1582
    def _safe_jobstore(self, value: Any, *, strict: bool = False) -> str: ...        # line 1658
    def _make_redis_jobstore(self) -> RedisJobStore: ...                             # line 1693
    async def start_headless(self, *, dsn: Optional[str] = None, use_redis: bool = False,
        register_listeners: bool = True) -> None: ...                                # line 1720
    async def stop_headless(self, *, wait: bool = True) -> None: ...                 # line 1770
    async def on_startup(self, app: web.Application, conn: Callable): ...            # line 1831

# apscheduler 3.11.2 (pinned: packages/ai-parrot-server/pyproject.toml:43 "apscheduler==3.11.2")
class BaseExecutor:
    def submit_job(self, job, run_times): ...          # executors/base.py:58 (increments _instances)
    def _run_job_success(self, job_id, events): ...    # executors/base.py:81 (decrements _instances, dispatches events)
    def _run_job_error(self, job_id, exc, traceback=None): ...  # executors/base.py:95
class AsyncIOExecutor(BaseExecutor):
    def _do_submit_job(self, job, run_times): ...      # executors/asyncio.py:31 — create_task(run_coroutine_job(job, job._jobstore_alias, run_times, self._logger.name)); done-callback → _run_job_success(job.id, events)
async def run_coroutine_job(job, jobstore_alias, run_times, logger_name): ...  # executors/base.py:161
# Job.__getstate__ pickles func.__self__ for instance methods → manager unpicklable (TypeError "Schedulers cannot be serialized")
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `jobs.run_db_schedule` | `AgentSchedulerManager._run_db_schedule` (new) → `_execute_agent_job` | method call | `manager.py:609` |
| `jobs.run_auto_schedule` | `_run_auto_task` (new) → `_execute_agent_task` | method call | `manager.py:1098` |
| `CoordinatedAsyncIOExecutor` | `AsyncIOScheduler(executors=...)` | constructor arg | `manager.py:365`, `:372-377` |
| `build_fire_coordinator` | `start_headless` | call before `scheduler.start()` | `manager.py:1762-1763` |
| `RedisFireCoordinator` client | `sanitize_redis_settings(host=CACHE_HOST, port=CACHE_PORT, db=6)` | `aioredis.Redis(**settings)` | `manager.py:1700`, `sanitize.py:236` |
| `_on_coordination_unavailable` | `AgentSchedule` row metadata | asyncdb model update (same pattern as `_update_schedule_run`) | `manager.py:886-917` |
| agentd | `start_headless(dsn=..., use_redis=...)` | unchanged call | `ai-parrot-integrations/.../agentd/service.py:526` |
| `CALLBACK_REGISTRY` callbacks | `_handle_job_success` → `build_scheduler_callback` | unchanged | `manager.py:704`, `scheduler/functions/__init__.py` |

### Does NOT Exist (Anti-Hallucination)
- ~~`packages/ai-parrot-server/src/parrot/scheduler/__init__.py`~~: `parrot.scheduler` is a namespace subpackage. Import submodules explicitly (`parrot.scheduler.manager`, `.jobs`, `.coordination`).
- ~~`parrot.scheduler.jobs`~~, ~~`parrot.scheduler.coordination`~~: created by M1 and M2.
- ~~`AgentSchedulerManager._run_db_schedule` / `_run_auto_task` / `_on_coordination_unavailable` / `_fire_coordinator` / `_local_callbacks` / `_auto_tasks`~~: created by M3.
- ~~a `SCHEDULER_COORDINATION` / `SCHEDULER_FIRE_LOCK_TTL` setting in `parrot/conf.py`~~: read via navconfig inside `coordination.py`, not added to core `parrot/conf.py`.
- ~~`packages/ai-parrot-server/src/parrot/conf.py`~~: the server package has no `conf.py`; `from ..conf import ENVIRONMENT` in manager.py resolves to core `parrot.conf`.
- ~~APScheduler passing the scheduled run time into the job function~~: it doesn't in 3.x; only the executor sees `run_times`.
- ~~a cross-process job-store coordination in APScheduler 3.x~~: sharing a `RedisJobStore` among schedulers is unsupported (duplicate or missed runs).
- ~~an `agents_scheduler` column for locks/claims~~: no DDL change in this feature.

### Edit Sites (Blueprint Anchors)

Verified against: `479042d3e`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/jobs.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/scheduler/coordination.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `        self._run_now_active: Set[str] = set()` | `manager.py:354` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `        executors = {"default": AsyncIOExecutor()}` | `manager.py:365` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `        print(event)` | `manager.py:457` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    def job_status(self, event: JobExecutionEvent):` (fix the `job_name = job.name` that follows `job = self.scheduler.get_job(job_id)` inside it; `job_name = job.name` alone occurs 3×: 467, 484, 531) | `manager.py:471` / `:484` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    def job_success(self, event: JobExecutionEvent):` | `manager.py:515` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    async def _update_schedule_run(` | `manager.py:863` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | add_schedule: `            job = self.scheduler.add_job(` + next line `                self._execute_agent_job,` + `                id=str(schedule.schedule_id),` (anchor `job = self.scheduler.add_job(` occurs 2×: 1071, 1493) | `manager.py:1071` | 2 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `                    self._execute_agent_task,` (register_bot_schedules) | `manager.py:1196` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `                            self._execute_agent_job,` (load_schedules_from_db) | `manager.py:1272` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    def _job_kwargs_from_schedule(self, schedule: AgentSchedule) -> Dict[str, Any]:` | `manager.py:1322` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | update_schedule: `            job = self.scheduler.add_job(` + next line `                self._execute_agent_job,` + `                id=job_id,` | `manager.py:1493` | 2 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    async def run_schedule_now(self, schedule_id: str) -> AgentSchedule:` | `manager.py:1521` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    async def _run_now_wrapper(self, schedule_id: str, **kwargs) -> Any:` (remove) | `manager.py:1582` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    async def start_headless(` | `manager.py:1720` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    async def stop_headless(self, *, wait: bool = True) -> None:` | `manager.py:1770` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `        await self.start_headless(use_redis=True, register_listeners=False)` | `manager.py:1853` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `SchedulerHandler.patch` re-add: `                    scheduler_manager.scheduler.add_job(` | `manager.py:2005` | 1 |
| `packages/ai-parrot-server/tests/scheduler/test_run_now.py` | MODIFY | `from parrot.scheduler.manager import AgentSchedulerManager, SchedulerRunNowConflictError` | `test_run_now.py:31` | 1 |
| `packages/ai-parrot-server/tests/scheduler/test_jobs.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/scheduler/test_coordination.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/scheduler/test_multiworker.py` | CREATE | — | — | — |
| `docs/scheduler/multi-worker.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Redis SET NX EX idiom: `RedisEventDeduplicator.is_duplicate` (`ai-parrot-integrations/.../slack/dedup.py:168`). Async client creation: `parrot/autonomous/redis_jobs.py:38`.
- DB row writes follow `_update_schedule_run`: `async with await self._pool.acquire() as conn: AgentSchedule.Meta.connection = conn` and an **awaited** `AgentSchedule.get(...)`. The missing-`await` bug fixed in FEAT-467 must not come back.
- `str`-only job kwargs. Anything that is not JSON-able stays process-local (`_local_callbacks`, `_auto_tasks`).
- Logging via `self.logger` / module logger with `%`-style args. No `print`.
- The claim key uses `run_times[-1].isoformat()` (tz-aware UTC; the scheduler is built with `timezone="UTC"`, `manager.py:376`), so every worker produces byte-identical keys.

### Known Risks / Gotchas
- **Private APScheduler API.** `_do_submit_job` and `run_coroutine_job` are internal. Mitigations: `apscheduler==3.11.2` is already pinned exactly (`pyproject.toml:43`), and `test_executor_hook_signature_guard` fails loudly on drift.
- **Clock skew between hosts.** It does not affect key equality, because each worker derives the run time from the trigger rather than from its wall clock. Skew only delays when a worker *tries* to claim. The TTL (24 h) must exceed `misfire_grace_time` (300 s) plus the skew, so it does.
- **`max_instances` stays per process.** A long run in worker A does not stop worker B from claiming the *next* fire. That is acceptable, and it is the same semantics a single process has today.
- **Behaviour change on aiohttp.** Existing DB schedules with `send_result`/`callbacks` start delivering after deploy, and successes start stamping. This needs a release note (AC11).
- **The lost-claim worker's `_job_context`.** The loser never runs `_execute_agent_job`, so it never writes context, and there is nothing to leak.
- **`SKIPPED` passes through `EVENT_JOB_EXECUTED`.** `job_success` must short-circuit on it, or a skipped fire would stamp a "success".
- **Reschedule on fingerprint change.** Use `scheduler.reschedule_job(job_id, jobstore=..., trigger=...)`. If the jobstore alias changed (`scheduler_type` edited elsewhere), remove the job and re-add it in the new store instead.
- **Run-now on a deleted row.** `_run_db_schedule(run_now=True)` returns `SKIPPED` and the guard is released in the trampoline's `finally`.
- **Two managers in one process** (tests, embedded apps) must use distinct `registered_name` values, or `register_manager` overwrites. The last registration wins, and that is documented.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `apscheduler` | `==3.11.2` (already pinned) | executor hook depends on 3.11.2 internals |
| `redis` (`redis.asyncio`) | already a server dependency (used by `parrot/autonomous/redis_jobs.py`) | claim / guard keys |
| `fakeredis` | test-only, optional | in-memory async Redis for tests; fall back to a dict-backed `AsyncMock` if absent (do not add a hard dependency) |

---

## 8. Open Questions

- [x] How should workers avoid duplicate firing? *Resolved in proposal Q&A (2026-10-05)*: a per-fire Redis lock (`SET NX` on job_id + scheduled_run_time), which also covers `auto_*` jobs. Leader election and a Postgres claim column were rejected. → §2 Overview item 3, M2, AC2.
- [x] Should listeners be on for the aiohttp path? *Resolved in proposal Q&A*: on by default, with no feature flag and a release note. → M4, AC1, AC11.
- [x] What happens when Redis is unreachable at fire time? *Resolved in proposal Q&A*: fail closed (skip, log an error, stamp `last_status=lock_unavailable`); `SCHEDULER_COORDINATION=none` is the explicit single-process opt-out. → G5, G6, AC6, AC7.
- [ ] Q1: Should `scheduler_type="redis"` stay supported once it pickles? It gives persistence but not coordination, and APScheduler 3 warns against sharing a jobstore across processes. Options: keep it with a docs warning (current spec assumption, AC11), or deprecate it. *Owner: Jesus Lara*
- [ ] Q2: Should `POST /api/v1/parrot/scheduler/restart` restart all workers (via a Redis broadcast) or remain per-worker? Out of scope here; the current behaviour is kept. *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` · Status: skipped (proposal frontmatter `status: review`, not `accepted`; the §3b precondition was not met) · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree, `.claude/worktrees/feat-FEAT-631-scheduler-multiworker-correctness`, based on `origin/dev`. The sdd-coder engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M3 → M1: M3 calls `jobs.run_db_schedule`, `run_db_schedule_now`, `run_auto_schedule`, `register_manager`, and `SKIPPED`.
  - M3 → M2: M3 builds `CoordinatedAsyncIOExecutor` and calls `build_fire_coordinator` in `__init__` / `start_headless`.
  - M4 → M1: M4 compares `retval is jobs.SKIPPED`.
  - M5 → M1–M4.
  - M1 and M2 have no edge between them and run concurrently.
- **Shared files**: `scheduler/manager.py` is modified by both M3 and M4, so their tasks are serialized (M4 after M3, or merged into adjacent tasks).
- **Exclusive resources**: none. There is no migration, lockfile change or extension rebuild; `fakeredis` stays optional.
- **Cross-feature dependencies**: none. FEAT-467 (run-now / last-result) and FEAT-422 (`start_headless`) are already merged; their contracts are preserved by AC4 and AC9.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-05 | Jesus Lara / Claude | Initial draft from proposal GH-1573 (issue #1573) |
| 0.2 | 2026-10-05 | Jesus Lara | Approved for decomposition |

# TASK-4155: SchedulerManager lifecycle: init, namespaced jobstores, coordinator, run-state stores, headless and aiohttp startup

**Feature**: FEAT-644 — SchedulerManager base (db | redis | code backends)
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4154, TASK-4149, TASK-4150, TASK-4151, TASK-4152
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, second slice: the `SchedulerManager` class shell and everything about starting and stopping it.
This is a behaviour-preserving move of `packages/ai-parrot-server/src/parrot/scheduler/manager.py:362-400` (`__init__`), `:1840-1918` (jobstores), `:1064-1117`
(`_create_trigger`), `:1552-1560` (`_get_connection_pool`), `:1919-2097` (headless + aiohttp lifecycle and routes) and
`:1445-1463` (`restart_scheduler`), with three changes: Redis keys are namespaced by `registered_name`
(`parrot:scheduler:{name}:jobs` / `:run_times`), the coordinator is built with that prefix and forced to `redis` when
the jobstore is attached, and the manager owns one async Redis client plus one `RunStateStore` per backend.

Redis-backed tests use the `scheduler_redis` / `scheduler_redis_sync` fixtures from `packages/ai-parrot-server/tests/scheduler/conftest.py` (created by TASK-4149): a REAL Redis at `CACHE_HOST:CACHE_PORT`, logical db 15, a unique `registered_name` per test, keys deleted by that prefix on teardown, and `pytest.skip` when Redis is unreachable. `fakeredis` is NOT installed in the workspace venv and is not declared in any `pyproject.toml` (spec §4/§7 assumed it was — this is the recorded deviation); do not import it.

---

## Scope

- Add `class SchedulerManager` with `registered_name = "scheduler_manager"` and `__init__(**kwargs)` (move of manager.py:362-400 minus `bot_manager`; adds `self.targets = TargetRegistry()`, `self._resolvers = {'service': RegistryResolver(self.targets)}`, `self._code_jobs: dict[str, CodeJobRecord] = {}`, `self._memory_state = MemoryRunState()`, `self._redis_client = None`, settings `self._max_failures` / `self._alert_recipients`).
- Add `register_resolver(resolver)` and `register_target(name, obj, *, kind='service', methods=None)`.
- Move jobstore helpers: `_build_jobstores`, `_make_redis_jobstore` (namespaced keys, `db=redis_db()`), `_ensure_redis_jobstore`, `_registered_jobstores`, plus a `redis_available` property.
- Move `_create_trigger` (with `ScheduleType` from base; `once` default run_date → `utcnow()`), `_get_connection_pool`.
- Add `_run_state_for(backend) -> RunStateStore` (db → `PostgresRunState(pool.acquire)`, redis → `RedisRunState(self._redis_client, prefix=manager_prefix(name) + 'runstate:')` or `SchedulerUnavailableError`, code → `self._memory_state`).
- Move `start_headless` / `stop_headless` (build/close the async Redis client; coordinator via `build_fire_coordinator(coordination, use_redis=use_redis, prefix=manager_prefix(self.registered_name))`), `setup` (same routes), `on_startup` (no bot scanning), `on_shutdown`, `restart_scheduler`, `restart_handler`.
- Write `tests/scheduler/test_base_lifecycle.py`.

**NOT in scope**: `define_listeners` and the listeners (TASK-4157 — `start_headless(register_listeners=True)` calls a method TASK-4157 adds; this task's tests pass `register_listeners=False`); `load_schedules_from_db` (TASK-4156 — only called when a pool exists); add/CRUD (TASK-4156); fire path (TASK-4157); any manager.py change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/base.py` | MODIFY | SchedulerManager class: init, registration, jobstores, run-state stores, lifecycle, routes |
| `packages/ai-parrot-server/tests/scheduler/test_base_lifecycle.py` | CREATE | Lifecycle, namespacing and forced-coordinator tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase (verified on `dev` @ `3555841e9`, 2026-10-08).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# moved from packages/ai-parrot-server/src/parrot/scheduler/manager.py:9-60 — only what this slice uses
import asyncio, contextlib
from typing import Any, Callable, Dict, Optional, Set
from apscheduler.jobstores.memory import MemoryJobStore                    # manager.py:30
from apscheduler.jobstores.redis import RedisJobStore                      # manager.py:31
from apscheduler.schedulers.asyncio import AsyncIOScheduler                # manager.py:32
from apscheduler.triggers.cron import CronTrigger                          # manager.py:33
from apscheduler.triggers.date import DateTrigger                          # manager.py:34
from apscheduler.triggers.interval import IntervalTrigger                  # manager.py:35
from aiohttp import web                                                    # manager.py:36
from asyncdb import AsyncDB                                                # manager.py:39
from navigator.connections import PostgresPool                             # manager.py:41
from parrot.conf import default_dsn, CACHE_HOST, CACHE_PORT                # manager.py:42
import redis.asyncio as aioredis                                           # coordination.py:13
from navconfig import config as nav_config                                 # coordination.py:149 (lazy there)
from .sanitize import normalize_schedule_type, sanitize_schedule_config, sanitize_redis_settings, normalize_backend  # sanitize.py + TASK-4150
from .coordination import CoordinatedAsyncIOExecutor, FireCoordinator, NullFireCoordinator, build_fire_coordinator, manager_prefix, redis_db  # + TASK-4151
from .runstate import RunStateStore, PostgresRunState, RedisRunState, MemoryRunState      # TASK-4148/4149
from .models import CodeJobRecord                                          # TASK-4147
from . import jobs                                                         # manager.py:57
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:362-400 — __init__ body to move (logger "Parrot.Scheduler", _pool, _owns_pool, _job_context, _pending_success_tasks,
#   registered_name kwarg, _fire_coordinator = NullFireCoordinator(), _local_callbacks, jobs.register_manager(self),
#   executors {"default": CoordinatedAsyncIOExecutor(on_unavailable=self._on_coordination_unavailable)},
#   job_defaults coalesce=True, max_instances=2, misfire_grace_time=300; AsyncIOScheduler(..., timezone="UTC"))
# NOTE: `_on_coordination_unavailable` is added by TASK-4157 — pass a lambda that awaits it lazily, or define a stub
#   `async def _on_coordination_unavailable(self, job_id, exc) -> None` HERE that TASK-4157 then replaces.
def _make_redis_jobstore(self) -> RedisJobStore:          # packages/ai-parrot-server/src/parrot/scheduler/manager.py:1892 — jobs_key="apscheduler.jobs", run_times_key="apscheduler.run_times", db=6
async def start_headless(self, *, dsn=None, use_redis=False, register_listeners=True, coordination=None)  # packages/ai-parrot-server/src/parrot/scheduler/manager.py:1919
async def stop_headless(self, *, wait: bool = True) -> None   # packages/ai-parrot-server/src/parrot/scheduler/manager.py:1977
def setup(self, app: web.Application) -> web.Application     # packages/ai-parrot-server/src/parrot/scheduler/manager.py:2005 — registers the 5 routes, app[self.registered_name] = self
async def on_startup(self, app, conn)                         # packages/ai-parrot-server/src/parrot/scheduler/manager.py:2042 — start_headless(use_redis=True, register_listeners=True)
# coordination (TASK-4151): manager_prefix(name) -> "parrot:scheduler:<name>:"; redis_db() -> int;
#   build_fire_coordinator(mode=None, *, use_redis=False, prefix=DEFAULT_PREFIX)
```
Routes (move verbatim, `setup()` at manager.py:2017-2037): `/api/v1/parrot/scheduler/schedules`,
`/schedules/{schedule_id}`, `/schedules/{schedule_id}/last-result`, `/callbacks`, `POST /restart`.
(Spec §7 said route registration was "not located" — it is here, in `setup()`.)

### Does NOT Exist
- ~~`SchedulerManager`~~ — created here.
- ~~`self.bot_manager` on the base~~ — only `AgentSchedulerManager` has it (TASK-4158).

- ~~`BotManager`, `parrot.manager`, `parrot.bots`, `parrot.registry` imports in `base.py`~~ — forbidden (spec AC1); agent/crew resolution lives in `manager.py` (TASK-4158).
- ~~`from .manager import ...` in `base.py`~~ — circular (manager imports base). `ScheduleType`, `SchedulerRunNowConflictError` and `_RUN_NOW_JOB_PREFIX` are defined in `base.py` (TASK-4154); `manager.py` re-exports them in TASK-4158.
- ~~`AgentSchedule` in `base.py`~~ — base uses `ServiceSchedule` only.
- ~~`datetime.now()` in `base.py`~~ — use `utcnow()` everywhere (AC7).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/scheduler/base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/scheduler/test_base_lifecycle.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.__init__",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.start_headless",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.stop_headless",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.setup",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.on_startup",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._make_redis_jobstore",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._create_trigger",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/coordination.py#CoordinatedAsyncIOExecutor",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/jobs.py#register_manager"
  ]
}
```

---

## Implementation Notes

`__init__` settings: `self._max_failures = clean_int(nav_config.get("SCHEDULER_MAX_CONSECUTIVE_FAILURES"), default=3, minimum=1, ...)`
(read `clean_int`'s full signature at sanitize.py:148 first); `self._alert_recipients = [r.strip() for r in
str(nav_config.get("SCHEDULER_ALERT_RECIPIENTS") or "").split(",") if r.strip()]`.

`start_headless` order (spec §2 "Startup order", unchanged from today but now load-bearing for Redis jobs):
attach Redis jobstore (+ build `self._redis_client`) → pool from `dsn` → `define_listeners()` when asked →
coordinator (`prefix=manager_prefix(...)`) set on the executor → `scheduler.start()` (APScheduler loads the Redis jobs
here) → `load_schedules_from_db()` only when a pool exists.

`stop_headless` also closes `self._redis_client` (`aclose`, suppressed) and sets it to `None`.

Tests: monkeypatch `navconfig.config.get` so `SCHEDULER_REDIS_DB` returns `15` and use `scheduler_namespace` as
`registered_name`. Never construct a manager without `stop_headless` in teardown — `jobs._MANAGERS` is process-global.

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
1. Add the imports and the class header with `__init__` (moved) — *why*: same scheduler/executor/job_defaults as today (AC: behaviour-preserving).
2. Add `register_resolver` / `register_target` — *why*: G1 public registration API.
3. Move the jobstore helpers and namespace the Redis keys — *why*: AC14 / S3.
4. Move `_create_trigger`, `_get_connection_pool`; add `_run_state_for` — *why*: later slices call them.
5. Move the lifecycle methods with the coordinator + Redis client changes — *why*: Redis jobs reload on `scheduler.start()`.
6. Write the tests and run them.

### `packages/ai-parrot-server/src/parrot/scheduler/base.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-4154: grep -c '^class RegistryResolver' packages/ai-parrot-server/src/parrot/scheduler/base.py)
# AFTER the end of `class RegistryResolver` — append:
class SchedulerManager:
    """Target-agnostic scheduler: APScheduler + Postgres/Redis/code backends (FEAT-644)."""

    registered_name: str = "scheduler_manager"

    def __init__(self, **kwargs: Any) -> None:
        """Build the scheduler (UTC, coalesce, max_instances=2, misfire 300s) and register in ``jobs``."""
        # FILL IN: move manager.py:362-400 (minus bot_manager) + the new attributes listed in Scope.

    def register_resolver(self, resolver: TargetResolver) -> None:
        """Install/replace the resolver for ``resolver.kind``."""
        self._resolvers[resolver.kind] = resolver

    def register_target(self, name: str, obj: Any, *, kind: str = "service",
                        methods: Sequence[str] | None = None) -> None:
        """Explicit registration consulted first by every resolver."""
        self.targets.register(name, obj, kind=kind, methods=methods)

    @property
    def redis_available(self) -> bool:
        """True when the ``redis`` jobstore is attached."""
        return "redis" in self._registered_jobstores()

    def _make_redis_jobstore(self) -> RedisJobStore:
        """RedisJobStore with keys ``parrot:scheduler:<name>:jobs`` / ``:run_times`` on ``SCHEDULER_REDIS_DB``."""
        prefix = manager_prefix(self.registered_name)
        return RedisJobStore(
            jobs_key=f"{prefix}jobs",
            run_times_key=f"{prefix}run_times",
            **sanitize_redis_settings(host=CACHE_HOST, port=CACHE_PORT, db=redis_db()),
        )

    # FILL IN: move _build_jobstores, _ensure_redis_jobstore, _registered_jobstores (manager.py:1840-1918),
    #          _create_trigger (1064-1117; datetime.now() → utcnow()), _get_connection_pool (1552-1560).

    def _run_state_for(self, backend: str) -> RunStateStore:
        """Return the RunStateStore for ``backend``; ``redis`` without a client → SchedulerUnavailableError."""
        # FILL IN: db → PostgresRunState(pool.acquire) (pool required → SchedulerUnavailableError if None);
        #          redis → RedisRunState(self._redis_client, prefix=manager_prefix(self.registered_name) + "runstate:");
        #          code → self._memory_state; anything else → ValueError.
```
```python
# (continued) — lifecycle, moved from manager.py:1919-2097 and 1445-1463
    async def start_headless(self, *, dsn: Optional[str] = None, use_redis: bool = False,
                             register_listeners: bool = True, coordination: Optional[str] = None) -> None:
        """Boot without aiohttp; order: jobstores → pool → listeners → coordinator → start → load db rows."""
        # FILL IN: as manager.py:1919-1975 + async Redis client (decode_responses=True, db=redis_db()) when use_redis
        #          + build_fire_coordinator(coordination, use_redis=use_redis, prefix=manager_prefix(self.registered_name)).

    async def stop_headless(self, *, wait: bool = True) -> None:
        """Shut down; close the owned pool, the async Redis client and the coordinator; unregister."""
        # FILL IN: manager.py:1977-2003 + close self._redis_client.

    def setup(self, app: web.Application) -> web.Application:
        """Pool + the 5 scheduler routes (moved verbatim from manager.py:2005-2040)."""
        # FILL IN

    async def on_startup(self, app: web.Application, conn: Callable) -> None:
        """Set the pool and ``start_headless(use_redis=True, register_listeners=True)``; no bot scanning here."""
        # FILL IN

    # FILL IN: on_shutdown, restart_scheduler, restart_handler — moved verbatim.
```
**Why**: AgentSchedulerManager (TASK-4158) overrides only `__init__` and `on_startup`; everything else it inherits,
so this slice must be a faithful move — diff it against manager.py when done.

### FILL IN checklist
- [ ] `__init__` — moved body + new attributes; settings via nav_config.
- [ ] Moved jobstore helpers / `_create_trigger` (utcnow) / `_get_connection_pool`.
- [ ] `_run_state_for` — three backends, fail closed for redis.
- [ ] `start_headless` / `stop_headless` — Redis client + namespaced coordinator.
- [ ] `setup` / `on_startup` / `on_shutdown` / `restart_*` — moved.

---

## Acceptance Criteria

- [ ] `SchedulerManager(registered_name=ns)` + `start_headless(use_redis=True, register_listeners=False)` attaches a RedisJobStore whose keys start with `parrot:scheduler:<ns>:` and a `RedisFireCoordinator` with that prefix (even when `SCHEDULER_COORDINATION=none`).
- [ ] `_run_state_for('redis')` returns a `RedisRunState` after start and raises `SchedulerUnavailableError` without Redis.
- [ ] `stop_headless()` is safe without a prior start and unregisters the manager from `jobs`.
- [ ] `setup(app)` registers the same 5 routes as the legacy manager.
- [ ] The legacy `AgentSchedulerManager` suite (`test_headless.py`) is untouched and still passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

- `pytest packages/ai-parrot-server/tests/scheduler/test_base_lifecycle.py -q`
- `pytest packages/ai-parrot-server/tests/scheduler/test_headless.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/scheduler/test_base_lifecycle.py
async def test_init_registers_manager_and_service_resolver(scheduler_namespace): ...
async def test_redis_jobstore_keys_namespaced(scheduler_namespace, scheduler_redis, monkeypatch): ...
async def test_coordinator_forced_redis_with_jobstore(scheduler_namespace, scheduler_redis, monkeypatch): ...
async def test_run_state_for_backends(scheduler_namespace, scheduler_redis, monkeypatch): ...
async def test_stop_headless_tolerates_no_start(scheduler_namespace): ...
def test_setup_registers_routes(scheduler_namespace): ...
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
   `feat(scheduler-manager-base): TASK-4155 — SchedulerManager lifecycle: init, namespaced jobstores, coordinator, run-state stores, headless and aiohttp startup`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4155 scheduler-manager-base verified` (never move the file by hand)
10. **Fill in the Completion Note** below, then commit the staged SDD state: `sdd: complete TASK-4155 — SchedulerManager lifecycle: init, namespaced jobstores, coordinator, run-state stores, headless and aiohttp startup`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

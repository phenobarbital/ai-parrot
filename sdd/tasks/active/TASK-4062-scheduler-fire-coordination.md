# TASK-4062: Per-fire coordination (Redis claim, run-now guard, coordinated executor)

**Feature**: FEAT-631 — Scheduler multi-worker correctness
**Spec**: `sdd/specs/scheduler-multiworker-correctness.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 / Goals G2, G5, G6. Each gunicorn worker runs its own `AsyncIOScheduler`, so every fire runs N times. This task
builds a cross-worker claim keyed by `(job_id, scheduled run time)` and applies it inside an `AsyncIOExecutor` subclass, the
only APScheduler 3.x hook that sees the scheduled run time. It also adds a cross-worker run-now guard. Wiring into the manager
happens in TASK-4064/4065.

---

## Scope

- Create `parrot/scheduler/coordination.py` with `FireCoordinationError`, `FireCoordinator` (Protocol), `NullFireCoordinator`,
  `RedisFireCoordinator`, `build_fire_coordinator`, `CoordinatedAsyncIOExecutor`.
- Config via navconfig: `SCHEDULER_COORDINATION` (`redis`|`none`), `SCHEDULER_FIRE_LOCK_TTL` (default 86400),
  `SCHEDULER_RUN_NOW_LOCK_TTL` (default 3600).
- Write `tests/scheduler/test_coordination.py`, including the apscheduler signature guard.

**NOT in scope**: touching `manager.py`; the DB `lock_unavailable` stamp (the executor only invokes the `on_unavailable`
callback; TASK-4065 implements the callback); adding `fakeredis` as a dependency (tests use a dict-backed fake).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/coordination.py` | CREATE | coordinators + executor |
| `packages/ai-parrot-server/tests/scheduler/test_coordination.py` | CREATE | unit tests + signature guard |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import redis.asyncio as aioredis                                   # verified: parrot/autonomous/redis_jobs.py:6
from apscheduler.executors.asyncio import AsyncIOExecutor          # verified: scheduler/manager.py:28
from apscheduler.executors.base import run_coroutine_job           # verified: apscheduler 3.11.2 executors/base.py:161
from apscheduler.util import iscoroutinefunction_partial           # verified: apscheduler 3.11.2 util.py:468
from parrot.conf import CACHE_HOST, CACHE_PORT                     # verified: scheduler/manager.py:41
from parrot.scheduler.sanitize import (                            # verified: sanitize.py:236 (sanitize_redis_settings), :88 (DEFAULT_REDIS_JOBSTORE_DB); SchedulerConfigError imported at manager.py:43-52
    DEFAULT_REDIS_JOBSTORE_DB, SchedulerConfigError, sanitize_redis_settings,
)
from navconfig import config as nav_config                         # verified: scheduler/manager.py:299 (local-import idiom)
```

### Existing Signatures to Use
```python
# apscheduler 3.11.2 executors/asyncio.py:31 — the method being overridden (verbatim behaviour to preserve for the "won" path)
def _do_submit_job(self, job, run_times):
    def callback(f):
        self._pending_futures.discard(f)
        try:
            events = f.result()
        except BaseException:
            self._run_job_error(job.id, *sys.exc_info()[1:])
        else:
            self._run_job_success(job.id, events)
    if iscoroutinefunction_partial(job.func):
        coro = run_coroutine_job(job, job._jobstore_alias, run_times, self._logger.name)
        f = self._eventloop.create_task(coro)
    else:
        f = self._eventloop.run_in_executor(None, run_job, job, job._jobstore_alias, run_times, self._logger.name)
    f.add_done_callback(callback)
    self._pending_futures.add(f)
# executors/base.py:81  def _run_job_success(self, job_id, events)  — events == [] dispatches nothing, still decrements _instances
# sanitize.py:236  def sanitize_redis_settings(host, port, db=DEFAULT_REDIS_JOBSTORE_DB) -> {"host": str, "port": int, "db": int}
# Redis SET NX EX idiom: ai-parrot-integrations/.../slack/dedup.py:168  await self._redis.set(key, "1", nx=True, ex=self._ttl)
```

### Does NOT Exist
- ~~APScheduler passing the scheduled run time into the job coroutine~~: only the executor receives `run_times`.
- ~~`SCHEDULER_COORDINATION` in `parrot/conf.py`~~: read it with navconfig inside `coordination.py`. Do not edit `parrot/conf.py`.
- ~~`fakeredis` in the venv~~: not installed; do not add it. Use a dict-backed async fake in the tests.
- ~~`parrot.scheduler.coordination`~~: this task creates it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/scheduler/coordination.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/scheduler/test_coordination.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/sanitize.py#sanitize_redis_settings",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/sanitize.py#SchedulerConfigError"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write the coordinator classes. *Why*: the protocol is what TASK-4064/4065 program against.
2. Write `build_fire_coordinator`. Precedence: explicit `mode` > `SCHEDULER_COORDINATION` > (`"redis"` if `use_redis` else
   `"none"`). Unknown values raise `SchedulerConfigError`. *Why*: AC7; never coerce silently.
3. Write `CoordinatedAsyncIOExecutor._do_submit_job`. Copy the base method's structure and replace only the coroutine with a
   wrapper. *Why*: the "won" path must behave exactly like stock APScheduler, so listeners fire once (AC2).
4. Write the tests, including the signature guard. *Why*: the hook is a private API (spec §7 risk).

### `packages/ai-parrot-server/src/parrot/scheduler/coordination.py` (CREATE), part 1: coordinators
```python
"""Cross-worker fire coordination for the agent scheduler (FEAT-631)."""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
import uuid
from datetime import datetime
from typing import Awaitable, Callable, Optional, Protocol, Set, runtime_checkable

import redis.asyncio as aioredis
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.executors.base import run_coroutine_job
from apscheduler.util import iscoroutinefunction_partial

from parrot.conf import CACHE_HOST, CACHE_PORT
from .sanitize import DEFAULT_REDIS_JOBSTORE_DB, SchedulerConfigError, sanitize_redis_settings

logger = logging.getLogger("Parrot.Scheduler.coordination")

DEFAULT_PREFIX = "parrot:scheduler:"
DEFAULT_FIRE_TTL = 86400
DEFAULT_RUN_NOW_TTL = 3600


class FireCoordinationError(Exception):
    """The coordination backend could not answer. Callers MUST fail closed (skip the fire)."""


@runtime_checkable
class FireCoordinator(Protocol):
    worker_id: str

    async def claim(self, job_id: str, run_time: datetime) -> bool: ...
    async def try_acquire_running(self, schedule_id: str) -> bool: ...
    async def release_running(self, schedule_id: str) -> None: ...
    async def close(self) -> None: ...


def _default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class NullFireCoordinator:
    """Single-process coordinator: every claim wins; the run-now guard is an in-process set."""

    def __init__(self, worker_id: Optional[str] = None) -> None:
        self.worker_id = worker_id or _default_worker_id()
        self._running: Set[str] = set()

    async def claim(self, job_id: str, run_time: datetime) -> bool:
        return True

    async def try_acquire_running(self, schedule_id: str) -> bool:
        # FILL IN: False if already in self._running, else add and return True — bounded by AC4 (single-process 409)

    async def release_running(self, schedule_id: str) -> None:
        self._running.discard(str(schedule_id))

    async def close(self) -> None:
        return None


class RedisFireCoordinator:
    """Claims ``{prefix}fire:{job_id}:{run_time.isoformat()}`` and guards ``{prefix}running:{schedule_id}`` with SET NX EX."""

    def __init__(self, client: "aioredis.Redis", *, worker_id: Optional[str] = None,
                 fire_ttl: int = DEFAULT_FIRE_TTL, run_now_ttl: int = DEFAULT_RUN_NOW_TTL,
                 prefix: str = DEFAULT_PREFIX) -> None:
        self._client = client
        self.worker_id = worker_id or _default_worker_id()
        self._fire_ttl = int(fire_ttl)
        self._run_now_ttl = int(run_now_ttl)
        self._prefix = prefix

    async def claim(self, job_id: str, run_time: datetime) -> bool:
        key = f"{self._prefix}fire:{job_id}:{run_time.isoformat()}"
        # FILL IN: `await self._client.set(key, self.worker_id, nx=True, ex=self._fire_ttl)` → bool(result);
        #          wrap ANY exception as FireCoordinationError(...) from exc — bounded by G5 (fail closed) + test_claim_redis_error_raises_coordination_error

    async def try_acquire_running(self, schedule_id: str) -> bool:
        # FILL IN: same SET NX EX on f"{self._prefix}running:{schedule_id}" with run_now_ttl; errors → FireCoordinationError — bounded by AC4

    async def release_running(self, schedule_id: str) -> None:
        # FILL IN: `await self._client.delete(key)`; log (warning) and swallow any exception — never raises (spec §3 M2 skeleton)

    async def close(self) -> None:
        # FILL IN: `await self._client.aclose()` if present else `close()`; suppress exceptions
```

### `coordination.py` (CREATE), part 2: factory + executor
```python
def build_fire_coordinator(mode: Optional[str] = None, *, use_redis: bool = False) -> FireCoordinator:
    """Resolve and build the coordinator: explicit ``mode`` > ``SCHEDULER_COORDINATION`` > (redis if use_redis else none).

    Raises:
        SchedulerConfigError: unknown mode value.
    """
    from navconfig import config as nav_config  # local import — same idiom as manager.py:299

    # FILL IN: resolve raw = mode or nav_config.get("SCHEDULER_COORDINATION") or ("redis" if use_redis else "none");
    #          normalize with str(raw).strip().lower(); "none" → NullFireCoordinator();
    #          "redis" → RedisFireCoordinator(aioredis.Redis(**sanitize_redis_settings(host=CACHE_HOST, port=CACHE_PORT,
    #          db=DEFAULT_REDIS_JOBSTORE_DB)), fire_ttl=<SCHEDULER_FIRE_LOCK_TTL or default>, run_now_ttl=<SCHEDULER_RUN_NOW_LOCK_TTL or default>);
    #          anything else → raise SchedulerConfigError(f"Unknown SCHEDULER_COORDINATION {raw!r}; expected 'redis' or 'none'")
    #          — bounded by AC7 (never coerce)


UnavailableHook = Callable[[str, BaseException], Awaitable[None]]


class CoordinatedAsyncIOExecutor(AsyncIOExecutor):
    """AsyncIOExecutor whose coroutine jobs first claim ``(job.id, run_times[-1])``."""

    def __init__(self, coordinator: Optional[FireCoordinator] = None,
                 on_unavailable: Optional[UnavailableHook] = None) -> None:
        super().__init__()
        self._coordinator: FireCoordinator = coordinator or NullFireCoordinator()
        self._on_unavailable = on_unavailable

    def set_coordinator(self, coordinator: FireCoordinator) -> None:
        """Swap the coordinator (start_headless builds it after __init__)."""
        self._coordinator = coordinator

    async def _claimed_run(self, job, run_times):
        try:
            won = await self._coordinator.claim(job.id, run_times[-1])
        except FireCoordinationError as exc:
            logger.error("Scheduler coordination unavailable for job %s: %s — skipping fire (fail closed)", job.id, exc)
            # FILL IN: if self._on_unavailable: await it(job.id, exc) inside try/except that logs and swallows — bounded by G5
            return []
        if not won:
            logger.debug("Job %s @ %s claimed by another worker; skipping", job.id, run_times[-1])
            return []
        return await run_coroutine_job(job, job._jobstore_alias, run_times, self._logger.name)

    def _do_submit_job(self, job, run_times):
        if not iscoroutinefunction_partial(job.func):
            return super()._do_submit_job(job, run_times)

        def callback(f):
            self._pending_futures.discard(f)
            try:
                events = f.result()
            except BaseException:
                self._run_job_error(job.id, *sys.exc_info()[1:])
            else:
                self._run_job_success(job.id, events)

        f = self._eventloop.create_task(self._claimed_run(job, run_times))
        f.add_done_callback(callback)
        self._pending_futures.add(f)
```
**Why this shape**: the "won" path is byte-for-byte the stock coroutine path (verified `executors/asyncio.py:31`). Lost and
unavailable return `[]`, which `_run_job_success` turns into "dispatch nothing", so no `EVENT_JOB_EXECUTED`, no listener and
no DB stamp (AC2, AC6). Sync jobs are untouched: every scheduler job in this feature is a coroutine.

### `packages/ai-parrot-server/tests/scheduler/test_coordination.py` (CREATE)
```python
"""Tests for parrot.scheduler.coordination (FEAT-631 TASK-4062)."""
import inspect
from datetime import datetime, timezone

import pytest
from apscheduler.executors.asyncio import AsyncIOExecutor

from parrot.scheduler import coordination as coord
from parrot.scheduler.sanitize import SchedulerConfigError


class FakeRedis:
    """Dict-backed async double for SET NX EX / DELETE; set raise_on to make every call raise."""

    def __init__(self, raise_on: bool = False):
        self.store: dict = {}
        self.raise_on = raise_on

    async def set(self, key, value, nx=False, ex=None):
        if self.raise_on:
            raise ConnectionError("redis down")
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)

    async def aclose(self):
        return None


def test_executor_hook_signature_guard():
    params = list(inspect.signature(AsyncIOExecutor._do_submit_job).parameters)
    assert params == ["self", "job", "run_times"], "apscheduler executor internals changed — revisit FEAT-631 coordination"

# FILL IN: test_claim_once_across_two_coordinators (shared FakeRedis, distinct worker_id; same key once, new run_time claimable)
# FILL IN: test_claim_redis_error_raises_coordination_error
# FILL IN: test_run_now_guard_cross_worker (second try_acquire_running False; release then True)
# FILL IN: test_null_coordinator_guard
# FILL IN: test_build_fire_coordinator_modes (monkeypatch navconfig get; explicit > env > use_redis; "bogus" → SchedulerConfigError;
#          for "redis" monkeypatch coord.aioredis.Redis to a FakeRedis factory so no socket is opened)
# FILL IN: test_executor_lost_claim_dispatches_nothing / test_executor_unavailable_fails_closed — build a real AsyncIOScheduler with
#          CoordinatedAsyncIOExecutor, add an IntervalTrigger coroutine job, record EVENT_JOB_EXECUTED via add_listener,
#          call executor._claimed_run directly OR drive one submit; assert job coroutine not awaited and no event; on_unavailable awaited once
```

### FILL IN checklist
- [ ] `NullFireCoordinator.try_acquire_running`; bounded by AC4
- [ ] `RedisFireCoordinator.claim` / `try_acquire_running` / `release_running` / `close`; bounded by G5 and the skeleton
- [ ] `build_fire_coordinator` resolution and errors; bounded by AC7
- [ ] `_claimed_run` `on_unavailable` call; bounded by G5
- [ ] The 7 tests listed; bounded by spec §4 M2 rows

---

## Acceptance Criteria

- [ ] Two `RedisFireCoordinator`s over one fake client: exactly one wins `(job_id, run_time)` (AC2 building block).
- [ ] A Redis error surfaces as `FireCoordinationError`; the executor then runs nothing and dispatches no event (AC6 building block).
- [ ] `build_fire_coordinator("bogus")` raises `SchedulerConfigError` (AC7).
- [ ] The signature guard test exists and passes on apscheduler 3.11.2.
- [ ] `ruff check` is clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/scheduler/test_coordination.py -q`

---

## Test Specification

See the `test_coordination.py` block above.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug scheduler-multiworker-correctness --feature-id FEAT-631 --spec sdd/specs/scheduler-multiworker-correctness.spec.md --index sdd/tasks/index/scheduler-multiworker-correctness.json`).
2. Verify the Codebase Contract; set this task `in-progress` in the index; commit the index.
3. Implement and complete the `# FILL IN:` markers. Validate with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src`.
4. Commit only the listed files: `feat(scheduler-multiworker-correctness): TASK-4062 — fire coordination`.
5. Run `scripts/sdd/close_task.sh TASK-4062 scheduler-multiworker-correctness verified`, fill in the Completion Note, commit, and push.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

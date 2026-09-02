# TASK-2760: WorkerPool — readiness-gated spares + restart-loop visibility

**Feature**: FEAT-500 — REPL Worker Readiness Handshake & Non-Lethal Namespace Timeouts
**Spec**: `sdd/specs/bug-workerpool-repl.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2759
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. `WorkerPool._top_up_prewarmed()` appends a spare and logs
`prewarmed worker ready` the instant `handle.start()` returns
(`pool.py:166-187`), and `acquire()` binds the oldest spare on crash-restart
with `is_alive` as the only health signal (`pool.py:231-268`) — the pool
half of the death spiral (spec §1). With TASK-2759's `wait_ready()` in
place, this task makes "prewarmed" mean *ready*, and makes a restart loop
visible in the logs (spec G5/AC8).

---

## Scope

- `_top_up_prewarmed()`: after `handle = await self._spawn_handle()`,
  `await handle.wait_ready()` **outside** `self._lock`. On
  `WorkerBootstrapError` → `logger.exception("WorkerPool: prewarmed worker failed to become ready")`,
  `await handle.kill()` (idempotent), and `return` (same shape as the
  existing spawn-failure branch at `pool.py:170-172`). Only after readiness:
  append under the lock and log
  `"WorkerPool: prewarmed worker ready (pid=%s, bootstrap_ms=%d, pool size=%d)"`.
  Keep the post-spawn `_started` re-check (`pool.py:173-186`) — apply it
  after `wait_ready()` too.
- `acquire()`: keep the binding logic. Add `self._restarts: dict[str, list[float]]`
  (init in `__init__`). In the `worker is dead, restarting` branch
  (`pool.py:241-243`): record `time.monotonic()`, prune entries older than
  60 s, and if `len(...) >= 3` emit
  `logger.warning("WorkerPool: session %r restarted %d times in the last 60s — possible restart loop (last worker exit code=%s, stderr tail=%r)", ...)`
  using `existing._proc.returncode` (may be `None`) and the last line of
  `existing._stderr_tail` (may be empty). Keep the existing warning line
  unchanged so log greps still work.
- `def restart_count(self, session_id: str) -> int` — length of the pruned
  list (0 if unknown). `release()`/`_evict_idle()`/`shutdown()` clear the
  session's entry when they unmap it.
- Tests in `tests/repl_worker/test_pool.py`.

**NOT in scope**: changing FIFO spare selection (spec §8 Q3, deferred),
handle internals (TASK-2759), tool layer (TASK-2761).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/pool.py` | MODIFY | readiness gate in top-up; restart counter + warning; `restart_count()` |
| `packages/ai-parrot/tests/repl_worker/test_pool.py` | MODIFY | spare-not-ready-until-frame + restart-loop tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .handle import WorkerHandle                      # pool.py:38
from .protocol import WorkerConfig                    # pool.py:39
from .handle import WorkerBootstrapError              # add — created by TASK-2759
# pool.py already imports asyncio, concurrent.futures, contextlib, logging, os, time (pool.py:30-36)
# tests: from parrot.tools.repl_worker import WorkerPool, WorkerConfig, WorkerHandle   (repl_worker/__init__.py:14-16)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/repl_worker/pool.py
class WorkerPool:                                                      # :58
    def __init__(self, config=None, output_dir=None, repl_kwargs=None, executor=None)   # :61-110
        self._sessions: dict[str, WorkerHandle] = {}; self._last_active: dict[str, float] = {}; self._prewarmed: list[WorkerHandle] = []   # :93-95
        self._lock = asyncio.Lock(); self._topup_lock = asyncio.Lock()  # :97, :103
        self._background_tasks: set[asyncio.Task]; self._maintenance_task; self._started = False   # :108-110
    async def _spawn_handle(self) -> WorkerHandle                       # :140-145  WorkerHandle(...); await handle.start(); return handle
    async def _top_up_prewarmed(self) -> None                          # :147-187
        # :156-158 single-flight via _topup_lock; :160-165 ceiling check under _lock; :166-172 spawn (exception → logger.exception + return)
        # :173-186 post-spawn _started re-check (kill if shutdown ran); :187 logger.debug("WorkerPool: prewarmed worker ready (pool size=%d)", ...)
    async def _evict_idle(self) -> None                                 # :199-212  pops session under _lock, kills outside
    async def acquire(self, session_id: str) -> WorkerHandle           # :214-276
        # :231-243 existing-session branch: :234 if existing.is_alive → return; :241 logger.warning("WorkerPool: session %r worker is dead, restarting", session_id); :242-243 pop session/_last_active
        # :255-261 ceiling check; :263-268 bind spare (pop(0), debug :265) or spawn fresh (:267-268); :270-271 map; :275 self._track_background(self._top_up_prewarmed())
    async def release(self, session_id: str) -> None                   # :278-286
    async def shutdown(self) -> None                                   # :288-326  sets _started=False first; cancels tasks; kills all handles

# packages/ai-parrot/src/parrot/tools/repl_worker/handle.py (after TASK-2759)
class WorkerHandle:
    async def wait_ready(self, timeout_s: float | None = None) -> ReadyResponse   # NEW (TASK-2759) — raises WorkerBootstrapError
    @property def is_ready(self) -> bool                                # NEW (TASK-2759)
    self._proc: Optional[subprocess.Popen]  (returncode via _proc.returncode / poll())   # :110
    self._stderr_tail: list[str]                                        # :144
    async def kill(self) -> None                                        # :451-486 idempotent

# packages/ai-parrot/tests/repl_worker/test_pool.py
fixture worker_config -> WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=5, prewarm_pool_size=0)   # :21-25
class TestWorkerPool :28 — prewarm case builds WorkerConfig(..., prewarm_pool_size=1) at :84; orphan reaping test :123-144
```

### Does NOT Exist
- ~~`WorkerPool.restart_count` / `_restarts`~~ — you create them.
- ~~any readiness check in the pool today~~ — none; `is_alive` (`proc.poll()`) is the only signal.
- ~~`WorkerPool.ping_all()` / health sweep in `_maintenance_loop`~~ — none; do not add one (spec Non-Goals).
- ~~a "readiest spare first" policy~~ — deferred (spec §8 Q3); keep `pop(0)`.
- ~~`WorkerHandle.exit_code`~~ — use `handle._proc.returncode` / `poll()`; there is no public accessor (adding a small `exit_code` property to the handle is acceptable if you prefer — document it in the completion note).

---

## Implementation Notes

### Pattern to Follow
```python
# pool.py:166-187 (today) — insert the readiness await between spawn and append, keeping the _started re-check
try:
    handle = await self._spawn_handle()
    await handle.wait_ready()                    # NEW — outside self._lock
except asyncio.CancelledError:
    raise
except WorkerBootstrapError:
    logger.exception("WorkerPool: prewarmed worker failed to become ready")
    return
except Exception:
    logger.exception("WorkerPool: failed to spawn a prewarmed worker")
    return
async with self._lock:
    ...existing _started re-check, append...
logger.debug("WorkerPool: prewarmed worker ready (pid=%s, bootstrap_ms=%d, pool size=%d)", ...)
```

### Key Constraints
- Never `await wait_ready()` while holding `self._lock` — it can take up to `bootstrap_timeout_ms` and would block every other session's `acquire()`.
- The fresh-spawn path in `acquire()` (`pool.py:267-268`) runs under `self._lock`; do NOT add a readiness await there — the handle's first `_send()` awaits readiness on its own (TASK-2759).
- `shutdown()` cancels background top-ups (`pool.py:313-317`); a cancelled top-up mid-`wait_ready()` must not leak the worker — the existing `_started` re-check plus `handle.kill()` in the bootstrap-failure branch cover it; add a test if you touch that path.
- Log messages: keep `worker is dead, restarting` verbatim (external log greps rely on it).

### References in Codebase
- `pool.py:147-187` — top-up (modify)
- `pool.py:214-276` — acquire (add counter)
- `test_pool.py:84-121` — existing prewarm test (extend)

---

## Acceptance Criteria

- [ ] With `prewarm_pool_size=1` and a slow `setup_code` (sleep 3 s): `pool._prewarmed` is empty while the worker boots and contains one **ready** handle afterwards; caplog shows `prewarmed worker ready` only after the ready frame
- [ ] A spare whose bootstrap fails (tiny `bootstrap_timeout_ms`) is never appended and is not alive afterwards
- [ ] Killing a session's worker externally three times within 60 s and re-acquiring each time → `restart_count(session) == 3` and exactly one `possible restart loop` warning in caplog
- [ ] Existing `TestWorkerPool` tests (TTL eviction, ceiling, crash restart, orphan reaping) pass unchanged in outcome
- [ ] `pytest packages/ai-parrot/tests/repl_worker/test_pool.py -v` passes; `ruff check` clean
- [ ] Spec AC1 (pool half), AC8, AC12 (pool half)

---

## Test Specification

```python
# packages/ai-parrot/tests/repl_worker/test_pool.py (additions)
import asyncio, logging, pytest
from parrot.tools.repl_worker import WorkerPool, WorkerConfig

SLOW = {"setup_code": "import time\ntime.sleep(3)"}

class TestReadinessGate:
    async def test_spare_not_ready_until_ready_frame(self, tmp_path, caplog):
        caplog.set_level(logging.DEBUG, logger="parrot.tools.repl_worker.pool")
        cfg = WorkerConfig(deadline_ms=5_000, max_workers=2, idle_ttl_seconds=30, prewarm_pool_size=1)
        pool = WorkerPool(cfg, output_dir=str(tmp_path), repl_kwargs=SLOW)
        try:
            await pool._ensure_started()
            await asyncio.sleep(0.5)
            assert pool._prewarmed == []                       # still booting
            for _ in range(80):                                # ≤ 8 s
                await asyncio.sleep(0.1)
                if pool._prewarmed:
                    break
            assert len(pool._prewarmed) == 1 and pool._prewarmed[0].is_ready
            assert "prewarmed worker ready" in caplog.text
        finally:
            await pool.shutdown()

class TestRestartLoopVisibility:
    async def test_restart_loop_warning(self, worker_config, tmp_path, caplog):
        caplog.set_level(logging.WARNING, logger="parrot.tools.repl_worker.pool")
        pool = WorkerPool(worker_config, output_dir=str(tmp_path))
        try:
            for _ in range(3):
                h = await pool.acquire("s1")
                await h.wait_ready()
                await h.kill()                                 # external death
            await pool.acquire("s1")
            assert pool.restart_count("s1") == 3
            assert caplog.text.count("possible restart loop") == 1
        finally:
            await pool.shutdown()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2759 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-read `pool.py` and the new `wait_ready()` in `handle.py` before editing
4. **Update status** in `sdd/tasks/index/bug-workerpool-repl.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met (run all of `tests/repl_worker/`)
7. **Move this file** to `sdd/tasks/completed/TASK-2760-pool-readiness-gated-spares.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 5)
**Date**: 2026-09-02
**Notes**:
- `pool.py` imports `WorkerBootstrapError` alongside `WorkerHandle`. Two module
  constants added next to `_CEILING_CAP`: `_RESTART_WINDOW_S = 60.0` and
  `_RESTART_LOOP_THRESHOLD = 3` (the 60 s / 3 restarts from the spec, named
  rather than inlined).
- `_top_up_prewarmed()`: `ready = await handle.wait_ready()` immediately after
  `_spawn_handle()`, still OUTSIDE `self._lock`. New
  `except WorkerBootstrapError` branch -> `logger.exception("WorkerPool:
  prewarmed worker failed to become ready")`, `await handle.kill()`, `return`;
  the generic `except Exception` spawn-failure branch and the
  `asyncio.CancelledError` re-raise are untouched, as is the post-spawn
  `_started` re-check (it now runs after readiness too, so a spare that boots
  during `shutdown()` is still killed rather than resurrected). The success log
  became `"WorkerPool: prewarmed worker ready (pid=%s, bootstrap_ms=%d, pool
  size=%d)"`, fed by the `ReadyResponse` that `wait_ready()` returns.
- `acquire()`: binding logic, FIFO `pop(0)` and the verbatim
  `"WorkerPool: session %r worker is dead, restarting"` line are all unchanged
  (external log greps keep working). One call added right after that warning:
  `self._record_restart(session_id, existing)`. No readiness await was added to
  the fresh-spawn path — the handle's own first `_send()` covers it.
- New `_record_restart(session_id, dead)` (private, called under `self._lock`):
  prunes the session's timestamps to the 60 s window, appends `time.monotonic()`,
  and at >= 3 logs `logger.warning("WorkerPool: session %r restarted %d times in
  the last %ds — possible restart loop (last worker exit code=%s, stderr
  tail=%r)")` using `dead._proc.returncode` and the last `_stderr_tail` line.
- New public `restart_count(session_id) -> int` — prunes, then reports; `0` for
  an unknown session.
- Counter cleanup: `_evict_idle()` and `shutdown()` drop the session's restart
  history when they unmap it. `release()` deliberately does NOT — reading it
  showed it only resets the TTL clock and never unmaps the session, so clearing
  there would erase a live session's history.
- Per the task's explicit allowance, no `WorkerHandle.exit_code` property was
  added; `_record_restart` reads `handle._proc.returncode` directly (the pool
  already reaches into `handle` internals elsewhere).
- Tests (`test_pool.py`, +4, 11 total, all passing):
  `TestReadinessGate::test_pool_spare_not_ready_until_ready_frame` (asserts both
  that `_prewarmed` is empty AND that "prewarmed worker ready" has not been
  logged at 0.5 s — the actual regression), plus
  `test_pool_spare_failing_bootstrap_is_never_appended`;
  `TestRestartLoopVisibility::test_pool_restart_loop_warning` (3 external kills
  -> `restart_count == 3`, exactly one warning) and
  `test_restart_count_unknown_session_is_zero`.
  Note: the task's sketch killed the worker 3x and re-acquired once at the end,
  which only registers ONE restart (the pool must observe each death via an
  `acquire()`); the test re-acquires inside the loop so all three deaths are
  counted, as AC8 requires.
- Verification: `pytest .../test_pool.py` -> 11 passed; whole
  `tests/repl_worker/` -> 96 passed, 1 failed. The failure is the same
  pre-existing `test_e2e_data_analysis_session` matplotlib/`plt` environment
  issue documented in TASK-2759 (3 failures in that file at baseline, 1 now).
  `ruff check` on both changed files: findings identical to baseline (verified
  via `git stash`).

**Deviations from spec**: none (the restart-loop test's acquire placement is a
correction to the task's illustrative snippet, not a behaviour change).

# TASK-1942: WorkerPool — prewarm, TTL, ceiling, crash restart, orphan reaping

**Feature**: FEAT-380 — Sandbox Hardening — PythonREPLTool a worker persistente
**Spec**: `sdd/specs/sandbox-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1941
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 — worker lifecycle management on top of `WorkerHandle`:
lazy start, a prewarmed pool (v1, G4/AC10) so the first call of a session
does not pay the 1–3 s pandas import, idle-TTL eviction, a hard concurrency
ceiling with immediate rejection (no unbounded queueing), restart on crash
with the namespace-loss error, and orphan reaping (`PR_SET_PDEATHSIG` on
Linux + shutdown sweep as portable backstop) — AC12.

---

## Scope

- Create `packages/ai-parrot/src/parrot/tools/repl_worker/pool.py` with:

  ```python
  class WorkerPool:
      async def acquire(self, session_id: str) -> WorkerHandle: ...
      async def release(self, session_id: str) -> None: ...
      async def shutdown(self) -> None: ...
  ```

- **Session mapping**: one worker per `session_id` (G7). `acquire` returns
  the session's live worker, or binds a prewarmed one, or spawns lazily.
- **Prewarm pool (v1)**: `WorkerConfig.prewarm_pool_size` workers started in
  the background with libraries already imported; assignment on demand;
  background top-up after one is claimed.
- **Ceiling**: effective max = `max_workers` if > 0 else
  `max(4, os.cpu_count())`, capped at 16. At the ceiling, `acquire` **raises
  immediately** with a clear, catchable error (define
  `WorkerPoolExhaustedError` in the package) — never queues indefinitely.
- **Idle TTL**: workers idle longer than `idle_ttl_seconds` (default 1800)
  are killed and unmapped; a later `acquire` for that session spawns fresh
  (namespace intentionally gone — the session went idle).
- **Crash restart**: if a session's worker is found dead (crash/OOM/kill),
  spawn a replacement and surface the namespace-loss error (cause=`crash`
  unless the handle recorded a more specific cause) for the interrupted call.
- **Orphan reaping**: set `PR_SET_PDEATHSIG` (SIGKILL) on Linux children;
  `shutdown()` kills every worker and prewarmed spare — host shutdown leaves
  zero live workers on any platform.
- Config plumbed from `WorkerConfig` (deployment-tunable, working defaults).
- Unit tests: ceiling rejection, TTL eviction, prewarm assignment, crash
  restart, orphan reaping.

**NOT in scope**: changes to `pythonrepl.py` (TASK-1943); protocol or worker
entrypoint changes (TASK-1940) beyond adding the `PR_SET_PDEATHSIG` startup
flag if it must live child-side; DataFrame transport (TASK-1945).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/pool.py` | CREATE | `WorkerPool` + `WorkerPoolExhaustedError` |
| `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py` | MODIFY | Only if PDEATHSIG must be set child-side (prctl at startup) |
| `packages/ai-parrot/tests/repl_worker/test_pool.py` | CREATE | Ceiling/TTL/prewarm/crash/orphan tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` HEAD on 2026-07-27.

### Verified Imports

```python
# From TASK-1940/1941 (verify actual exported names before importing):
from parrot.tools.repl_worker.protocol import WorkerConfig, NamespaceLossError
from parrot.tools.repl_worker.handle import WorkerHandle
```

### Existing Signatures to Use

```python
# spec §2 — WorkerConfig fields this task consumes (frozen):
max_workers: int = 0            # 0 → max(4, cpu_count), cap 16
idle_ttl_seconds: int = 1800
prewarm_pool_size: int = 2
```

```python
# PR_SET_PDEATHSIG — Linux-only, via ctypes or the child's own startup:
# import ctypes; libc = ctypes.CDLL("libc.so.6", use_errno=True)
# PR_SET_PDEATHSIG = 1; libc.prctl(1, signal.SIGKILL)
# Must run IN THE CHILD (prctl applies to the calling process).
```

### Does NOT Exist

- ~~A session registry / session concept in `PythonREPLTool`~~ — sessions
  exist only here, keyed by the `session_id` string the caller provides.
- ~~A third-party process-pool dependency~~ — stdlib only
  (`asyncio`, `os`, `signal`, `ctypes` for prctl).
- ~~`PR_SET_PDEATHSIG` on macOS/Windows~~ — Linux-only; elsewhere rely on
  the shutdown sweep (that is the "portable backstop" in the spec).
- ~~Queueing at the ceiling~~ — explicitly rejected in brainstorm: reject
  immediately with a clear error.

---

## Implementation Notes

### Key Constraints

- Async-first: eviction/top-up via a background `asyncio.Task` owned by the
  pool; make `shutdown()` cancel it deterministically (no orphan tasks in
  tests).
- Prewarmed workers are **not** bound to any session until claimed — their
  bootstrap must not depend on session state.
- TTL clock = time since last completed operation on that worker; store the
  timestamp on release/completion, not on acquire.
- `WorkerPoolExhaustedError` message must state current ceiling and suggest
  raising `max_workers` — this surfaces to operators (AC12 "error claro").
- Use `self.logger` for lifecycle events (spawn, evict, restart, reap) —
  these are the observability surface of the whole feature.
- Tests must use tiny configs (`worker_config` fixture from spec §4:
  `idle_ttl_seconds=5`, `prewarm_pool_size=0` except in the prewarm test) so
  the suite stays fast.

### References in Codebase

- `parrot/tools/repl_worker/handle.py` (TASK-1941) — spawn/kill/health API.

---

## Acceptance Criteria

- [ ] Ceiling reached → immediate `WorkerPoolExhaustedError`, no queueing
      (`test_pool_ceiling_rejects`) — AC12.
- [ ] Worker idle > TTL → evicted (`test_pool_ttl_eviction`) — AC12.
- [ ] Prewarmed worker assigned without paying the pandas import
      (`test_pool_prewarm`: first exec completes in ms, not seconds) — AC10.
- [ ] Dead worker → restart + namespace-loss error (`test_crash_restart`).
- [ ] `shutdown()` leaves zero live workers, including prewarmed spares
      (`test_orphan_reaping`) — AC12.
- [ ] Two sessions get two distinct workers (`acquire("a") is not acquire("b")`).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/repl_worker/test_pool.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/repl_worker/`

---

## Test Specification

```python
# packages/ai-parrot/tests/repl_worker/test_pool.py
import pytest
from parrot.tools.repl_worker.protocol import WorkerConfig
from parrot.tools.repl_worker.pool import WorkerPool, WorkerPoolExhaustedError

@pytest.fixture
def worker_config():
    return WorkerConfig(rlimit_as_bytes=512 * 1024**2, deadline_ms=2_000,
                        max_workers=2, idle_ttl_seconds=5, prewarm_pool_size=0)


class TestWorkerPool:
    async def test_pool_ceiling_rejects(self, worker_config):
        """3rd concurrent session with max_workers=2 → WorkerPoolExhaustedError immediately."""
        ...

    async def test_pool_ttl_eviction(self, worker_config):
        """Worker idle > 5s TTL is evicted; re-acquire spawns fresh."""
        ...

    async def test_pool_prewarm(self):
        """prewarm_pool_size=1: first exec on a new session is assigned the
        warm worker (no import cost)."""
        ...

    async def test_crash_restart(self, worker_config):
        """Externally-killed worker → next acquire yields a live replacement;
        interrupted call got a namespace-loss error."""
        ...

    async def test_orphan_reaping(self, worker_config):
        """shutdown() → zero child processes remain."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1941 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm handle/protocol exported names
4. **Update status** in `sdd/tasks/index/sandbox-hardening.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1942-repl-worker-pool-lifecycle.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-27
**Notes**:
- `pool.py`: `WorkerPool` + `WorkerPoolExhaustedError`. Session mapping
  (`session_id -> WorkerHandle`), a background `_maintenance_loop()` task
  (TTL sweep, interval `min(5, max(1, idle_ttl_seconds/10))`) and a
  background `_top_up_prewarmed()` task both started lazily and
  non-blockingly from `_ensure_started()` (called at the top of `acquire()`)
  — deliberately fire-and-forget so the FIRST caller into the pool is never
  made to wait for prewarming; later callers benefit once the background
  task has had time to run. Ceiling (`max_workers` or
  `min(max(4, cpu_count()), 16)`) is checked against **sessions +
  prewarmed spares combined** (total live worker processes), raising
  `WorkerPoolExhaustedError` immediately — no queueing. Crash restart: a
  dead session worker is popped and replaced transparently on its next
  `acquire()` (the interrupted call's namespace-loss error was already
  surfaced by `WorkerHandle.execute()` at the time of death; this class
  doesn't re-report it, just makes the session usable again).
  `shutdown()` cancels the maintenance task and kills every bound +
  prewarmed handle — zero live workers survive.
- `worker.py` (MODIFY, as the task scoped): added
  `set_parent_death_signal()` — Linux-only `PR_SET_PDEATHSIG(SIGKILL)` via
  `ctypes`/`libc.prctl`, called first thing in `main()` (before
  `apply_rlimits`/heavy imports). No-op with nothing logged as an error on
  non-Linux platforms (macOS/Windows rely on `shutdown()`'s sweep as the
  documented portable backstop, per scope).
- 7 new tests in `test_pool.py` (ceiling, distinct-session workers,
  same-session reuse, TTL eviction, prewarm timing, crash restart, orphan
  reaping via `shutdown()`), all against real spawned worker subprocesses.
  `pytest packages/ai-parrot/tests/repl_worker/ -q` → 48 passed (protocol +
  worker + handle + pool). `ruff check` on `repl_worker/` is clean.

**Deviations from spec / notable findings**: none beyond the
`rlimit_as_bytes` fixture-value note already on record from TASK-1940/1941
(this task's own `worker_config` fixture again illustrates 512 MiB in the
spec text; tests here use the spec's ~4 GiB *default* instead, since every
pool test spawns real workers that import pandas/numpy/matplotlib).

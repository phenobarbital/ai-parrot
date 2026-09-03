# TASK-2779: Enforce host memory reserve and pressure eviction in WorkerPool

**Feature**: FEAT-521 - REPL Worker Idle/Busy Detection & Memory Guardrails
**Spec**: `sdd/specs/repl-worker-idle-detection-memory-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2774, TASK-2775, TASK-2777, TASK-2778
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 protects the host as a whole by gating new workers, evicting only unbound spares under pressure, and exposing aggregate memory telemetry.

## Scope

- Compute effective host availability from `psutil.virtual_memory().available` and cgroup v2 `memory.max`/`memory.current` when finite and readable.
- Skip prewarm spawning under the configured reserve with a DEBUG log.
- Reject only new-spawn branches of `acquire()` under pressure; existing sessions and already-created spares remain usable.
- Add maintenance-time pressure eviction that kills prewarmed spares before any session and never evicts bound sessions for pressure alone.
- Add `memory_summary()` returning worker count, total observed RSS, and effective host availability.
- Emit aggregate worker RSS at INFO when any worker is over its soft limit.
- Include the observer's memory cause/details in restart-loop visibility.

**NOT in scope**: per-worker sampling/kills, changing the concurrency ceiling, or tests owned by TASK-2782.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/pool.py` | MODIFY | Host reserve checks, spare eviction, summaries, logging |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import psutil
from parrot.tools.repl_worker.handle import WorkerBootstrapError, WorkerHandle
from parrot.tools.repl_worker.protocol import WorkerConfig
```

### Existing Signatures to Use

```python
class WorkerPool:  # pool.py:63
    async def _spawn_handle(self) -> WorkerHandle: ...  # :190
    async def _top_up_prewarmed(self) -> None: ...  # :197
    async def _maintenance_loop(self) -> None: ...  # :286
    async def _evict_idle(self) -> None: ...  # :296
    def _record_restart(self, session_id: str, dead: WorkerHandle) -> None: ...  # :315
    async def acquire(self, session_id: str) -> WorkerHandle: ...  # :367

class WorkerPoolExhaustedError(RuntimeError): ...  # pool.py:55
```

### Does NOT Exist

- ~~`WorkerPool.memory_summary()`~~ and ~~`_evict_under_pressure()`~~ do not exist.
- ~~Cgroup-aware availability helpers~~ do not exist.
- ~~Any `psutil` use in `pool.py`~~ does not exist.
- Pressure eviction of bound sessions is explicitly forbidden.

## Implementation Notes

- Keep reserve checks inside the same locking decisions that choose spare vs spawn to avoid races.
- Treat unreadable, `max`, malformed, or absent cgroup files as unavailable data; fall back safely to psutil.
- Effective cgroup availability is bounded remaining capacity; never report negative bytes.
- Do not block an existing live session or consumption of a prewarmed spare.

## Acceptance Criteria

- [ ] No worker is spawned or prewarmed below the host reserve.
- [ ] `acquire()` raises a clear memory-pressure `WorkerPoolExhaustedError` only when it would spawn.
- [ ] Maintenance kills spares first and never pressure-evicts sessions.
- [ ] `memory_summary()` matches live observer samples and effective host availability.
- [ ] Aggregate INFO and restart WARNING logs carry actionable RSS/memory cause data.
- [ ] Existing ceiling, prewarm, TTL, and shutdown behavior remains intact.

## Test Specification

TASK-2782 owns psutil/cgroup reserve, prewarm, pressure eviction, summary, logging, and restart-cause tests.

## Agent Instructions

Confirm dependencies are completed. Re-read pool locking and post-spawn ceiling recheck paths before adding reserve checks; do not reintroduce oversubscription or shutdown orphan races.

---

## Completion Note

**Completed by**: unassigned
**Date**: pending
**Notes**: pending

**Deviations from spec**: none

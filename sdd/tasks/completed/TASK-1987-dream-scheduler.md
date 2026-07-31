# TASK-1987: DreamScheduler — In-Process Periodic Execution with Catch-Up

**Feature**: FEAT-390 — Dream Cycle — Episodic→Wiki Brain Consolidation
**Spec**: `sdd/specs/dream-cycle-brain-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1986
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. The dream cycle is offline, periodic, and explicit by
design (brainstorm decision), and must survive disconnections: if the server
was down when a cycle was due, the scheduler detects it at startup
(`next_due < now`) and runs a catch-up cycle. State lives in the JSON sidecar
from TASK-1983.

---

## Scope

Implement `parrot/memory/dream/scheduler.py` with class `DreamScheduler`:

- `__init__(self, runner: DreamCycleRunner, state_path: Path,
  interval_hours: float = 24.0, config: DreamConfig | None = None)`.
- `async start(self) -> None`:
  - `load_state(state_path, agent_id)`; sync `interval_hours` into the state.
  - Stale-lock handling: if `state.running` and `state.running_since` older
    than 2× interval → ignore the lock (log WARNING); if fresher → do not
    start a second loop.
  - If `state.next_due` is None (first run) → schedule `next_due = now + interval`.
  - If `state.next_due <= now` → **catch-up**: run one cycle after a random
    jitter of 0–`config.startup_jitter_seconds` (default 60).
  - Spawn the asyncio loop task: sleep until `next_due`, run cycle, persist
    state, reschedule.
- `async stop(self) -> None` — cancel the loop task cleanly; persist state;
  clear `running` flag.
- `async run_now(self) -> DreamCycleReport` — explicit trigger; respects the
  lock (no concurrent cycles); reschedules `next_due = now + interval` after.
- Around every cycle: set `running=True`/`running_since` before, clear after,
  persisting state at both points (crash leaves a detectable stale lock).
- Failure backoff: when the cycle reports `aborted=True` (e.g. wiki store
  down) → `next_due = now + interval / config.failure_backoff_divisor`
  (default: interval/4) instead of the full interval.
- Structured log line per cycle from the `DreamCycleReport`.
- Unit tests in `tests/memory/dream/test_scheduler.py`.

**NOT in scope**: runner internals (TASK-1986), mixin wiring (TASK-1989),
any CLI entry point (explicit non-goal for now).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/dream/scheduler.py` | CREATE | `DreamScheduler` |
| `packages/ai-parrot/src/parrot/memory/dream/__init__.py` | MODIFY | Export `DreamScheduler` |
| `tests/memory/dream/test_scheduler.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.memory.dream import (   # created by TASK-1983/1986
    DreamConfig, DreamCycleReport, DreamCycleRunner, DreamState,
    load_state, save_state,
)
import asyncio, random, logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
```

### Existing Signatures to Use
```python
# parrot/memory/dream/models.py (TASK-1983)
class DreamState(BaseModel):
    agent_id: str
    last_run: datetime | None
    next_due: datetime | None
    interval_hours: float
    running: bool
    running_since: datetime | None
    cycles_completed: int
    ...
def save_state(state: DreamState, path: Path) -> None   # atomic
def load_state(path: Path, agent_id: str) -> DreamState # tolerant

# parrot/memory/dream/runner.py (TASK-1986)
class DreamCycleRunner:
    async def run_cycle(self, state: DreamState) -> DreamCycleReport
    # runner mutates state counters/watermark; scheduler owns persistence
    # + lock flags + next_due.
```

### Does NOT Exist
- ~~cron / external scheduling~~ — in-process asyncio only (brainstorm decision)
- ~~multi-process lock (file locking, Redis lock)~~ — single-process
  assumption; the `running`/`running_since` flag pair is only for
  crash/stale detection, and two live processes on one state file is
  documented-unsupported (spec §7)
- ~~`DreamScheduler.agent_id` param~~ — derive `agent_id` from
  `runner`'s namespace or pass through state; verify what TASK-1986 exposes
  and keep the constructor as specced

---

## Implementation Notes

### Pattern to Follow
Plain asyncio background-task lifecycle:
```python
self._task: asyncio.Task | None = None
async def start(self):
    ...
    self._task = asyncio.create_task(self._loop(), name=f"dream-{agent_id}")
async def stop(self):
    if self._task:
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
```

### Key Constraints
- Never raise out of the loop: wrap each iteration in try/except → WARNING.
- All datetimes timezone-aware UTC.
- Jitter uses `random.uniform(0, jitter)` — acceptable here (tests can patch).
- Make the loop testable: factor `_seconds_until_due(state, now)` and accept
  an injectable `now_fn`/clock or monkeypatchable sleep, so tests don't
  actually sleep.
- Persist state after EVERY mutation that must survive a crash (lock set,
  cycle done, reschedule).

### References in Codebase
- `packages/ai-parrot/src/parrot/memory/unified/manager.py` — logger naming +
  degrade-not-raise style used across the memory stack.

---

## Acceptance Criteria

- [ ] Catch-up: state with `next_due` in the past → cycle runs at `start()`
- [ ] First run: `next_due=None` → scheduled at now + interval, no immediate cycle
- [ ] Stale lock (`running_since` > 2× interval) ignored with WARNING
- [ ] Fresh lock → `run_now()` refuses to run a concurrent cycle
- [ ] Aborted cycle reschedules with interval/4 backoff
- [ ] `stop()` cancels cleanly and persists state
- [ ] All tests pass: `pytest tests/memory/dream/test_scheduler.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/dream/`

---

## Test Specification

```python
# tests/memory/dream/test_scheduler.py
import pytest
from datetime import datetime, timedelta, timezone
from parrot.memory.dream import DreamScheduler, DreamState, save_state


class TestSchedulerStart:
    async def test_catchup_on_overdue_next_due(self, tmp_path, stub_runner):
        state = DreamState(agent_id="a1",
                           next_due=datetime.now(timezone.utc) - timedelta(hours=1))
        save_state(state, tmp_path / "dream_state.json")
        sched = DreamScheduler(stub_runner, tmp_path / "dream_state.json",
                               interval_hours=24)
        await sched.start()   # with jitter patched to 0
        assert stub_runner.cycles_run == 1
        await sched.stop()

    async def test_first_run_schedules_only(self, tmp_path, stub_runner): ...
    async def test_stale_lock_ignored(self, tmp_path, stub_runner): ...


class TestRunNow:
    async def test_explicit_trigger(self, tmp_path, stub_runner): ...
    async def test_lock_prevents_concurrent(self, tmp_path, stub_runner): ...


class TestBackoff:
    async def test_aborted_cycle_backs_off(self, tmp_path, aborting_runner):
        """next_due ≈ now + interval/4 after an aborted report."""
```

`stub_runner`: object with `async run_cycle(state)` incrementing a counter
and returning a success `DreamCycleReport`; `aborting_runner` returns
`aborted=True`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1986 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/dream-cycle-brain-consolidation.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1987-dream-scheduler.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-31
**Notes**: Implemented `DreamScheduler` (`parrot/memory/dream/scheduler.py`)
with the plain-asyncio background-task lifecycle from the Implementation
Notes: `start()` loads state, clears a stale lock (`running_since` > 2x
interval, WARNING logged) or bails out on a fresh lock, schedules
`next_due = now + interval` on first run (no immediate cycle), and runs a
jittered catch-up cycle when `next_due <= now` before spawning the loop
task. `stop()` cancels the task and persists cleared lock state. `run_now()`
loads state on demand, refuses a concurrent run under a fresh lock
(returns an aborted stub report), otherwise delegates to the same
`_run_locked_cycle()` helper `start()`/the loop use — lock set + persisted
before the call, cleared + persisted + rescheduled after. Aborted reports
reschedule at `interval / failure_backoff_divisor` instead of the full
interval. `agent_id` is derived from `runner._namespace.agent_id` (no
public accessor exists on `DreamCycleRunner`, consistent with the
private-reach pattern already used in `runner.py` for
`EpisodicMemoryStore._backend`/`._embedding`). 8 new unit tests pass
(catch-up, first-run-schedules-only, stale-lock-ignored,
fresh-lock-prevents-second-loop, explicit trigger, lock-prevents-concurrent,
backoff, stop persists+clears). Tests use `DreamConfig(startup_jitter_seconds=0)`
instead of monkeypatching `random.uniform` (task note: "tests can patch") —
avoids any real sleep without patching library internals. `ruff check`
clean.

**Deviations from spec**: none.

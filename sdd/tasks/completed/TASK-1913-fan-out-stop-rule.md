# TASK-1913: should_fan_out — deterministic parallelism stop rule

**Feature**: FEAT-377 — Graph Engineering Hardening
**Spec**: `sdd/specs/graphindex-as-engineering-devloop.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1911
**Assigned-to**: unassigned

---

## Context

Module 3 item 3 (spec §3, G4). Whether to use the agent pool at all is
purely config-driven today (`pool_cfg is None` → single-agent). Wave sizing
is already dynamic (`TaskScheduler.next_wave()`), but a configured pool
fans out even when the task graph is a straight chain. This task encodes the
stop rule as one pure, unit-testable function — no LLM.

*(Depends on TASK-1911 only because both edit `nodes/development.py` —
sequential execution avoids merge churn; there is no semantic dependency.)*

---

## Scope

- Add module-level pure function in `nodes/development.py`:
  ```python
  def should_fan_out(wave: List[TaskRef], pool_cfg: DevAgentPoolConfig) -> bool
  ```
  Returns `True` only when the first wave has ≥ 2 independent tasks (and the
  pool has > 1 effective worker slots).
- Wire it into the pool-vs-single decision: after `_resolve_pool_config`
  yields a config, compute the first `TaskScheduler.next_wave()`; when
  `should_fan_out(...)` is `False`, degrade to the existing single-agent
  path (which already exists as the fallback).
- Ensure degradation is logged (`self.logger.info`) with the reason.
- Unit tests for the function and for the degradation wiring.

**NOT in scope**: changing `TaskScheduler`; wave-size caps; retry/escalation
logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` | MODIFY | `should_fan_out` + wiring |
| `packages/ai-parrot/tests/flows/dev_loop/test_development_node.py` | MODIFY | stop-rule tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models import DevAgentPoolConfig
from parrot.flows.dev_loop.task_scheduler import TaskScheduler
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py
def _resolve_pool_config(self, shared: Dict[str, Any]) -> Optional[DevAgentPoolConfig]:  # line 139
# cascade: WorkBrief.dev_agents > injected pool_config > None (lines 139-154)
# pool-vs-single decision at lines 123-133: pool_cfg None or dispatcher_builder None → single-agent
async def _execute_pool(self, shared, research, pool_cfg) -> DevelopmentOutput:  # 235-240
# pool loop: while True: wave = scheduler.next_wave() (lines 235-340)

# packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py
def next_wave(self) -> List[TaskRef]:   # line 166 — dependency-satisfied pending tasks
# TaskScheduler class spans lines 43-238; Kahn topological ordering
```

### Does NOT Exist
- ~~`should_fan_out`~~ — this task creates it
- ~~a runtime parallelism decision anywhere~~ — today it is config-only
- ~~`TaskScheduler.peek_wave()`~~ — *(unverified — check whether `next_wave()` mutates scheduler state; if it consumes the wave, either construct a throwaway scheduler for the decision or capture the first wave and pass it into the pool loop — do NOT call next_wave() twice blindly)*

### Contract resolution (found during implementation, 2026-07-26)
- `next_wave()` does NOT mutate scheduler state (confirmed by reading it in
  full: only `mark_done`/`mark_failed` touch `_pending`/`_done`/`_failed`).
  Calling it twice (once in `execute()` for the `should_fan_out` decision,
  once more as the first iteration of `_execute_pool`'s `while True:` loop)
  is safe and idempotent — no throwaway scheduler needed. To avoid
  re-reading the per-spec index file twice, though, the scheduler
  CONSTRUCTION (`_find_feature_slug` + `TaskScheduler.from_worktree`) was
  hoisted out of `_execute_pool` into a new `_build_scheduler(research)`
  helper, called once from `execute()`; the resulting scheduler is passed
  into `_execute_pool` as a new parameter instead of rebuilding it there.
- `next_wave()`'s own docstring states it returns tasks "in no particular
  order" — `TaskScheduler._pending` is a plain `Set[str]`, not an
  order-preserving structure. Several pre-existing tests asserted which
  specific task landed on `development.w1` vs `w2`; those assertions were
  fixed to be order-independent (see Completion Note).

---

## Implementation Notes

### Key Constraints
- Pure function: no I/O, no LLM, no config reads inside — everything via
  parameters. This is what makes it unit-testable per the spec.
- Effective worker slots = sum of `spec.count` across `pool_cfg.agents`
  (capped by `pool_max` — check how `DevAgentPool.build` computes it and
  mirror).
- A feature with a long dependency chain (every wave size 1) must run
  single-agent even with 4 configured workers.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py` — `DevAgentPool.build(cls, config, dispatcher_builder, pool_max)` cap semantics
- `packages/ai-parrot/tests/flows/dev_loop/test_development_node.py` — FEAT-323 node tests to extend

---

## Acceptance Criteria

- [ ] `should_fan_out`: <2 independent first-wave tasks → False; ≥2 → True; ≤1 effective slot → False
- [ ] Configured pool + chain-shaped task graph → single-agent path taken (logged)
- [ ] Configured pool + ≥2-task first wave → pool path taken (unchanged)
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/` clean

---

## Test Specification

```python
def test_should_fan_out_two_independent_tasks(): ...
def test_should_fan_out_single_task_wave(): ...
def test_should_fan_out_single_slot_pool(): ...
async def test_development_degrades_to_single_agent_on_chain(): ...
```

---

## Agent Instructions

1. **Read the spec** for full context
2. **Check dependencies** — TASK-1911 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/graphindex-as-engineering-devloop.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-26
**Notes**:
- `nodes/development.py`: added module-level `should_fan_out(wave,
  pool_cfg) -> bool` — pure, no I/O/LLM/config reads. Returns `True` only
  when `len(wave) >= 2` AND `sum(spec.count for spec in pool_cfg.agents) >
  1`. Wired into `execute()`: after the existing `pool_cfg is None` /
  `dispatcher_builder is None` degradation checks, builds the scheduler
  once (new `_build_scheduler(research)` helper, extracted from
  `_execute_pool` — see Codebase Contract resolution), computes
  `scheduler.next_wave()`, and degrades to `_execute_single` (logged via
  `self.logger.info` with the wave size and effective slot count) when
  `should_fan_out` is `False`. `_execute_pool` now takes the already-built
  `scheduler` as a parameter instead of rebuilding it (no double index
  read).
- Fixed 6 pre-existing tests across 2 files whose pool configs had only
  1 effective worker slot (`DevAgentSpec(agent=..., count=1)` default) —
  under the new stop rule these ALWAYS degrade to single-agent regardless
  of wave size, since `effective_slots=1` fails `>1` unconditionally. Not
  in this task's listed file scope, but genuine regressions from the
  correct new behavior (same policy applied to test fixture breaks in
  every prior task this session):
  - `test_development_node.py` (5 tests, `TestCascade`/`TestPoolPath`):
    bumped to `count=2` (or 2 explicit specs) and added a second
    independent first-wave task where needed, preserving each test's
    original intent (cascade config resolution, multi-wave dispatch,
    all-incomplete, isolated-mode cleanup — the latter two now use 2
    dispatchers/managers instead of 1). Discovered and fixed an
    order-dependent assertion in `test_injected_pool_used_when_no_brief_pool`
    while doing this — `next_wave()`'s "no particular order" contract
    means asserting task-1-lands-on-worker-1 was already latent-fragile;
    rewrote to assert set membership instead of position.
  - `integration/test_pool_e2e.py::test_partial_completion_reaches_qa`:
    bumped to a 2-worker pool with BOTH dispatchers configured to fail
    "TASK-2" once, so the failure survives landing on either worker
    (initial attempt or the round-robin retry) — preserves the original
    "TASK-2 fails twice → incomplete, TASK-3 skipped transitively"
    assertion regardless of which worker gets which task.
- New tests: `TestShouldFanOut` (5 cases covering the acceptance
  criteria: 2-task+multi-slot fans out, single-task wave never fans out,
  empty wave never fans out, single-slot pool never fans out even with a
  2-task wave, and effective-slot summation across multiple specs) and
  `TestFanOutWiring` (`test_development_degrades_to_single_agent_on_chain`
  — 3-task straight chain + 4-worker pool still runs single-agent;
  `test_development_takes_pool_path_when_wave_has_two_tasks` — unchanged
  pool-path behavior).
- `pytest packages/ai-parrot/tests/flows/dev_loop/ -m "not live"` (minus
  the pre-existing `hypothesis`-missing file): 676 passed, 1 skipped,
  same one pre-existing unrelated failure noted in every prior task.
  Re-ran the fixed files 3x each to rule out the `set`-ordering
  discovery being a flake rather than a real fix — stable.
- `ruff check` clean on all touched files.

**Deviations from spec**: none beyond the documented, non-behavioral test
fixture fixes above (all caused by the new stop rule correctly changing
single-worker-pool behavior, which the spec's own acceptance criteria
require).

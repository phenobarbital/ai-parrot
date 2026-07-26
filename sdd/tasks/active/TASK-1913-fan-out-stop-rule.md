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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

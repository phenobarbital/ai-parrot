---
type: Wiki Overview
title: 'TASK-941: Migrate run_flow'
id: doc:sdd-tasks-completed-task-941-migrate-run-flow-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This migration is the most critical validation of the flow primitives — if
  `AgentTaskMachine`, `FlowContext.can_execute()`, and `FlowTransition` have design
  flaws, this is where they surface.
relates_to:
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# TASK-941: Migrate run_flow

**Feature**: FEAT-137 — AgentCrew Primitives Migration
**Spec**: `sdd/specs/agentcrew-primitives.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-940
**Assigned-to**: unassigned

---

## Context

`run_flow` is the most complex execution mode: a DAG with dependencies declared via `task_flow()`, conditional transitions (`ON_SUCCESS`, `ON_ERROR`, `ON_CONDITION`, `ALWAYS`), priority-based evaluation, cycle detection, retry semantics, and the `on_agent_complete` callback.

This migration is the most critical validation of the flow primitives — if `AgentTaskMachine`, `FlowContext.can_execute()`, and `FlowTransition` have design flaws, this is where they surface.

This is Module 4 of the spec.

---

## Scope

- Replace local `FlowContext` and type alias usage within `run_flow` (crew.py:2131-2270+) with core `flows.core` imports.
- Wire FSM transitions for DAG execution:
  - `fsm.schedule()` when all dependencies satisfied.
  - `fsm.start()` when execution begins.
  - `fsm.succeed()` on success.
  - `fsm.fail()` on error/timeout.
  - `fsm.retry()` for failed nodes with `retry_count < max_retries`.
- Wire `on_agent_complete` callback to FSM's `on_enter_completed` hook instead of the current ad-hoc call site (crew.py:2252-2254).
- Verify all invariants:
  - Agent executes only when ALL dependencies are in `completed` state.
  - `task_flow(A, B, condition=ON_SUCCESS)`: B runs only if A completed without error.
  - `task_flow(A, B, condition=ON_ERROR)`: B runs only if A failed.
  - `task_flow(A, B, condition=ON_CONDITION, predicate=fn)`: B runs if `await fn(A.result)` is truthy.
  - Multiple transitions from same source: evaluation order = priority descending.
  - Cycle detection: warning, not exception.
  - Retry: `max_retries` respected.
- Add mock-based regression tests for flow invariants.
- Add `@pytest.mark.real_llm` tests: DAG and conditional scenarios.

**NOT in scope**: Migrating `run_loop`. Removing local definitions. Changing `task_flow()` signature.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | MODIFY | Migrate `run_flow` to use core primitives + FSM |
| `packages/ai-parrot/tests/test_crew_flow_regression.py` | CREATE | Regression tests for flow mode |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.bots.flows.core import (
    FlowContext, AgentRef, DependencyResults, PromptBuilder,
    determine_run_status, NodeExecutionInfo, AgentTaskMachine,
    TransitionCondition,  # fsm.py:17 — ON_SUCCESS, ON_ERROR, ON_CONDITION, ALWAYS
    FlowTransition,       # transition.py:28
)
from parrot.models.crew import CrewResult, AgentExecutionInfo, build_agent_metadata
```

### Existing Signatures to Use

```python
# crew.py run_flow signature (line 2131):
async def run_flow(
    self, initial_task: str, max_iterations: int = 100,
    generate_summary: bool = True, synthesis_prompt: Optional[str] = None,
    user_id=None, session_id=None, max_tokens: int = 8192,
    temperature: float = 0.1,
    on_agent_complete: Optional[Callable] = None,  # CALLBACK
    **kwargs
) -> CrewResult:

# on_agent_complete current call site (crew.py:2252-2254):
# if on_agent_complete:
#     for agent_name, result in results.items():
#         await on_agent_complete(agent_name, result, context)

# FlowTransition (transition.py:28):
@dataclass
class FlowTransition:
    source: str
    targets: Set[str]
    condition: TransitionCondition = TransitionCondition.ON_SUCCESS
    predicate: Optional[Callable] = None
    priority: int = 0
    async def should_activate(self, result, error) -> bool:  # evaluates condition

# TransitionCondition (fsm.py:17):
class TransitionCondition(str, Enum):
    ON_SUCCESS = "on_success"
    ON_ERROR = "on_error"
    ON_TIMEOUT = "on_timeout"
    ON_CONDITION = "on_condition"
    ALWAYS = "always"

# AgentTaskMachine (fsm.py:40):
# Hooks: on_enter_completed() — this is where on_agent_complete will fire
# Transitions: schedule, start, succeed, fail, retry

# crew.py task_flow (line 633):
def task_flow(self, source_agent, target_agents):
```

### Does NOT Exist

- ~~`AgentTaskMachine.on_complete`~~ — the hook is `on_enter_completed`, not `on_complete`
- ~~`FlowTransition.evaluate()`~~ — use `should_activate(result, error)`
- ~~`FlowContext.get_ready_nodes()`~~ — no such method; iterate nodes and check `can_execute()` per node
- ~~`AgentTaskMachine.is_completed`~~ — check `fsm.current_state == fsm.completed`

---

## Implementation Notes

### Wiring on_agent_complete to FSM

The `on_agent_complete` callback currently fires at an ad-hoc point after batch processing (crew.py:2252-2254). Post-migration, it should fire via the FSM's `on_enter_completed` hook. The approach:

1. Before execution starts, if `on_agent_complete` is provided, register it as a callback on each node's FSM `on_enter_completed`.
2. The FSM's `on_enter_completed` fires when `fsm.succeed()` is called, which happens at the same logical moment as the current ad-hoc call.
3. The callback must receive `(agent_name, result, context)` — same signature as today.

Key consideration: `on_enter_completed` is a synchronous hook in `python-statemachine`. If `on_agent_complete` is async, the FSM hook needs to schedule the coroutine. Verify how `AgentTaskMachine` handles async hooks — if it doesn't, add an adapter that uses `asyncio.create_task` or call the callback immediately after `fsm.succeed()` instead of inside the hook.

### Key Constraints

- Do NOT change `run_flow` or `task_flow` method signatures.
- Cycle detection must produce a warning (via `self.logger.warning`), NOT raise an exception.
- Retry: a failed node with `retry_count < max_retries` can be re-scheduled via `fsm.retry()` (failed → ready).
- The DAG evaluation loop must respect `max_iterations` to prevent infinite loops in degenerate cases.

---

## Acceptance Criteria

- [ ] `run_flow` uses core `FlowContext`, FSM transitions, and `TransitionCondition`
- [ ] `on_agent_complete` fires via FSM `on_enter_completed` (or immediately after `succeed()`)
- [ ] Dependency ordering: agent runs only when all deps completed
- [ ] `ON_SUCCESS`, `ON_ERROR`, `ON_CONDITION`, `ALWAYS` transitions work correctly
- [ ] Priority-based transition evaluation (descending)
- [ ] Cycle detection produces warning, not exception
- [ ] Retry semantics with `max_retries` respected
- [ ] All existing flow tests pass unchanged
- [ ] New mock-based regression tests pass
- [ ] `@pytest.mark.real_llm` tests pass with `PARROT_TEST_REAL_LLM=1`
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot/tests/test_crew_flow_regression.py
import pytest


class TestFlowRegression:
    async def test_dependency_ordering(self):
        """A→B,C→D: B and C run after A; D runs after B and C."""

    async def test_on_success_transition(self):
        """A→B (ON_SUCCESS): B runs only if A succeeded."""

    async def test_on_error_transition(self):
        """A→C (ON_ERROR): C runs only if A failed."""

    async def test_on_condition_predicate(self):
        """A→B (ON_CONDITION, predicate): B runs only if predicate(A.result) is truthy."""

    async def test_cycle_detection_warning(self):
        """Adding transition that creates cycle → warning, not exception."""

    async def test_callback_via_fsm(self):
        """on_agent_complete fires with correct (agent_name, result, context) args."""
        callback_log = []
        async def callback(name, result, ctx):
            callback_log.append((name, result))
        # Run flow with callback, verify log entries

    async def test_retry_on_failure(self):
        """Failed agent with retries remaining is re-executed."""

    @pytest.mark.real_llm
    async def test_real_flow_dag(self):
        """A→B,C→D DAG with Gemini Flash."""

    @pytest.mark.real_llm
    async def test_real_flow_conditional(self):
        """A→B (ON_SUCCESS), A→C (ON_ERROR) with Gemini Flash."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-940 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm signatures still accurate
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-941-migrate-run-flow.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

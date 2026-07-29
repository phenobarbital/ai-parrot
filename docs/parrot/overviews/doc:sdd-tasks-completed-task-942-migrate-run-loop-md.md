---
type: Wiki Overview
title: 'TASK-942: Migrate run_loop'
id: doc:sdd-tasks-completed-task-942-migrate-run-loop-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This mode is the most "particular" — it doesn't map cleanly to the DAG primitives.
  The FSM usage here is per-iteration (each pass through the loop is a fresh execution
  cycle) rather than per-node-in-a-graph.
relates_to:
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# TASK-942: Migrate run_loop

**Feature**: FEAT-137 — AgentCrew Primitives Migration
**Spec**: `sdd/specs/agentcrew-primitives.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-941
**Assigned-to**: unassigned

---

## Context

`run_loop` is a special execution mode: iterative, not graph-based. Each iteration's output becomes the next iteration's prompt. A stop condition (LLM-evaluated) or `max_iterations` cap terminates the loop.

This mode is the most "particular" — it doesn't map cleanly to the DAG primitives. The FSM usage here is per-iteration (each pass through the loop is a fresh execution cycle) rather than per-node-in-a-graph.

This is Module 5 of the spec.

---

## Scope

- Replace local `FlowContext` and type alias usage within `run_loop` (crew.py:1420-1518+) with core `flows.core` imports.
- Wire FSM transitions per loop iteration:
  - Each iteration: `fsm.schedule()` → `fsm.start()` → `fsm.succeed()` (or `fail()`).
  - On new iteration: reset or create new FSM state (decide: reuse node with state reset, or track iteration metadata).
- Verify all invariants:
  - Iteration 0: prompt = `initial_task`.
  - Iteration N: prompt = output of iteration N-1 (NOT accumulated context).
  - Stop condition: evaluated by LLM against output + condition string.
  - `max_iterations` cap respected.
  - `result.metadata['iterations']` = actual iteration count.
- Add mock-based regression tests for loop invariants.
- Add `@pytest.mark.real_llm` tests: condition-met and max-cap scenarios.

**NOT in scope**: Removing local definitions (TASK-943). Any changes to loop condition evaluation logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | MODIFY | Migrate `run_loop` to use core primitives + FSM |
| `packages/ai-parrot/tests/test_crew_loop_regression.py` | CREATE | Regression tests for loop mode |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.bots.flows.core import (
    FlowContext, AgentRef, DependencyResults, PromptBuilder,
    determine_run_status, NodeExecutionInfo, AgentTaskMachine,
)
from parrot.models.crew import CrewResult, AgentExecutionInfo, build_agent_metadata
```

### Existing Signatures to Use

```python
# crew.py run_loop signature (line 1420):
async def run_loop(
    self, initial_task: str, condition: str,
    max_iterations: int = 2, user_id=None, session_id=None,
    agent_sequence: Optional[List[str]] = None,
    pass_full_context: bool = True, generate_summary: bool = True,
    synthesis_prompt: Optional[str] = None, max_tokens: int = 8192,
    temperature: float = 0.1, **kwargs
) -> CrewResult:

# AgentTaskMachine (fsm.py:40):
# States: idle, ready, running, completed, failed, blocked
# For loop: each iteration cycles through schedule → start → succeed
```

### Does NOT Exist

- ~~`AgentTaskMachine.reset()`~~ — no reset method; for new iterations, either create a new FSM or manage state manually. Verify available transitions.
- ~~`FlowContext.iteration_count`~~ — does not exist on core FlowContext; track iterations in `result.metadata['iterations']`
- ~~`AgentNode.run_iteration()`~~ — no such method; use `execute()` per iteration

---

## Implementation Notes

### Loop FSM Strategy

The loop is different from DAG modes: the same agent(s) execute multiple times. Two approaches:
1. **New FSM per iteration**: create a fresh `AgentTaskMachine` for each iteration. Simple but loses state history.
2. **Retry-based**: use `fsm.succeed()` then re-`schedule()` for next iteration. Check if `completed → ready` transition exists (it likely doesn't — `completed` is a final state).

Recommended: approach 1 (fresh FSM per iteration) since `completed` is a final state in the FSM. The iteration count is tracked externally in `result.metadata['iterations']`.

### Key Constraints

- Do NOT change the `run_loop` method signature.
- Iteration N prompt = output of iteration N-1 ONLY — no accumulated context.
- The condition evaluation logic (LLM-based) must NOT change. It already works; just ensure it receives the correct context.
- `max_iterations` is a hard cap — if reached, loop stops regardless of condition.

---

## Acceptance Criteria

- [ ] `run_loop` uses core `FlowContext`
- [ ] FSM transitions wired per iteration
- [ ] Iteration chaining: prompt N = output of N-1
- [ ] Stop condition evaluates correctly
- [ ] `max_iterations` cap respected
- [ ] `result.metadata['iterations']` = actual count
- [ ] All existing loop tests pass unchanged
- [ ] New mock-based regression tests pass
- [ ] `@pytest.mark.real_llm` tests pass with `PARROT_TEST_REAL_LLM=1`
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot/tests/test_crew_loop_regression.py
import pytest


class TestLoopRegression:
    async def test_iteration_chaining(self):
        """Iteration N prompt = output of iteration N-1."""

    async def test_max_iterations_cap(self):
        """Loop stops at max_iterations even if condition unmet."""
        result = await crew.run_loop(
            initial_task="start",
            condition="never true",
            max_iterations=3,
        )
        assert result.metadata["iterations"] == 3

    async def test_condition_stops_early(self):
        """Loop stops before max when condition met."""

    async def test_fsm_per_iteration(self):
        """Each iteration has valid FSM state transitions."""

    @pytest.mark.real_llm
    async def test_real_loop_condition_met(self):
        """Loop with Gemini Flash until output contains keyword."""

    @pytest.mark.real_llm
    async def test_real_loop_max_cap(self):
        """Condition never met, max_iterations respected."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-941 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm signatures still accurate
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-942-migrate-run-loop.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

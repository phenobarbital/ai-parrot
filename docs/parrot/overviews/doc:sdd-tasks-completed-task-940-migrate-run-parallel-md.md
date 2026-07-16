---
type: Wiki Overview
title: 'TASK-940: Migrate run_parallel'
id: doc:sdd-tasks-completed-task-940-migrate-run-parallel-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is Module 3 of the spec. It follows the same migration pattern as TASK-939
  (sequential) but adds concurrency concerns.
relates_to:
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# TASK-940: Migrate run_parallel

**Feature**: FEAT-137 — AgentCrew Primitives Migration
**Spec**: `sdd/specs/agentcrew-primitives.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-939
**Assigned-to**: unassigned

---

## Context

`run_parallel` executes all agents concurrently via `asyncio.gather(return_exceptions=True)`. This mode introduces concurrent FSM state management: each node has its own FSM (no shared state), but `FlowContext.completed_tasks` is mutated concurrently by multiple tasks.

This is Module 3 of the spec. It follows the same migration pattern as TASK-939 (sequential) but adds concurrency concerns.

---

## Scope

- Replace local `FlowContext` and type alias usage within `run_parallel` (crew.py:1846-1920+) with core `flows.core` imports.
- Wire FSM transitions for concurrent execution:
  - All nodes: `fsm.schedule()` → `fsm.start()` before gather.
  - Per-node: `fsm.succeed()` on success, `fsm.fail()` on error.
- Verify concurrent safety: `set.add()` on `FlowContext.completed_tasks` is atomic in CPython — verify this invariant holds with FSM per node.
- Verify all invariants:
  - All agents start within the same `asyncio.gather`.
  - Errors captured via `return_exceptions=True`; individual failure does NOT abort others.
  - Status: `completed` (all OK), `partial` (some OK + some failed), `failed` (all failed).
  - `result.agents` order may not match add-order (depends on completion timing).
- Add mock-based regression tests for parallel invariants.
- Add `@pytest.mark.real_llm` tests: 3-agent parallel, one-failure scenario.

**NOT in scope**: Migrating `run_flow` or `run_loop`. Removing local definitions.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | MODIFY | Migrate `run_parallel` to use core primitives + FSM |
| `packages/ai-parrot/tests/test_crew_parallel_regression.py` | CREATE | Regression tests for parallel mode |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Same core imports as TASK-939:
from parrot.bots.flows.core import (
    FlowContext, AgentRef, DependencyResults, PromptBuilder,
    determine_run_status, NodeExecutionInfo, AgentTaskMachine,
)
from parrot.models.crew import CrewResult, AgentExecutionInfo, build_agent_metadata
```

### Existing Signatures to Use

```python
# crew.py run_parallel signature (line 1846):
async def run_parallel(
    self, tasks: List[Dict[str, Any]], all_results: Optional[bool] = True,
    user_id=None, session_id=None, generate_summary: bool = True,
    synthesis_prompt: Optional[str] = None, max_tokens: int = 8192,
    temperature: float = 0.1, **kwargs
) -> CrewResult:

# Core FlowContext (same contract as TASK-939):
# can_execute(), mark_completed(), mark_failed(), get_input_for_node()

# AgentTaskMachine transitions:
# schedule: idle → ready
# start: ready → running
# succeed: running → completed
# fail: running/ready/idle → failed
```

### Does NOT Exist

- ~~`AgentTaskMachine.complete()`~~ — use `succeed()`
- ~~`FlowContext.mark_all_completed()`~~ — no batch method; call `mark_completed` per node
- ~~`AgentNode.is_completed`~~ — check `node.fsm.current_state == node.fsm.completed`

---

## Implementation Notes

### Pattern to Follow

Within `run_parallel`:
1. For each agent node: `node.fsm.schedule()` then `node.fsm.start()`.
2. `asyncio.gather(*[node.execute(prompt, timeout=...) for node in nodes], return_exceptions=True)`.
3. For each result in gather output:
   - Success: `node.fsm.succeed()`, `context.mark_completed(...)`.
   - Exception: `node.fsm.fail()` (if not already failed by execute's error handler), `context.mark_failed(...)`.
4. Status via `determine_run_status(success_count, failure_count)`.

### Key Constraints

- Do NOT change `run_parallel` method signature.
- `asyncio.gather(return_exceptions=True)` semantics must be preserved exactly.
- Each node has its own FSM instance — no shared FSM state between concurrent tasks.
- `FlowContext.completed_tasks.add()` is called from multiple coroutines — this is safe in CPython due to GIL, but add a comment noting the assumption.
- Be careful with `fsm.fail()` in execute's error handler vs the gather result processing — avoid double-transition. Check `fsm.current_state` before calling `fail()`.

---

## Acceptance Criteria

- [ ] `run_parallel` uses core `FlowContext` and FSM transitions
- [ ] `asyncio.gather(return_exceptions=True)` semantics preserved
- [ ] Status calculation: completed/partial/failed correct for all scenarios
- [ ] Concurrent FSM safety verified (each node independent)
- [ ] All existing parallel tests pass unchanged
- [ ] New mock-based regression tests pass
- [ ] `@pytest.mark.real_llm` tests pass with `PARROT_TEST_REAL_LLM=1`
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot/tests/test_crew_parallel_regression.py
import pytest


class TestParallelRegression:
    async def test_all_agents_run_concurrently(self, crew_with_3_stub_agents):
        """All agents execute via asyncio.gather."""
        result = await crew_with_3_stub_agents.run_parallel(
            [{"task": "t1"}, {"task": "t2"}, {"task": "t3"}]
        )
        assert result.status == "completed"
        assert len(result.agents) == 3

    async def test_one_failure_partial_status(self, crew_with_one_failing_agent):
        """One failure → partial status, others complete."""
        result = await crew_with_one_failing_agent.run_parallel(...)
        assert result.status == "partial"
        assert len(result.errors) == 1

    async def test_all_failure_failed_status(self, crew_with_all_failing_agents):
        """All fail → failed status."""
        result = await crew_with_all_failing_agents.run_parallel(...)
        assert result.status == "failed"

    async def test_fsm_states_independent(self, crew_with_3_stub_agents):
        """Each node FSM transitions independently."""
        # Verify FSM states after parallel execution

    @pytest.mark.real_llm
    async def test_real_parallel_3_agents(self, crew_with_3_gemini_agents):
        """3 agents in parallel with Gemini Flash."""
        result = await crew_with_3_gemini_agents.run_parallel(
            [{"task": "Explain gravity"}, {"task": "Explain entropy"}, {"task": "Explain inertia"}]
        )
        assert result.status == "completed"

    @pytest.mark.real_llm
    async def test_real_parallel_one_failure(self):
        """One agent configured to fail, others succeed."""
        # Verify partial status with real LLM
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-939 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm signatures still accurate
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-940-migrate-run-parallel.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

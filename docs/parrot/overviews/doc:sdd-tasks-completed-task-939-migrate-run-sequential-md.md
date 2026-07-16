---
type: Wiki Overview
title: 'TASK-939: Migrate run_sequential'
id: doc:sdd-tasks-completed-task-939-migrate-run-sequential-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The migration swaps crew.py's local `FlowContext` and type aliases for `flows.core`
  imports and wires FSM state transitions at the correct execution points. The method
  signature and all observable behavior must remain identical.
relates_to:
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.bots.flows.core.types
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# TASK-939: Migrate run_sequential

**Feature**: FEAT-137 — AgentCrew Primitives Migration
**Spec**: `sdd/specs/agentcrew-primitives.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-938
**Assigned-to**: unassigned

---

## Context

`run_sequential` is the simplest execution mode: a linear pipeline where each agent's output feeds the next. This is the first mode to migrate, establishing the pattern for all subsequent modes.

The migration swaps crew.py's local `FlowContext` and type aliases for `flows.core` imports and wires FSM state transitions at the correct execution points. The method signature and all observable behavior must remain identical.

This is Module 2 of the spec.

---

## Scope

- Replace local `FlowContext` usage within `run_sequential` (crew.py:1123-1400) with core `FlowContext` from `parrot.bots.flows.core.context`.
- Replace local type aliases (`AgentRef`, `DependencyResults`, `PromptBuilder`) with imports from `parrot.bots.flows.core.types`.
- Wire FSM transitions at correct points within `run_sequential`:
  - `fsm.schedule()` when the node is next in line.
  - `fsm.start()` when execution begins.
  - `fsm.succeed()` on successful completion.
  - `fsm.fail()` on error or timeout.
- Verify all invariants:
  - Agents execute in strict `add_agent` order.
  - Output of agent N propagates as dependency context to agent N+1.
  - If agent K fails, agents K+1..N do NOT execute; status = `partial` (or `failed` if K=0).
  - `result.status` calculated by `determine_run_status()`.
- Add mock-based regression tests for sequential invariants.
- Add `@pytest.mark.real_llm` test: 3-agent pipeline with Gemini Flash.

**NOT in scope**: Migrating `run_parallel`, `run_flow`, or `run_loop`. Removing local class definitions (that's TASK-943 cleanup).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | MODIFY | Migrate `run_sequential` to use core primitives + FSM |
| `packages/ai-parrot/tests/test_crew_sequential_regression.py` | CREATE | Regression tests for sequential mode |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Core primitives to use:
from parrot.bots.flows.core import (
    FlowContext,           # context.py:26
    AgentRef,              # types.py:100
    DependencyResults,     # types.py (type alias)
    PromptBuilder,         # types.py (type alias)
    determine_run_status,  # result.py:32
    NodeExecutionInfo,     # result.py:60
    AgentTaskMachine,      # fsm.py:40
)

# Already in crew.py:
from parrot.models.crew import (
    CrewResult,            # return type
    AgentExecutionInfo,    # per-agent metadata
    build_agent_metadata,  # metadata builder (models/crew.py:322)
)
```

### Existing Signatures to Use

```python
# Core FlowContext (flows/core/context.py:26)
@dataclass
class FlowContext:
    initial_task: str
    results: Dict[str, Any]
    responses: Dict[str, Any]
    node_metadata: Dict[str, NodeExecutionInfo]
    completion_order: List[str]
    errors: Dict[str, Exception]
    active_tasks: Set[str]
    completed_tasks: Set[str]
    def can_execute(self, _node_id, dependencies: Set[str]) -> bool:  # line 66
    def mark_completed(self, node_id, result=None, response=None, metadata=None):  # line 80
    def mark_failed(self, node_id, error, metadata=None):  # line 109
    def get_input_for_node(self, node_id, dependencies: Set[str]):  # line 132
    def get_input_for_agent(self, agent_name, dependencies):  # line 169 (backward-compat alias)
    @property
    def agent_metadata(self):  # line 169 (backward-compat alias for node_metadata)

# crew.py run_sequential signature (line 1123):
async def run_sequential(
    self, query: str, user_id=None, session_id=None,
    pass_full_context: bool = True, generate_summary: bool = True,
    synthesis_prompt: Optional[str] = None, agent_sequence: List[str] = None,
    max_tokens: int = 8192, temperature: float = 0.1,
    model: Optional[str] = 'gemini-2.5-pro', **kwargs
) -> CrewResult:

# AgentTaskMachine transitions (fsm.py:40):
# schedule: idle → ready
# start: ready → running
# succeed: running → completed
# fail: running/ready/idle → failed
```

### Does NOT Exist

- ~~`FlowContext.get_result_for_agent()`~~ — use `get_input_for_agent()` or `get_input_for_node()`
- ~~`AgentTaskMachine.complete()`~~ — the transition is called `succeed`, not `complete`
- ~~`AgentTaskMachine.run()`~~ — the transition is called `start`, not `run`
- ~~`FlowContext.add_result()`~~ — use `mark_completed(node_id, result=..., response=...)`

---

## Implementation Notes

### Pattern to Follow

Within `run_sequential`, at each agent execution step:
1. `node.fsm.schedule()` — mark node as ready.
2. `node.fsm.start()` — mark as running.
3. Execute via `node.execute(prompt, timeout=self.agent_execution_timeout)` (inherited from core `AgentNode`).
4. On success: `node.fsm.succeed()`, then `context.mark_completed(agent_name, result, response, metadata)`.
5. On failure: `node.fsm.fail()`, then `context.mark_failed(agent_name, error, metadata)`.

The core `FlowContext` from `flows.core` has the same API as the local one (plus backward-compat aliases), so the migration is mostly an import swap + adding FSM transition calls.

### Key Constraints

- Do NOT change the method signature of `run_sequential`.
- Do NOT change the `CrewResult` structure or status calculation logic.
- The local `FlowContext` class definition in crew.py must NOT be deleted yet — other modes still reference it. Just stop using it in `run_sequential`. Deletion is TASK-943.
- FSM transitions must NOT change observable behavior — they formalize what already happens implicitly.

---

## Acceptance Criteria

- [ ] `run_sequential` uses core `FlowContext` from `flows.core`
- [ ] FSM transitions wired at correct execution points
- [ ] Agents execute in strict order with output propagation
- [ ] Early-stop on failure preserves `partial`/`failed` status semantics
- [ ] All existing sequential tests pass unchanged
- [ ] New mock-based regression tests pass
- [ ] `@pytest.mark.real_llm` test passes with `PARROT_TEST_REAL_LLM=1`
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot/tests/test_crew_sequential_regression.py
import pytest


class TestSequentialRegression:
    async def test_execution_order_strict(self, crew_with_3_stub_agents):
        """Agents execute in add_agent order."""
        result = await crew_with_3_stub_agents.run_sequential("start")
        # Verify completion_order matches add order

    async def test_output_propagation(self, crew_with_3_stub_agents):
        """Output of agent N feeds agent N+1 as dependency context."""
        result = await crew_with_3_stub_agents.run_sequential("start")
        # Verify each agent received previous agent's output

    async def test_early_stop_on_failure(self, crew_with_failing_middle_agent):
        """If agent K fails, K+1..N do not execute."""
        result = await crew_with_failing_middle_agent.run_sequential("start")
        assert result.status == "partial"
        # Verify third agent did not execute

    async def test_fsm_states_after_sequential(self, crew_with_3_stub_agents):
        """All node FSMs in completed state after successful run."""
        result = await crew_with_3_stub_agents.run_sequential("start")
        # Verify FSM states

    @pytest.mark.real_llm
    async def test_real_sequential_3_agents(self, crew_with_3_gemini_agents):
        """Real 3-agent pipeline with Gemini Flash."""
        result = await crew_with_3_gemini_agents.run_sequential(
            "Summarize the concept of machine learning in one sentence"
        )
        assert result.status == "completed"
        assert len(result.agents) == 3
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-938 is in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-939-migrate-run-sequential.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

---
type: Wiki Overview
title: 'TASK-1781: Fix `run_loop()` Frozen-FSM Reassignment Bug'
id: doc:sdd-tasks-completed-task-1781-run-loop-frozen-fsm-fix-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'escape hatch: `object.__setattr__(node, "fsm", AgentTaskMachine(agent_name=node.agent.name))`.'
relates_to:
- concept: mod:parrot.bots.flows.crew.crew
  rel: mentions
---

# TASK-1781: Fix `run_loop()` Frozen-FSM Reassignment Bug

**Feature**: FEAT-309 — Fix `AgentCrew.run_loop()` Frozen-FSM Reassignment Bug
**Spec**: `sdd/specs/agentcrew-run-loop-frozen-fsm-fix.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Spec §3 Module 1. `AgentCrew.run_loop()` resets each node's FSM at the top
> of every iteration via a direct field reassignment
> (`node.fsm = AgentTaskMachine(...)`). Since `CrewAgentNode` (via `AgentNode`)
> is a **frozen** Pydantic model (`model_config = ConfigDict(frozen=True, ...)`,
> introduced by TASK-1062), this raises `pydantic_core.ValidationError:
> Instance is frozen` on every single call — `run_loop()` is completely
> unusable today with any real `CrewAgentNode`. The codebase already has an
> established, documented escape hatch for this exact situation
> (`object.__setattr__`, used in `AgentNode.model_post_init()`); `run_loop()`
> simply never adopted it. This task is a narrow, mechanical one-line fix.

---

## Scope

- In `AgentCrew.run_loop()`, replace the direct field reassignment
  `node.fsm = AgentTaskMachine(agent_name=node.agent.name)` with the frozen-model
  escape hatch: `object.__setattr__(node, "fsm", AgentTaskMachine(agent_name=node.agent.name))`.
- Keep the existing surrounding comment and per-iteration reset semantics
  exactly as they are (fresh FSM per iteration, because `completed` is a
  final state).

**NOT in scope**: Changing `AgentTaskMachine`'s state graph or adding a
`.reset()` method to the FSM. Un-freezing `AgentNode`/`CrewAgentNode`.
Touching `run_flow`, `run_sequential`, or `run_parallel` (none of them
perform this per-iteration reset — verified via `grep`, exactly one call
site exists in the whole `parrot/bots/flows/` tree). Writing the regression
tests (that's TASK-1782).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | MODIFY | One-line fix inside `run_loop()`'s per-iteration FSM reset loop (~line 1849) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, class names, and method signatures.
> Verified against `packages/ai-parrot/src/parrot/` on 2026-07-14.

### Verified Imports
```python
# Already imported at the top of crew.py — no new imports needed for this fix.
from ..core.fsm import AgentTaskMachine  # crew.py's existing import (module-level)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
async def run_loop(
    self, initial_task: str, condition: str,
    max_iterations: int = 2, ...,
) -> FlowResult: ...                                          # ~L1722

# THE BUG — inside run_loop(), per-iteration FSM reset (~L1844-1849):
for iteration_index in range(max_iterations):
    ...
    # Fresh FSM per iteration (completed is a final state, so
    # we cannot reuse the same FSM across iterations)
    for agent_id in agent_sequence:
        node = self.workflow_graph.get(agent_id)
        if node:
            node.fsm = AgentTaskMachine(agent_name=node.agent.name)  # ← raises ValidationError

# packages/ai-parrot/src/parrot/bots/flows/core/node.py
class Node(BaseModel):                                         # L67
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)  # L98

class AgentNode(Node):                                          # L180
    agent: AgentLike                                            # L211
    node_id: str                                                # L212
    fsm: Optional[AgentTaskMachine] = None                       # L215
    def model_post_init(self, __context: Any) -> None:           # L217
        super().model_post_init(__context)
        if self.fsm is None:
            # THE ESTABLISHED PATTERN — object.__setattr__ is the
            # frozen-Pydantic escape hatch for setting a field.
            object.__setattr__(
                self, "fsm", AgentTaskMachine(agent_name=self.agent.name)
            )                                                    # L222-226

# packages/ai-parrot/src/parrot/bots/flows/crew/nodes.py
class CrewAgentNode(_CoreAgentNode):                             # L28
    # _CoreAgentNode == AgentNode (imported `as _CoreAgentNode`).
    # No __init__ override; inherits AgentNode's frozen model_config
    # and `fsm` field verbatim.

# packages/ai-parrot/src/parrot/bots/flows/core/fsm.py
class AgentTaskMachine(StateMachine):                            # L40
    idle = State("idle", initial=True)                           # L67
    completed = State("completed", final=True)                   # L70
    def __init__(self, agent_name: str, **kwargs: object) -> None: ...  # L84
```

### Does NOT Exist
- ~~`AgentTaskMachine.reset()`~~ — no such method; a fresh instance is
  constructed both before and after this fix — only the *assignment
  mechanism* changes.
- ~~`CrewAgentNode.__setattr__` override~~ — no custom override exists;
  the frozen behavior comes purely from the inherited `model_config`.
- ~~Any other `node.fsm = ...` direct-assignment call site~~ — verified via
  `grep -rn "node.fsm = AgentTaskMachine" packages/ai-parrot/src/parrot/bots/flows/`:
  exactly one match, inside `run_loop()`. Do not "fix" other files —
  there is nothing else to fix.

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py (~line 1844-1849)
# BEFORE:
for agent_id in agent_sequence:
    node = self.workflow_graph.get(agent_id)
    if node:
        node.fsm = AgentTaskMachine(agent_name=node.agent.name)

# AFTER (exact fix):
for agent_id in agent_sequence:
    node = self.workflow_graph.get(agent_id)
    if node:
        object.__setattr__(
            node, "fsm", AgentTaskMachine(agent_name=node.agent.name)
        )
```

### Key Constraints
- Do NOT change `AgentTaskMachine`'s state graph — `completed` must remain
  final; this fix works *with* that constraint (constructing a fresh
  instance), not around it.
- Do NOT un-freeze `AgentNode`/`CrewAgentNode` — that's a much larger
  architectural change (FEAT-163's B-lite shape) relied on elsewhere for
  concurrent-run safety, and is explicitly out of scope.
- Verify that other FSM interactions elsewhere in `run_loop()` (e.g.
  `node.fsm.schedule()`, `.start()`, `.succeed()`, `.fail()`) are untouched —
  those mutate the FSM object in place (not reassigning the frozen field)
  and remain valid after this fix.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/flows/core/node.py:217-227` — the
  established `object.__setattr__` escape-hatch pattern to copy verbatim.

---

## Acceptance Criteria

- [ ] `AgentCrew.run_loop()` completes at least one iteration without
  raising `pydantic_core.ValidationError`, for 0, 1, and many registered
  agents.
- [ ] Each iteration's FSM is verifiably fresh (starts at `idle`); a
  `completed`/`failed` FSM from a prior iteration is never reused.
- [ ] `run_flow`, `run_sequential`, `run_parallel` are unaffected (their
  existing regression test suites continue to pass unmodified — this fix
  touches no code path used by those methods).
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
- [ ] No breaking changes to `AgentNode`/`CrewAgentNode`'s frozen-Pydantic
  contract or `AgentTaskMachine`'s public API.

---

## Test Specification

> This task makes the one-line fix. TASK-1782 owns the full regression
> test suite; however, the fix is not "acceptance-complete" until at least
> a minimal sanity check confirms `run_loop()` no longer raises. A minimal
> ad-hoc check (not a committed test) is sufficient here if TASK-1782
> hasn't started yet — e.g.:

```python
# Ad-hoc sanity check (not committed as part of this task):
import asyncio
from parrot.bots.flows.crew.crew import AgentCrew
# ... construct a crew with >=1 real agent, call:
# await crew.run_loop("start", condition="stop", max_iterations=1)
# Assert no ValidationError is raised.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentcrew-run-loop-frozen-fsm-fix.spec.md` §3 Module 1
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm the exact line numbers and
   surrounding code for the `node.fsm = AgentTaskMachine(...)` call site and
   the `object.__setattr__` pattern in `core/node.py` still match (code may
   have shifted since this task was written)
4. **Implement** the one-line fix exactly as specified
5. **Run a sanity check** (ad-hoc or via TASK-1782 if already available)
6. **Update status** and move to completed when done

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-14
**Notes**: Verified line numbers against current worktree state (unchanged
since spec authoring: `run_loop()` at L1722, FSM reset at L1844-1849).
Applied the exact one-line fix specified: replaced `node.fsm =
AgentTaskMachine(...)` with `object.__setattr__(node, "fsm",
AgentTaskMachine(agent_name=node.agent.name))`, matching the established
escape hatch already documented in `core/node.py:222-227`. Ran an ad-hoc
sanity check (3 stub agents, `run_loop("start", condition="never true",
max_iterations=2)`) — confirmed the fix resolves the
`pydantic_core.ValidationError: Instance is frozen` crash; test passed,
then the throwaway sanity file was deleted (not committed, per the task's
own Test Specification guidance — TASK-1782 owns the real regression
suite). ruff clean. Only `crew.py` touched — no unrelated changes.

**Deviations from spec**: none

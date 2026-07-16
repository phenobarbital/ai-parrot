---
type: Wiki Overview
title: 'Feature Specification: Fix `AgentCrew.run_loop()` Frozen-FSM Reassignment
  Bug'
id: doc:sdd-specs-agentcrew-run-loop-frozen-fsm-fix-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: single invocation** that has at least one registered agent, making the
relates_to:
- concept: mod:parrot.bots.flows.core.fsm
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.bots.flows.crew.crew
  rel: mentions
- concept: mod:parrot.bots.flows.crew.nodes
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Fix `AgentCrew.run_loop()` Frozen-FSM Reassignment Bug

**Feature ID**: FEAT-309
**Date**: 2026-07-14
**Author**: Jesus Lara
**Status**: draft
**Target version**: (next patch)

> Discovered during FEAT-308 (`agentcrew-node-infographic`) TASK-1780's
> end-to-end integration tests. Confirmed via a minimal repro (plain
> `AgentCrew` + 3 stub agents + `run_sequential()`/`run_loop()`, zero
> FEAT-308 code involved) that this is a pre-existing defect, unrelated to
> FEAT-308. See `sdd/tasks/completed/TASK-1780-infographic-integration-tests.md`
> Completion Note for the original discovery write-up.

---

## 1. Motivation & Business Requirements

### Problem Statement

`AgentCrew.run_loop()` raises a `pydantic_core.ValidationError` on **every
single invocation** that has at least one registered agent, making the
loop execution mode entirely unusable today:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for CrewAgentNode
fsm
  Instance is frozen [type=frozen_instance, input_value=AgentTaskMachine(...), input_type=AgentTaskMachine]
```

Root cause: `run_loop()` resets each node's FSM at the top of **every**
iteration (including the very first) via direct field reassignment:

```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:1844-1849
# Fresh FSM per iteration (completed is a final state, so
# we cannot reuse the same FSM across iterations)
for agent_id in agent_sequence:
    node = self.workflow_graph.get(agent_id)
    if node:
        node.fsm = AgentTaskMachine(agent_name=node.agent.name)
```

`CrewAgentNode` (`parrot/bots/flows/crew/nodes.py`) inherits from
`AgentNode` (`parrot/bots/flows/core/node.py`), a **frozen** Pydantic
`BaseModel` (`model_config = ConfigDict(frozen=True,
arbitrary_types_allowed=True)`, introduced by TASK-1062's migration to the
new Pydantic node shape). Frozen models reject *any* direct field
reassignment — `node.fsm = ...` always raises, regardless of iteration
count or agent count.

The codebase already documents and uses the correct pattern for this exact
situation — `AgentNode.model_post_init()` sets the FSM via the frozen-model
escape hatch:

```python
# packages/ai-parrot/src/parrot/bots/flows/core/node.py:222-227
# object.__setattr__ is the frozen-Pydantic escape hatch for
# setting a field inside model_post_init.  Use sparingly.
object.__setattr__(
    self, "fsm", AgentTaskMachine(agent_name=self.agent.name)
)
```

`run_loop()`'s per-iteration reset never adopted this pattern, presumably
because it was written/last touched before TASK-1062 converted nodes from
`@dataclass` to frozen Pydantic models, and was never revisited.

### Goals

- **G1** — `AgentCrew.run_loop()` completes at least one iteration without
  raising `ValidationError`, for any number of registered agents (including
  zero, one, and many).
- **G2** — Preserve the existing "fresh FSM per iteration" semantics
  exactly (each iteration's FSM starts at `idle`; `completed` remains a
  final state that cannot be reused across iterations).
- **G3** — No behavioural change to `run_flow`, `run_sequential`, or
  `run_parallel` — none of them perform this per-iteration FSM reset, and
  none are affected by this bug (confirmed: `grep` shows exactly one
  `node.fsm = AgentTaskMachine(...)` call site in the entire
  `parrot/bots/flows/` tree, inside `run_loop()`).

### Non-Goals (explicitly out of scope)

- Changing `AgentTaskMachine`'s state graph, transitions, or adding a
  native `.reset()` method to the FSM itself — the fix is scoped to
  *how* `run_loop()` replaces the FSM, not the FSM's own API.
- Un-freezing `AgentNode`/`CrewAgentNode` or altering the frozen-Pydantic
  node architecture (FEAT-163 B-lite shape) — that architecture is
  intentional and used correctly everywhere else.
- Any change to `FlowResult`, `ExecutionMemory`, or other FEAT-308
  infographic surfaces — this is a narrowly-scoped bug fix.
- Re-enabling the `test_run_loop_generates_infographic` integration test in
  FEAT-308's `tests/integration/test_crew_infographic_e2e.py` (currently
  `xfail`) is a natural side-effect verification once this fix lands, but
  wiring that back in is optional polish, not a blocking acceptance
  criterion of this spec.

---

## 2. Architectural Design

### Overview

Replace the single offending direct-assignment line in `run_loop()` with
the same `object.__setattr__` escape hatch already established and
documented in `AgentNode.model_post_init()`. This is a one-line,
mechanical fix — no new abstractions, no API changes, no new dependencies.

### Component Diagram

```
AgentCrew.run_loop()
    │ (per iteration, before executing agent_sequence)
    ▼
for agent_id in agent_sequence:
    node = self.workflow_graph.get(agent_id)
    if node:
        object.__setattr__(node, "fsm", AgentTaskMachine(agent_name=node.agent.name))
                    │
                    ▼
        (same frozen-model escape hatch pattern as
         AgentNode.model_post_init(), core/node.py:222-227)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AgentCrew.run_loop()` (`parrot/bots/flows/crew/crew.py`) | modifies | Single line: `node.fsm = ...` → `object.__setattr__(node, "fsm", ...)`. |
| `CrewAgentNode` / `AgentNode` (frozen Pydantic, `core/node.py`) | uses (unchanged) | No changes to the node classes themselves. |
| `AgentTaskMachine` (`core/fsm.py`) | uses (unchanged) | Constructed identically; only the *assignment mechanism* changes. |

### Data Models

No data model changes. `AgentNode.fsm: Optional[AgentTaskMachine] = None`
(`core/node.py`) is unchanged.

### New Public Interfaces

None. This is a bug fix with no new public surface.

---

## 3. Module Breakdown

### Module 1: `run_loop()` Frozen-FSM Reset Fix
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` (extend)
- **Responsibility**: Replace the direct `node.fsm = AgentTaskMachine(...)`
  reassignment (currently ~line 1849, inside the per-iteration FSM-reset
  loop) with `object.__setattr__(node, "fsm", AgentTaskMachine(agent_name=node.agent.name))`,
  matching the established pattern in `AgentNode.model_post_init()`.
- **Depends on**: none (self-contained one-line fix).

### Module 2: Regression Tests
- **Path**: `tests/unit/test_run_loop_fsm_reset.py` (new)
- **Responsibility**: Unit tests proving `run_loop()` no longer raises
  `ValidationError` across 0/1/many agents and multiple iterations, and
  that each iteration's FSM genuinely starts fresh (state transitions
  from a prior iteration do not leak into the next).
- **Depends on**: Module 1.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_run_loop_single_agent_single_iteration` | Module 1 | 1 agent, `max_iterations=1` → completes without `ValidationError`. |
| `test_run_loop_multiple_agents_multiple_iterations` | Module 1 | 3 agents, `max_iterations=3` → all iterations complete without error. |
| `test_run_loop_fsm_is_fresh_each_iteration` | Module 1 | After iteration 1, a node's FSM is in a final state (`completed`/`failed`); after iteration 2's reset, the *same node_id*'s FSM object is a new instance starting at `idle`. |
| `test_run_flow_sequential_parallel_unaffected` | Module 1 | Regression guard: `run_flow`/`run_sequential`/`run_parallel` behavior is byte-for-byte unchanged (no FSM-reset code path touches them). |

### Integration Tests
| Test | Description |
|---|---|
| `test_run_loop_generates_infographic` (FEAT-308, `tests/integration/test_crew_infographic_e2e.py`) | Currently `xfail(strict=True)`; once this fix lands, flip to a normal (non-xfail) assertion as a natural end-to-end confirmation. Optional polish — not a blocking AC of this spec. |

### Test Data / Fixtures
```python
# Reuse the existing DummyAgent-style stub pattern already established in
# packages/ai-parrot/tests/_crew_test_helpers.py (or the equivalent
# tests/integration/conftest.py DummyAgent added by FEAT-308) — no new
# fixture infrastructure needed.
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **[G1]** `AgentCrew.run_loop()` completes at least one iteration
  without raising `pydantic_core.ValidationError`, for 0, 1, and many
  registered agents.
- [ ] **[G2]** Each iteration's FSM is verifiably fresh (starts at `idle`);
  a `completed`/`failed` FSM from a prior iteration is never reused.
- [ ] **[G3]** `run_flow`, `run_sequential`, `run_parallel` are unaffected —
  their existing test suites (`packages/ai-parrot/tests/test_crew_flow_regression.py`,
  `test_crew_sequential_regression.py`, `test_crew_parallel_regression.py`)
  continue to pass unmodified.
- [ ] All new unit tests pass (`pytest tests/unit/test_run_loop_fsm_reset.py -v`).
- [ ] No breaking changes to `AgentNode`/`CrewAgentNode`'s frozen-Pydantic
  contract or `AgentTaskMachine`'s public API.
- [ ] `ruff check` clean on all modified/new files.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified against
> `packages/ai-parrot/src/parrot/` on 2026-07-14 (import namespace `parrot`).

### Verified Imports
```python
from parrot.bots.flows.crew.crew import AgentCrew                      # crew.py:93
from parrot.bots.flows.crew.nodes import CrewAgentNode                 # nodes.py:28
from parrot.bots.flows.core.node import AgentNode                      # node.py:180
from parrot.bots.flows.core.fsm import AgentTaskMachine                # fsm.py:40
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
class AgentCrew(PersistenceMixin, SynthesisMixin):                     # L93 (approx; shifts as file grows)
    async def run_loop(
        self, initial_task: str, condition: str,
        max_iterations: int = 2, ...,
    ) -> FlowResult: ...                                                # ~L1578

    # THE BUG — per-iteration FSM reset (~L1844-1849):
    #   for agent_id in agent_sequence:
    #       node = self.workflow_graph.get(agent_id)
    #       if node:
    #           node.fsm = AgentTaskMachine(agent_name=node.agent.name)  # ← raises ValidationError
    #
    # THE FIX (mechanical, one line):
    #   node.fsm = AgentTaskMachine(agent_name=node.agent.name)
    #   →
    #   object.__setattr__(node, "fsm", AgentTaskMachine(agent_name=node.agent.name))

# packages/ai-parrot/src/parrot/bots/flows/core/node.py
class Node(BaseModel):                                                  # L67
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)  # L98

class AgentNode(Node):                                                  # L180
    agent: AgentLike                                                    # L211
    node_id: str                                                        # L212
    fsm: Optional[AgentTaskMachine] = None                              # L215
    def model_post_init(self, __context: Any) -> None:                  # L217
        # THE ESTABLISHED PATTERN (already used, already documented):
        #   object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.agent.name))  # L224-226

# packages/ai-parrot/src/parrot/bots/flows/crew/nodes.py
class CrewAgentNode(_CoreAgentNode):                                    # L28 (_CoreAgentNode == AgentNode)
    # No __init__ override; inherits AgentNode's frozen model_config and
    # fsm field verbatim. Overrides only _build_prompt()/_format().

# packages/ai-parrot/src/parrot/bots/flows/core/fsm.py
class AgentTaskMachine(StateMachine):                                   # L40
    idle = State("idle", initial=True)                                  # L67
    completed = State("completed", final=True)                          # L70  ← why a fresh FSM is needed per iteration
    def __init__(self, agent_name: str, **kwargs: object) -> None: ...  # L84
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| Fixed `run_loop()` FSM reset | `CrewAgentNode` (frozen) | `object.__setattr__(node, "fsm", ...)` | Pattern precedent: `core/node.py:222-227` |

### Does NOT Exist (Anti-Hallucination)
- ~~`AgentTaskMachine.reset()`~~ — no such method; a fresh instance is
  always constructed (both in the buggy code and in the fix).
- ~~`CrewAgentNode.__setattr__` override~~ — no custom override; the
  frozen behavior comes purely from inherited `model_config`.
- ~~Any other `node.fsm = ...` call site~~ — verified via `grep -rn
  "node.fsm = AgentTaskMachine" packages/ai-parrot/src/parrot/bots/flows/`:
  exactly one match, inside `run_loop()`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Use the EXACT `object.__setattr__(node, "fsm", AgentTaskMachine(agent_name=node.agent.name))`
  pattern already documented at `core/node.py:222-227` — do not invent a
  different mutation mechanism.
- Keep the surrounding comment (`# Fresh FSM per iteration (completed is a
  final state, so we cannot reuse the same FSM across iterations)`) — it's
  still accurate and explains *why* a fresh FSM is needed each iteration.

### Known Risks / Gotchas
- **Do not** attempt to make `AgentNode`/`CrewAgentNode` non-frozen — that
  would be a much larger architectural change (FEAT-163's B-lite shape is
  relied on elsewhere for concurrent-run safety) and is explicitly out of
  scope.
- **Do not** change `AgentTaskMachine`'s state graph — `completed` must
  remain final; the fix works *with* that constraint, not against it.
- Double-check that `workflow_graph` node lookups elsewhere in `run_loop()`
  (e.g., any FSM read/mutation of nested state like `node.fsm.schedule()`,
  `.start()`, `.succeed()`, `.fail()`) are unaffected — those mutate the FSM
  object in place and do not reassign the frozen field, so they remain
  valid after this fix.

### External Dependencies
_No new dependencies._ `python-statemachine` (already a dependency) and
`pydantic` v2 (already a dependency) are unchanged.

---

## 8. Open Questions

- [x] Root cause — *Resolved during discovery*: frozen-Pydantic
  `CrewAgentNode.fsm` field reassignment via bare `node.fsm = ...`,
  introduced by TASK-1062's migration to frozen Pydantic nodes; `run_loop`'s
  per-iteration reset was never updated to use the established
  `object.__setattr__` escape hatch. *(→ §1, §6)*
- [ ] Should the FEAT-308 `test_run_loop_generates_infographic` xfail be
  flipped back to a normal assertion in the same PR as this fix, or in a
  separate follow-up commit against FEAT-308's already-merged code? —
  *Owner: Jesus* *(non-blocking; either is acceptable)*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-14 | Jesus Lara | Initial draft — bug discovered during FEAT-308 TASK-1780, filed as a follow-up spec per user request. |

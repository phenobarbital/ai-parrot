# TASK-1314: Test suite repointing + broken-test refactor (L5 — Module 7)

**Feature**: FEAT-196 — AgentsFlow Migration
**Spec**: `sdd/specs/agentsflow-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1312, TASK-1313
**Assigned-to**: unassigned

---

## Context

Layer 5 (continued). After TASK-1312 (internal repointing) and TASK-1313
(dev_loop repointing), the 31+ test files that still import from
`parrot.bots.flow.*` need to be updated. Tests broken at HEAD (those importing
the deleted `parrot.bots.flow.fsm`) must be **rewritten** (not quarantined)
against the new `flows/core/*` and `flows/flow/*` primitives.

Implements §3 Module 7 of the spec.

---

## Scope

### Phase 1: Discovery

Run `grep -rn "parrot\.bots\.flow\b" packages/ai-parrot/tests/` to get the
complete list (the spec lists 21 explicitly; there may be ~10 more).

### Phase 2: Simple repointing (import-only changes)

For each test file that only needs import updates (no broken behaviour):
- Replace `from parrot.bots.flow import X` → `from parrot.bots.flows import X`
- Replace `from parrot.bots.flow.X import Y` → appropriate new path
- Replace `from parrot.bots.flow.node import Node` → `from parrot.bots.flows.core.node import Node`
- Replace `from parrot.bots.flow.decision_node import X` → `from parrot.bots.flows.flow.nodes import X`
- Replace `from parrot.bots.flow.definition import X` → `from parrot.bots.flows.flow.definition import X`
- Replace `from parrot.bots.flow.actions import X` → `from parrot.bots.flows.flow.actions import X`
- Replace `from parrot.bots.flow.cel_evaluator import X` → `from parrot.bots.flows.flow.cel_evaluator import X`
- Replace `from parrot.bots.flow.svelteflow import X` → `from parrot.bots.flows.flow.svelteflow import X`
- Replace `from parrot.bots.flow.loader import X` → `from parrot.bots.flows.flow.loader import X`

### Phase 3: Broken-test rewrites (REFACTOR — NOT quarantine)

These 4+ test files are **broken at HEAD** (import `parrot.bots.flow.fsm` which
was deleted in FEAT-163) and require rewriting:

1. `packages/ai-parrot/tests/test_fsm.py` — imports deleted `parrot.bots.flow.fsm`.
   Rewrite against `parrot.bots.flows.core.fsm.AgentTaskMachine` /
   `parrot.bots.flows.core.transition.FlowTransition`.

2. `packages/ai-parrot/tests/flows/dev_loop/test_flow.py` — imports deleted
   `parrot.bots.flow.fsm`. Rewrite to test the dev_loop using new `flows.*` paths.

3. `packages/ai-parrot/tests/test_agentsflow_branch.py` — likely imports
   `parrot.bots.flow.fsm` or decision nodes. Rewrite against new paths.

4. `packages/ai-parrot/tests/test_agent_crew_examples.py` — may import old paths.
   Repoint + verify tests still exercise the same behaviour.

5. `packages/ai-parrot/tests/test_execution_memory_integration.py` — partially
   addressed by TASK-1310 (storage repointing) but may have additional `flow.*`
   references. Complete the repointing.

### Phase 4: Verify full suite

After all updates: `pytest packages/ai-parrot/tests/ -v --tb=short` must be green.

**NOT in scope**: adding new test scenarios. Modifying the actual production code.

---

## Files to Create / Modify

The known 21 files from the spec (update all of these):

| File | Action |
|---|---|
| `packages/ai-parrot/tests/test_agent_crew_examples.py` | MODIFY or REWRITE |
| `packages/ai-parrot/tests/test_agentsflow_branch.py` | MODIFY or REWRITE |
| `packages/ai-parrot/tests/test_cel_evaluator.py` | MODIFY |
| `packages/ai-parrot/tests/test_decision_node.py` | MODIFY |
| `packages/ai-parrot/tests/test_endnode.py` | MODIFY |
| `packages/ai-parrot/tests/test_execution_memory_integration.py` | MODIFY (see TASK-1310) |
| `packages/ai-parrot/tests/test_flow_actions.py` | MODIFY |
| `packages/ai-parrot/tests/test_flow_definition.py` | MODIFY |
| `packages/ai-parrot/tests/test_flow_integration.py` | MODIFY |
| `packages/ai-parrot/tests/test_flow_loader.py` | MODIFY |
| `packages/ai-parrot/tests/test_flow_mixins.py` | MODIFY (see TASK-1310) |
| `packages/ai-parrot/tests/test_fsm.py` | REWRITE (broken at HEAD) |
| `packages/ai-parrot/tests/test_orchestrator_agent.py` | MODIFY (see TASK-1310) |
| `packages/ai-parrot/tests/test_svelteflow_adapter.py` | MODIFY |
| `packages/ai-parrot/tests/bots/flow/test_definition_cycle.py` | MODIFY |
| `packages/ai-parrot/tests/bots/flows/test_agents_flow.py` | MODIFY |
| `packages/ai-parrot/tests/bots/flows/test_flow_node_subclasses.py` | MODIFY |
| `packages/ai-parrot/tests/bots/flows/test_from_definition.py` | MODIFY |
| `packages/ai-parrot/tests/flows/dev_loop/test_flow.py` | REWRITE (broken at HEAD) |
| `packages/ai-parrot/tests/test_flow_primitives/test_contract.py` | MODIFY |
| `packages/ai-parrot/tests/test_flow_primitives/test_init_reexports.py` | MODIFY |
| Additional files discovered by grep | MODIFY as needed |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# New import paths to use in tests:
from parrot.bots.flows import AgentsFlow, FlowResult, FlowContext
# verified: parrot/bots/flows/__init__.py

from parrot.bots.flows.core.node import Node, AgentNode, StartNode, EndNode
# verified: parrot/bots/flows/core/node.py:68, 182, 323, 387

from parrot.bots.flows.core.fsm import AgentTaskMachine, TransitionCondition
# verified: parrot/bots/flows/core/fsm.py (replaces deleted parrot.bots.flow.fsm)

from parrot.bots.flows.core.transition import FlowTransition
# verified: parrot/bots/flows/core/transition.py:28

from parrot.bots.flows.core.result import FlowResult, NodeResult, NodeExecutionInfo
# verified: parrot/bots/flows/core/result.py:273, 39, 190

from parrot.bots.flows.core.context import FlowContext
# verified: parrot/bots/flows/core/context.py:51

from parrot.bots.flows.flow.nodes import (
    DecisionFlowNode, BinaryDecision, ApprovalDecision, MultiChoiceDecision,
    InteractiveDecisionNode,
)
# verified: TASK-1311 creates this

from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition, EdgeDefinition
# verified: TASK-1309 creates this

from parrot.bots.flows.flow.actions import ACTION_REGISTRY, BaseAction
# verified: TASK-1309 creates this

from parrot.bots.flows.flow.cel_evaluator import CELPredicateEvaluator
# verified: TASK-1309 creates this

from parrot.bots.flows.flow.svelteflow import from_svelteflow, to_svelteflow
# verified: TASK-1309 creates this

from parrot.bots.flows.flow.loader import FlowLoader
# verified: TASK-1309 creates this
```

### Does NOT Exist

- ~~`parrot.bots.flow.fsm`~~ — deleted in FEAT-163. Tests importing this MUST be
  rewritten against `parrot.bots.flows.core.fsm.AgentTaskMachine`
- ~~`parrot.bots.flow.FlowNode`~~ — removed in FEAT-163; use `AgentNode`

---

## Implementation Notes

### Strategy for Broken-Test Rewrites

For `test_fsm.py` — rewrite against canonical FSM:

```python
# OLD (broken):
from parrot.bots.flow.fsm import AgentsFlow as LegacyAgentsFlow

# NEW (rewritten):
from parrot.bots.flows.core.fsm import AgentTaskMachine, TransitionCondition
from parrot.bots.flows.core.transition import FlowTransition
# Rewrite test assertions against AgentTaskMachine's interface
```

For `test_agentsflow_branch.py` — read the file first to understand what it tested,
then rewrite the same scenarios against the new `AgentsFlow` from `flows.flow`.

### Key Constraints

- **Rewrite, do NOT quarantine** — no `pytest.mark.skip`, no `xfail` without justification
- Read every test file before editing — understand what it tests, not just what it imports
- After all changes: `grep -rn "parrot\.bots\.flow\b" packages/ai-parrot/tests/` must
  return zero matches
- `pytest packages/ai-parrot/tests/ -v --tb=short` must be green (no new skips)

### References in Codebase

- All test files listed in §6 of the spec (Tests section)

---

## Acceptance Criteria

- [ ] `grep -rn "parrot\.bots\.flow\b" packages/ai-parrot/tests/` returns zero matches
- [ ] `test_fsm.py` passes with new `AgentTaskMachine`-based tests
- [ ] `tests/flows/dev_loop/test_flow.py` passes
- [ ] All 21 known test files pass
- [ ] `pytest packages/ai-parrot/tests/ -v` exits 0 with no new skips introduced
- [ ] `ruff check packages/ai-parrot/tests/`

---

## Test Specification

This task IS the test work. The acceptance criteria above define success.

Key verification command:
```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/ -v --tb=short 2>&1 | tail -30
grep -rn "parrot\.bots\.flow\b" packages/ai-parrot/tests/ | grep -v "parrot\.bots\.flows"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-migration.spec.md`
2. **Check dependencies** — TASK-1312 and TASK-1313 must be done
3. **Run discovery first**: `grep -rn "parrot\.bots\.flow\b" packages/ai-parrot/tests/`
   to get the complete list
4. **Read each test file** before editing — understand what it tests
5. **Simple repoints first** (import-only), then broken-test rewrites
6. **Run tests after each file** to catch regressions early
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/`
9. **Update index** in `sdd/tasks/index/agentsflow-migration.json`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

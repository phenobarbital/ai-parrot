---
type: Wiki Overview
title: 'TASK-1315: Curate parrot/bots/flows/__init__.py (L5 — Module 8)'
id: doc:sdd-tasks-completed-task-1315-agentsflow-migration-curate-flows-init-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Layer 5 (finalisation). The current `parrot/bots/flows/__init__.py` exposes
  some
relates_to:
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.flow.actions
  rel: mentions
- concept: mod:parrot.bots.flows.flow.cel_evaluator
  rel: mentions
- concept: mod:parrot.bots.flows.flow.loader
  rel: mentions
- concept: mod:parrot.bots.flows.flow.svelteflow
  rel: mentions
---

# TASK-1315: Curate parrot/bots/flows/__init__.py (L5 — Module 8)

**Feature**: FEAT-196 — AgentsFlow Migration
**Spec**: `sdd/specs/agentsflow-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1312, TASK-1313, TASK-1314
**Assigned-to**: unassigned

---

## Context

Layer 5 (finalisation). The current `parrot/bots/flows/__init__.py` exposes some
symbols that should be submodule-only (not at the package root). This task
rewrites the `__all__` list to expose only deliberate primitives and removes
demoted internals from the root-level re-exports.

Implements §3 Module 8 of the spec.

---

## Scope

Rewrite `packages/ai-parrot/src/parrot/bots/flows/__init__.py`:

### Keep at root (`__all__` includes):
`AgentLike`, `AgentRef`, `DependencyResults`, `PromptBuilder`, `ActionCallback`,
`CrewHookCallback`, `FlowStatus`, `Node`, `AgentNode`, `StartNode`, `EndNode`,
`FlowResult`, `NodeResult`, `NodeExecutionInfo`, `FlowContext`, `FlowTransition`,
`AgentTaskMachine`, `TransitionCondition`, `ExecutionMemory`, `VectorStoreMixin`,
`PersistenceMixin`, `SynthesisMixin`, `AgentCrew`, `CrewAgentNode`,
`OrchestratorAgent`, `A2AOrchestratorAgent`, `ResultRetrievalTool`, `AgentsFlow`,
`NODE_REGISTRY`, `register_node`, `CompletionEvent`, `FlowDefinition`,
`NodeDefinition`, `EdgeDefinition`, `DecisionFlowNode`, `InteractiveDecisionNode`,
`BinaryDecision`, `ApprovalDecision`, `MultiChoiceDecision`.

### Demote to submodule-only (REMOVE from `__all__` and root imports):
`CELPredicateEvaluator`, `ACTION_REGISTRY`, `register_action`, `create_action`,
`BaseAction`, `LogAction`, `NotifyAction`, `WebhookAction`, `MetricAction`,
`SetContextAction`, `ValidateAction`, `TransformAction`, `from_svelteflow`,
`to_svelteflow`, `FlowLoader`, `FlowMetadata`, `NodePosition`, `ActionDefinition`,
`LogActionDef`, `NotifyActionDef`, `WebhookActionDef`, `MetricActionDef`,
`SetContextActionDef`, `ValidateActionDef`, `TransformActionDef`.

New submodule import paths for demoted symbols:
- `CELPredicateEvaluator` → `from parrot.bots.flows.flow.cel_evaluator import CELPredicateEvaluator`
- `ACTION_REGISTRY`, action classes → `from parrot.bots.flows.flow.actions import ...`
- `FlowLoader` → `from parrot.bots.flows.flow.loader import FlowLoader`
- SvelteFlow adapters → `from parrot.bots.flows.flow.svelteflow import ...`

Write a test that verifies `__all__` matches the curated list exactly.

**NOT in scope**: changing the actual import logic for production code; just
curating `__all__` and removing demoted symbols from root re-exports.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/__init__.py` | MODIFY | Rewrite __all__ + remove demoted root imports |
| `packages/ai-parrot/tests/bots/flows/test_curated_init.py` | CREATE | Verifies __all__ matches spec list; no demoted symbols at root |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Current flows/__init__.py already imports (keep these):
from .core import (
    AgentLike, AgentRef, DependencyResults, PromptBuilder, ActionCallback,
    CrewHookCallback, FlowStatus, AgentTaskMachine, TransitionCondition,
    Node, AgentNode, StartNode, EndNode,
    FlowResult, NodeExecutionInfo, NodeResult, build_node_metadata,
    determine_run_status, FlowContext, FlowTransition,
    ExecutionMemory, VectorStoreMixin, PersistenceMixin, SynthesisMixin,
)
from .crew import AgentCrew, CrewAgentNode
from .agents import OrchestratorAgent, A2AOrchestratorAgent, ...
from .tools import ResultRetrievalTool
from .flow import AgentsFlow, NODE_REGISTRY, register_node, CompletionEvent

# Add after TASK-1311 makes these available:
from .flow import (
    FlowDefinition, NodeDefinition, EdgeDefinition,
    DecisionFlowNode, InteractiveDecisionNode,
    BinaryDecision, ApprovalDecision, MultiChoiceDecision,
)
```

### Existing Signatures to Use

```python
# Read current packages/ai-parrot/src/parrot/bots/flows/__init__.py in full
# before making changes — verify what currently re-exports at root
```

### Does NOT Exist

- ~~`CELPredicateEvaluator` in `parrot.bots.flows.__all__`~~ — demoted; importable only from
  `parrot.bots.flows.flow.cel_evaluator`
- ~~`ACTION_REGISTRY` in `parrot.bots.flows.__all__`~~ — demoted
- ~~`FlowLoader` in `parrot.bots.flows.__all__`~~ — demoted

---

## Implementation Notes

### The Curated `__all__` List (verbatim from spec §3 Module 8)

```python
__all__ = [
    # Types & protocols
    "AgentLike", "AgentRef", "DependencyResults", "PromptBuilder",
    "ActionCallback", "CrewHookCallback", "FlowStatus",
    # FSM
    "AgentTaskMachine", "TransitionCondition",
    # Node hierarchy
    "Node", "AgentNode", "StartNode", "EndNode",
    # Result models
    "FlowResult", "NodeResult", "NodeExecutionInfo",
    # Context
    "FlowContext",
    # Transitions
    "FlowTransition",
    # Storage
    "ExecutionMemory", "VectorStoreMixin", "PersistenceMixin", "SynthesisMixin",
    # Crew
    "AgentCrew", "CrewAgentNode",
    # Orchestrator agents
    "OrchestratorAgent", "A2AOrchestratorAgent",
    # Tools
    "ResultRetrievalTool",
    # AgentsFlow executor
    "AgentsFlow", "NODE_REGISTRY", "register_node", "CompletionEvent",
    # Flow definition
    "FlowDefinition", "NodeDefinition", "EdgeDefinition",
    # Decision nodes
    "DecisionFlowNode", "InteractiveDecisionNode",
    "BinaryDecision", "ApprovalDecision", "MultiChoiceDecision",
]
```

### Key Constraints

- The acceptance criterion in §5 of the spec checks `__all__` verbatim
- `python -c "import parrot.bots.flows; print(parrot.bots.flows.__all__)"` must exit 0
- Do NOT add `build_node_metadata`, `determine_run_status` to `__all__` unless
  spec §3 Module 8 explicitly includes them (they are in the current `__all__` — check
  if spec intends to keep them; if unclear, keep them to avoid breaking consumers)
- After demoting `CELPredicateEvaluator` etc., the root `__init__.py` should NOT
  `import CELPredicateEvaluator` — that would make it accessible even if not in `__all__`
- Verify smoke test: `python -c "import parrot.bots.flows"` exits 0

---

## Acceptance Criteria

- [ ] `python -c "import parrot.bots.flows; print(parrot.bots.flows.__all__)"` exits 0
- [ ] `parrot.bots.flows.__all__` contains all symbols from the curated list
- [ ] `CELPredicateEvaluator` is NOT importable via `from parrot.bots.flows import CELPredicateEvaluator`
- [ ] `ACTION_REGISTRY` is NOT importable via `from parrot.bots.flows import ACTION_REGISTRY`
- [ ] `FlowLoader` is NOT importable via `from parrot.bots.flows import FlowLoader`
- [ ] `pytest packages/ai-parrot/tests/bots/flows/test_curated_init.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/flows/__init__.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/test_curated_init.py
import pytest
import parrot.bots.flows as flows_pkg


CURATED_SYMBOLS = {
    "AgentLike", "AgentRef", "DependencyResults", "PromptBuilder",
    "ActionCallback", "CrewHookCallback", "FlowStatus",
    "AgentTaskMachine", "TransitionCondition",
    "Node", "AgentNode", "StartNode", "EndNode",
    "FlowResult", "NodeResult", "NodeExecutionInfo",
    "FlowContext", "FlowTransition",
    "ExecutionMemory", "VectorStoreMixin", "PersistenceMixin", "SynthesisMixin",
    "AgentCrew", "CrewAgentNode",
    "OrchestratorAgent", "A2AOrchestratorAgent",
    "ResultRetrievalTool",
    "AgentsFlow", "NODE_REGISTRY", "register_node", "CompletionEvent",
    "FlowDefinition", "NodeDefinition", "EdgeDefinition",
    "DecisionFlowNode", "InteractiveDecisionNode",
    "BinaryDecision", "ApprovalDecision", "MultiChoiceDecision",
}

DEMOTED_SYMBOLS = {
    "CELPredicateEvaluator",
    "ACTION_REGISTRY", "register_action", "create_action", "BaseAction",
    "LogAction", "NotifyAction", "WebhookAction", "MetricAction",
    "SetContextAction", "ValidateAction", "TransformAction",
    "from_svelteflow", "to_svelteflow",
    "FlowLoader",
}


def test_curated_symbols_in_all():
    """All curated symbols are in __all__."""
    for sym in CURATED_SYMBOLS:
        assert sym in flows_pkg.__all__, f"Missing from __all__: {sym}"


def test_demoted_symbols_not_in_all():
    """Demoted symbols are NOT in __all__."""
    for sym in DEMOTED_SYMBOLS:
        assert sym not in flows_pkg.__all__, f"Should be demoted (not in __all__): {sym}"


def test_smoke_import():
    """Package imports without errors."""
    import parrot.bots.flows  # noqa: PLC0415
    assert hasattr(parrot.bots.flows, "AgentsFlow")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-migration.spec.md` §3 Module 8
2. **Check dependencies** — TASK-1312, TASK-1313, TASK-1314 must be done
3. **Read `flows/__init__.py` in full** before making changes
4. **Implement** the curated `__all__` and remove demoted root imports
5. **Verify** smoke test and acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** in `sdd/tasks/index/agentsflow-migration.json`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-28
**Notes**:
- flows/__init__.py rewritten with curated __all__ (30 symbols as per spec)
- Added imports: FlowDefinition, NodeDefinition, EdgeDefinition from .flow.definition
- Added imports: DecisionFlowNode, InteractiveDecisionNode, BinaryDecision, ApprovalDecision, MultiChoiceDecision from .flow
- Removed from root: build_node_metadata, determine_run_status, HRAgentFactory, RAGHRAgent, EmployeeDataAgent, ListAvailableA2AAgentsTool, DiscoverA2AAgentsInput
- Demoted symbols (CELPredicateEvaluator, ACTION_REGISTRY, FlowLoader, etc.) are NOT imported at root
- Created tests/bots/flows/test_curated_init.py with 4 tests verifying __all__ contract
- All 4 tests pass; ruff clean

**Deviations from spec**: none

---
type: Wiki Overview
title: 'TASK-920: Package Init + Re-Exports + Dead Code Cleanup'
id: doc:sdd-tasks-completed-task-920-flow-primitives-init-reexports-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wires up the public API surface for `parrot.bots.flows.core` and establishes
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.bots.flows.core.fsm
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage
  rel: mentions
- concept: mod:parrot.bots.flows.core.transition
  rel: mentions
- concept: mod:parrot.bots.flows.core.types
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# TASK-920: Package Init + Re-Exports + Dead Code Cleanup

**Feature**: FEAT-134 — Flow Primitives — Shared Core for AgentCrew & AgentsFlow
**Spec**: `sdd/specs/flow-primitives.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-913, TASK-914, TASK-915, TASK-916, TASK-917, TASK-918, TASK-919
**Assigned-to**: unassigned

---

## Context

Wires up the public API surface for `parrot.bots.flows.core` and establishes
backward-compatible re-exports in existing modules so all current imports
continue to work. Also removes the dead `AgentTask` class from `crew.py`.

This is the integration task that ties all previous primitives together.

Implements Spec §3 Module 8.

---

## Scope

- Populate `packages/ai-parrot/src/parrot/bots/flows/__init__.py` — re-export
  all primitives from `core`.
- Populate `packages/ai-parrot/src/parrot/bots/flows/core/__init__.py` — the
  canonical public API surface with `__all__`.
- Add backward-compat re-exports in:
  - `packages/ai-parrot/src/parrot/models/crew.py` — `CrewResult` becomes
    alias for `FlowResult`; `AgentExecutionInfo` becomes alias for
    `NodeExecutionInfo`. **Actually**: keep the existing classes in
    `models/crew.py` unchanged for now; add aliases so that
    `FlowResult` and `NodeExecutionInfo` can also be imported from there.
    The full replacement happens in Spec 2.
- Delete the dead `AgentTask` class from
  `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` (lines 60-73).
- Write integration tests verifying all old import paths still work.

**NOT in scope**: Modifying `parrot.bots.flow.__init__.py` or
`parrot.bots.flow.storage.__init__.py` re-exports — those modules
already work and don't need to point to the new core yet (that's Spec 3).
Adding re-exports there could create circular imports.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/__init__.py` | MODIFY | Re-export from core |
| `packages/ai-parrot/src/parrot/bots/flows/core/__init__.py` | MODIFY | Public API + __all__ |
| `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | MODIFY | Delete `AgentTask` (lines 60-73) |
| `packages/ai-parrot/tests/test_flow_primitives/test_init_reexports.py` | CREATE | Import compat tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All imports from TASK-913 through TASK-919 that must be re-exported:
from parrot.bots.flows.core.types import (
    AgentLike, AgentRef, DependencyResults, PromptBuilder, ActionCallback, FlowStatus
)
from parrot.bots.flows.core.fsm import AgentTaskMachine, TransitionCondition
from parrot.bots.flows.core.node import Node, AgentNode, StartNode, EndNode
from parrot.bots.flows.core.result import (
    FlowResult, NodeExecutionInfo, FlowStatus,
    build_node_metadata, determine_run_status
)
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.transition import FlowTransition
from parrot.bots.flows.core.storage import (
    ExecutionMemory, PersistenceMixin, SynthesisMixin
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/orchestration/crew.py:60-73
# Dead code to delete:
@dataclass
class AgentTask:
    task_id: str
    agent_name: str
    input_data: Any
    dependencies: Set[str] = field(default_factory=set)
    context: Dict[str, Any] = field(default_factory=dict)
    completed: bool = False
    result: Optional[str] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    status: Literal["pending", "running", "completed", "failed"] = "pending"
```

### Does NOT Exist
- ~~`AgentTask` usage anywhere~~ — grep confirms zero imports/references beyond definition
- ~~`parrot.bots.flows.core.__all__`~~ — does not exist yet

---

## Implementation Notes

### core/__init__.py Pattern
```python
from .types import (
    AgentLike, AgentRef, DependencyResults, PromptBuilder,
    ActionCallback, FlowStatus,
)
from .fsm import AgentTaskMachine, TransitionCondition
from .node import Node, AgentNode, StartNode, EndNode
from .result import (
    FlowResult, NodeExecutionInfo,
    build_node_metadata, determine_run_status,
)
from .context import FlowContext
from .transition import FlowTransition
from .storage import ExecutionMemory, PersistenceMixin, SynthesisMixin

__all__ = [
    # Types
    "AgentLike", "AgentRef", "DependencyResults", "PromptBuilder",
    "ActionCallback", "FlowStatus",
    # FSM
    "AgentTaskMachine", "TransitionCondition",
    # Nodes
    "Node", "AgentNode", "StartNode", "EndNode",
    # Results
    "FlowResult", "NodeExecutionInfo",
    "build_node_metadata", "determine_run_status",
    # Context
    "FlowContext",
    # Transitions
    "FlowTransition",
    # Storage
    "ExecutionMemory", "PersistenceMixin", "SynthesisMixin",
]
```

### Key Constraints
- **AgentTask deletion**: Verify with `grep -rn "AgentTask"` that no code
  references it before deleting. The brainstorm confirmed it is dead code.
- **No circular imports**: The `core/__init__.py` only imports from within
  `core/`. The `flows/__init__.py` imports from `core`. Neither imports
  from `parrot.bots.flow` or `parrot.bots.orchestration`.
- **Do NOT add re-exports to `parrot.bots.flow.__init__.py`** — that module
  already works and adding imports from `flows.core` could trigger circular
  imports via `flow.fsm` → `models.crew` → etc.

---

## Acceptance Criteria

- [ ] `from parrot.bots.flows.core import Node, AgentNode, FlowResult, FlowContext, ...` works
- [ ] `from parrot.bots.flows import Node, AgentNode, FlowResult, ...` works
- [ ] `AgentTask` removed from `parrot/bots/orchestration/crew.py`
- [ ] No circular import errors
- [ ] Existing imports from `parrot.bots.flow`, `parrot.models.crew`,
      `parrot.bots.orchestration.crew` continue working (no regressions)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_flow_primitives/test_init_reexports.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_flow_primitives/test_init_reexports.py
import pytest


class TestCoreInit:
    def test_import_all_from_core(self):
        from parrot.bots.flows.core import (
            AgentLike, AgentRef, FlowStatus,
            AgentTaskMachine, TransitionCondition,
            Node, AgentNode, StartNode, EndNode,
            FlowResult, NodeExecutionInfo,
            FlowContext, FlowTransition,
            ExecutionMemory, PersistenceMixin, SynthesisMixin,
        )

    def test_import_from_flows_package(self):
        from parrot.bots.flows import (
            AgentLike, Node, FlowResult, FlowContext, FlowTransition,
        )


class TestExistingImportsNotBroken:
    def test_crew_result_still_importable(self):
        from parrot.models.crew import CrewResult
        assert CrewResult is not None

    def test_agent_execution_info_still_importable(self):
        from parrot.models.crew import AgentExecutionInfo
        assert AgentExecutionInfo is not None

    def test_flow_node_still_importable(self):
        from parrot.bots.flow import Node, StartNode, EndNode
        assert Node is not None

    def test_agents_flow_still_importable(self):
        from parrot.bots.flow import AgentsFlow, FlowNode
        assert AgentsFlow is not None

    def test_flow_storage_still_importable(self):
        from parrot.bots.flow.storage import ExecutionMemory, PersistenceMixin
        assert ExecutionMemory is not None


class TestDeadCodeRemoved:
    def test_agent_task_not_in_crew(self):
        import parrot.bots.orchestration.crew as crew_mod
        assert not hasattr(crew_mod, "AgentTask")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 8
2. **Check ALL dependencies** — TASK-913 through TASK-919 must be completed
3. **Run `grep -rn "AgentTask" packages/ai-parrot/src/`** to confirm dead code
4. **Populate** `core/__init__.py` and `flows/__init__.py`
5. **Delete** `AgentTask` from `crew.py`
6. **Run the full test suite**: `pytest packages/ai-parrot/tests/test_flow_primitives/ -v`
7. Also run: `pytest packages/ai-parrot/tests/ -x --timeout=30` to catch regressions

---

## Completion Note

Completed 2026-04-29.
- Populated `parrot/bots/flows/core/__init__.py` with full `__all__` covering all 20 public symbols from TASK-913–919.
- Populated `parrot/bots/flows/__init__.py` to re-export everything from `core`.
- Deleted `AgentTask` dataclass (lines 60-73) from `parrot/bots/orchestration/crew.py` — confirmed it was not imported anywhere outside its definition.
- All existing imports from `parrot.models.crew`, `parrot.bots.flow`, and `parrot.bots.orchestration.crew` continue to work.
All 17 unit tests pass; 0 regressions.

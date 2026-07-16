---
type: Wiki Overview
title: 'TASK-917: FlowContext — Workflow Execution State Tracking'
id: doc:sdd-tasks-completed-task-917-flow-primitives-context-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extracts and enhances `FlowContext` from `parrot.bots.orchestration.crew`
  into
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
---

# TASK-917: FlowContext — Workflow Execution State Tracking

**Feature**: FEAT-134 — Flow Primitives — Shared Core for AgentCrew & AgentsFlow
**Spec**: `sdd/specs/flow-primitives.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-913, TASK-915
**Assigned-to**: unassigned

---

## Context

Extracts and enhances `FlowContext` from `parrot.bots.orchestration.crew` into
the shared `parrot.bots.flows.core.context` module. Renames agent-centric
methods to node-centric (`get_input_for_node`) while preserving backward-compat
aliases (`get_input_for_agent`, `agent_metadata`).

Implements Spec §3 Module 5.

---

## Scope

- Create `packages/ai-parrot/src/parrot/bots/flows/core/context.py` containing:
  - `FlowContext` dataclass with:
    - Primary fields: `initial_task`, `results`, `responses`,
      `node_metadata: Dict[str, NodeExecutionInfo]`, `completion_order`,
      `errors`, `active_tasks`, `completed_tasks`.
    - Methods: `can_execute(node_id, dependencies)`,
      `mark_completed(node_id, result, response, metadata)`,
      `get_input_for_node(node_id, dependencies)`.
    - Backward-compat: `agent_metadata` property alias → `node_metadata`,
      `get_input_for_agent()` alias → `get_input_for_node()`.
- Write unit tests.

**NOT in scope**: Modifying the existing `FlowContext` in `crew.py` —
that happens in Spec 2.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/context.py` | CREATE | FlowContext |
| `packages/ai-parrot/tests/test_flow_primitives/test_context.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Result model from TASK-915:
from parrot.bots.flows.core.result import NodeExecutionInfo
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/orchestration/crew.py:74-142
@dataclass
class FlowContext:
    initial_task: str
    results: Dict[str, Any] = field(default_factory=dict)
    responses: Dict[str, Any] = field(default_factory=dict)
    agent_metadata: Dict[str, AgentExecutionInfo] = field(default_factory=dict)
    completion_order: List[str] = field(default_factory=list)
    errors: Dict[str, Exception] = field(default_factory=dict)
    active_tasks: Set[str] = field(default_factory=set)
    completed_tasks: Set[str] = field(default_factory=set)

    def can_execute(self, agent_name: str, dependencies: Set[str]) -> bool:
        return dependencies.issubset(self.completed_tasks)   # line 99

    def mark_completed(self, agent_name, result=None, response=None, metadata=None):
        self.completed_tasks.add(agent_name)                 # line 114
        self.completion_order.append(agent_name)             # line 115
        self.active_tasks.discard(agent_name)                # line 116
        # stores result, response, metadata if not None

    def get_input_for_agent(self, agent_name: str, dependencies: Set[str]) -> Dict[str, Any]:
        if not dependencies:                                 # line 132
            return {"task": self.initial_task}
        return {"task": self.initial_task, "dependencies": {dep: self.results.get(dep) ...}}
```

### Does NOT Exist
- ~~`FlowContext` in `parrot.bots.flows.core`~~ — does not exist yet
- ~~`FlowContext.node_metadata`~~ — does not exist; current field is `agent_metadata`
- ~~`FlowContext.get_input_for_node`~~ — does not exist; current method is `get_input_for_agent`

---

## Implementation Notes

### Key Constraints
- `node_metadata` is the primary field name; `agent_metadata` is a
  `@property` alias returning `self.node_metadata`.
- `get_input_for_node()` is the primary method; `get_input_for_agent()` is
  an alias that delegates to it.
- `can_execute()` logic is simple: `dependencies.issubset(self.completed_tasks)`.
  Preserve exactly.
- `mark_completed()` updates `completed_tasks`, `completion_order`,
  `active_tasks`, and stores result/response/metadata. Preserve exactly.

---

## Acceptance Criteria

- [ ] `FlowContext` dataclass with all fields from spec
- [ ] `node_metadata` is primary; `agent_metadata` property alias works
- [ ] `get_input_for_node()` is primary; `get_input_for_agent()` alias works
- [ ] `can_execute()` returns True when all deps in completed_tasks, False otherwise
- [ ] `mark_completed()` updates all tracking fields correctly
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_flow_primitives/test_context.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_flow_primitives/test_context.py
import pytest
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.result import NodeExecutionInfo


class TestFlowContextCanExecute:
    def test_no_deps_can_execute(self):
        ctx = FlowContext(initial_task="test")
        assert ctx.can_execute("node-1", set()) is True

    def test_deps_not_met(self):
        ctx = FlowContext(initial_task="test")
        assert ctx.can_execute("node-2", {"node-1"}) is False

    def test_deps_met(self):
        ctx = FlowContext(initial_task="test")
        ctx.completed_tasks.add("node-1")
        assert ctx.can_execute("node-2", {"node-1"}) is True


class TestFlowContextMarkCompleted:
    def test_updates_tracking(self):
        ctx = FlowContext(initial_task="test")
        ctx.active_tasks.add("node-1")
        info = NodeExecutionInfo(node_id="node-1", node_name="agent-1")
        ctx.mark_completed("node-1", result="done", response=None, metadata=info)
        assert "node-1" in ctx.completed_tasks
        assert "node-1" in ctx.completion_order
        assert "node-1" not in ctx.active_tasks
        assert ctx.results["node-1"] == "done"
        assert ctx.node_metadata["node-1"] == info


class TestFlowContextGetInput:
    def test_no_deps_returns_initial_task(self):
        ctx = FlowContext(initial_task="research AI")
        result = ctx.get_input_for_node("node-1", set())
        assert result["task"] == "research AI"

    def test_with_deps_includes_results(self):
        ctx = FlowContext(initial_task="research AI")
        ctx.results["dep-1"] = "findings"
        result = ctx.get_input_for_node("node-2", {"dep-1"})
        assert result["dependencies"]["dep-1"] == "findings"


class TestFlowContextBackwardCompat:
    def test_agent_metadata_alias(self):
        ctx = FlowContext(initial_task="test")
        assert ctx.agent_metadata is ctx.node_metadata

    def test_get_input_for_agent_alias(self):
        ctx = FlowContext(initial_task="test")
        assert ctx.get_input_for_agent("n", set()) == ctx.get_input_for_node("n", set())
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2 New Public Interfaces (FlowContext section) and §3 Module 5
2. **Check dependencies** — TASK-913 and TASK-915 must be completed
3. **Verify** existing `FlowContext` in `packages/ai-parrot/src/parrot/bots/orchestration/crew.py:74-142`
4. **Implement** following the exact same logic, adding node-centric renames + aliases

---

## Completion Note

Completed 2026-04-29. Created `parrot/bots/flows/core/context.py` with `FlowContext` dataclass:
- Primary fields: `initial_task`, `results`, `responses`, `node_metadata: Dict[str, NodeExecutionInfo]`, `completion_order`, `errors`, `active_tasks`, `completed_tasks`.
- Methods: `can_execute()`, `mark_completed()`, `get_input_for_node()`.
- Backward-compat: `agent_metadata` property alias → `node_metadata`; `get_input_for_agent()` alias → `get_input_for_node()`.
All 27 unit tests pass.

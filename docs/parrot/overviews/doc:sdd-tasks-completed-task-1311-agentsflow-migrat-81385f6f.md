---
type: Wiki Overview
title: 'TASK-1311: flows/flow/nodes.py — decision + interactive nodes (L3 — Module
  4)'
id: doc:sdd-tasks-completed-task-1311-agentsflow-migration-decision-nodes-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Layer 3 of the migration. The legacy `parrot/bots/flow/decision_node.py`
  (1,140 LoC)
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.core.types
  rel: mentions
- concept: mod:parrot.bots.flows.flow.nodes
  rel: mentions
---

# TASK-1311: flows/flow/nodes.py — decision + interactive nodes (L3 — Module 4)

**Feature**: FEAT-196 — AgentsFlow Migration
**Spec**: `sdd/specs/agentsflow-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1308
**Assigned-to**: unassigned

---

## Context

Layer 3 of the migration. The legacy `parrot/bots/flow/decision_node.py` (1,140 LoC)
and `parrot/bots/flow/interactive_node.py` (99 LoC) implement the decision-flow
nodes using the old `parrot.bots.flow.node.Node` base. This task rewrites them as
subclasses of `parrot.bots.flows.core.node.AgentNode` (or `Node` for non-agent
decisions), collecting everything in a single `flows/flow/nodes.py` module that
mirrors `flows/crew/nodes.py`.

Public symbol names and attribute shapes are preserved exactly (behavioural contract
preservation). Internals adopt `NodeResult`, `FlowContext.shared_data`, and
`build_node_metadata`.

Implements §3 Module 4 of the spec.

---

## Scope

- Create `packages/ai-parrot/src/parrot/bots/flows/flow/nodes.py` with all 10 public
  types rewritten on canonical bases:
  - `DecisionFlowNode` — subclass of `AgentNode` (from `flows/core/node`)
  - `DecisionResult` — dataclass/model (preserve existing shape)
  - `DecisionMode` — enum (preserve)
  - `DecisionType` — enum (preserve)
  - `DecisionNodeConfig` — Pydantic model (preserve)
  - `BinaryDecision` — subclass of `DecisionFlowNode` (preserve)
  - `ApprovalDecision` — subclass of `DecisionFlowNode` (preserve)
  - `MultiChoiceDecision` — subclass of `DecisionFlowNode` (preserve)
  - `EscalationPolicy` — model/enum (preserve)
  - `VoteWeight` — model/enum (preserve)
  - `InteractiveDecisionNode` — subclass of `Node` or `AgentNode` (preserve public surface)

- Internals adopt:
  - `NodeResult` for per-node output
  - `FlowContext.shared_data` for shared run state
  - `build_node_metadata` / `NodeExecutionInfo` for telemetry

- Update `packages/ai-parrot/src/parrot/bots/flows/flow/__init__.py` to
  re-export the public Decision* / Interactive* types from `.nodes`

- Write freeze-test and contract tests (§4 of spec)

- Do NOT delete `parrot/bots/flow/decision_node.py` or `interactive_node.py` here
  — removal is in TASK-1316

**NOT in scope**: updating `flows/flow/flow.py` to import from `.nodes`
(that's TASK-1312). Not touching `actions.py`, `definition.py`, or storage.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/flow/nodes.py` | CREATE | Rewritten DecisionFlowNode family + InteractiveDecisionNode |
| `packages/ai-parrot/src/parrot/bots/flows/flow/__init__.py` | MODIFY | Add re-exports for Decision* / Interactive* types |
| `packages/ai-parrot/tests/bots/flows/test_decision_node_contract.py` | CREATE | Freeze-tests + inheritance tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Canonical base classes (already exist — use verbatim):
from parrot.bots.flows.core.node import Node, AgentNode
# verified: parrot/bots/flows/core/node.py:68, 182

# Result / context models (already exist):
from parrot.bots.flows.core.result import (
    NodeResult, NodeExecutionInfo, build_node_metadata,
)
# verified: parrot/bots/flows/core/result.py:39, 190, 527

from parrot.bots.flows.core.context import FlowContext
# verified: parrot/bots/flows/core/context.py:51

# Dependency type:
from parrot.bots.flows.core.types import DependencyResults
# verified: parrot/bots/flows/core/types.py (check line)
```

### Existing Signatures to Use

```python
# parrot/bots/flows/core/node.py:68
class Node(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    node_id: str
    # _pre_actions, _post_actions: PrivateAttr lists (mutable, frozen-safe)

# parrot/bots/flows/core/node.py:182
class AgentNode(Node):
    node_id: str                                    # line 218
    def _build_prompt(                              # line 238
        self, ctx: "FlowContext", deps: DependencyResults,
    ) -> str: ...
    async def execute(                              # line 270
        self, ctx: "FlowContext", deps: DependencyResults, **kwargs: Any,
    ) -> Any: ...

# parrot/bots/flows/core/result.py:39
@dataclass
class NodeResult:
    node_id: str
    node_name: str
    task: str
    result: Any
    ai_message: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    parent_execution_id: Optional[str] = None
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))

# parrot/bots/flows/core/context.py:51
@dataclass
class FlowContext:
    node_metadata: Dict[str, NodeExecutionInfo] = field(default_factory=dict)
    shared_data: Dict[str, Any] = field(default_factory=dict)
    agent_registry: Optional["AgentRegistry"] = field(default=None)
    def can_execute(self, _node_id: str, dependencies: Set[str]) -> bool: ...
    def mark_completed(...) -> None: ...
    def mark_failed(...) -> None: ...
```

### Does NOT Exist

- ~~`parrot.bots.flow.node.Node`~~ — old base; use `parrot.bots.flows.core.node.Node`
- ~~`parrot.bots.flow.fsm`~~ — deleted in FEAT-163
- ~~`parrot.bots.flows.flow.nodes.py`~~ before this task runs
- ~~Per-decision-type file split~~ (`flows/nodes/decision/{base,binary,...}.py`) — rejected;
  ALL decision types live in a single `flows/flow/nodes.py`

---

## Implementation Notes

### Pattern to Follow

Mirror `parrot/bots/flows/crew/nodes.py` — single file, all crew-related node types.

The decision nodes are **frozen Pydantic** subclasses of `AgentNode` or `Node`.
Frozen means:
- No `self.field = value` in methods
- Mutable per-run state goes in `FlowContext.shared_data` keyed by `node_id`
- Or use `PrivateAttr` lists for lists that need appending

```python
# pattern from source decision_node.py (adapted for new base):
class DecisionFlowNode(AgentNode):
    """Decision node that evaluates conditions and routes flow."""
    # Preserve all public attributes from old decision_node.py
    # Replace: old Node base -> AgentNode
    # Replace: old AgentResult/custom result -> NodeResult
    # Replace: custom context dict -> FlowContext.shared_data

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any,
    ) -> NodeResult:
        # ... decision logic using ctx.shared_data
        return NodeResult(
            node_id=self.node_id,
            node_name=self.name,
            task=self.task,
            result=decision_result,
            metadata=build_node_metadata(...),
        )
```

### Key Constraints

- Read `parrot/bots/flow/decision_node.py` in full before writing — understand
  every method and attribute before reimplementing
- Read `parrot/bots/flow/interactive_node.py` in full before writing
- The freeze-test captures the **current** public surface; the rewrite must
  reproduce all listed attributes/methods exactly
- Node base is frozen Pydantic: store mutable per-run state in
  `FlowContext.shared_data[self.node_id]` or `PrivateAttr` lists, NOT as fields
- All I/O methods must be `async def`
- Use `self.logger` for logging (provided by `Node` base via `model_post_init`)

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flow/decision_node.py` — 1,140 LoC source
- `packages/ai-parrot/src/parrot/bots/flow/interactive_node.py` — 99 LoC source
- `packages/ai-parrot/src/parrot/bots/flows/crew/nodes.py` — mirror pattern
- `packages/ai-parrot/src/parrot/bots/flows/core/node.py` — AgentNode base

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/bots/flows/flow/nodes.py` exists
- [ ] `from parrot.bots.flows.flow.nodes import (DecisionFlowNode, DecisionResult, DecisionMode, DecisionType, DecisionNodeConfig, BinaryDecision, ApprovalDecision, MultiChoiceDecision, EscalationPolicy, VoteWeight, InteractiveDecisionNode)` all succeed
- [ ] `issubclass(DecisionFlowNode, AgentNode)` is True (or `issubclass(DecisionFlowNode, Node)`)
- [ ] `issubclass(BinaryDecision, DecisionFlowNode)` is True
- [ ] `issubclass(ApprovalDecision, DecisionFlowNode)` is True
- [ ] `issubclass(MultiChoiceDecision, DecisionFlowNode)` is True
- [ ] Freeze-test passes — all public attributes from old `decision_node.py` present
- [ ] `pytest packages/ai-parrot/tests/bots/flows/test_decision_node_contract.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/flows/flow/nodes.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/test_decision_node_contract.py
import pytest
from parrot.bots.flows.core.node import AgentNode, Node


EXPECTED_DECISION_SYMBOLS = {
    "DecisionFlowNode", "DecisionResult", "DecisionMode",
    "DecisionType", "DecisionNodeConfig", "BinaryDecision",
    "ApprovalDecision", "MultiChoiceDecision", "EscalationPolicy",
    "VoteWeight",
}


def test_all_decision_symbols_importable():
    """All expected decision symbols are importable from flows.flow.nodes."""
    import parrot.bots.flows.flow.nodes as nodes_module  # noqa: PLC0415
    for sym in EXPECTED_DECISION_SYMBOLS:
        assert hasattr(nodes_module, sym), f"Missing: {sym}"


def test_interactive_decision_node_importable():
    from parrot.bots.flows.flow.nodes import InteractiveDecisionNode  # noqa: PLC0415
    assert InteractiveDecisionNode is not None


def test_decision_flow_node_inherits_canonical_base():
    from parrot.bots.flows.flow.nodes import DecisionFlowNode  # noqa: PLC0415
    assert issubclass(DecisionFlowNode, (Node, AgentNode))


def test_binary_decision_is_subclass():
    from parrot.bots.flows.flow.nodes import BinaryDecision, DecisionFlowNode  # noqa: PLC0415
    assert issubclass(BinaryDecision, DecisionFlowNode)


def test_approval_decision_is_subclass():
    from parrot.bots.flows.flow.nodes import ApprovalDecision, DecisionFlowNode  # noqa: PLC0415
    assert issubclass(ApprovalDecision, DecisionFlowNode)


def test_multichoice_decision_is_subclass():
    from parrot.bots.flows.flow.nodes import MultiChoiceDecision, DecisionFlowNode  # noqa: PLC0415
    assert issubclass(MultiChoiceDecision, DecisionFlowNode)


def test_node_inheritance_chain():
    """Decision nodes ultimately subclass the canonical Node base."""
    from parrot.bots.flows.flow.nodes import DecisionFlowNode  # noqa: PLC0415
    mro_names = [c.__name__ for c in DecisionFlowNode.__mro__]
    assert "Node" in mro_names or "AgentNode" in mro_names
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-migration.spec.md`
2. **Check dependencies** — TASK-1308 must be in `sdd/tasks/completed/`
3. **Read source files** `parrot/bots/flow/decision_node.py` and
   `parrot/bots/flow/interactive_node.py` in full before writing a single line
4. **Capture the public surface** as the freeze-test fixture
5. **Implement** the rewrite following the scope and patterns above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** in `sdd/tasks/index/agentsflow-migration.json`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-05-28
**Notes**: Created `flows/flow/nodes.py` (1,170 LoC) with all 11 public types rewritten as
frozen Pydantic subclasses of `parrot.bots.flows.core.node.Node`. `DecisionFlowNode`
implements CIO, BALLOT, and CONSENSUS decision modes with escalation to HITL.
`InteractiveDecisionNode` wraps questionary CLI prompt. Fixed `build_node_metadata` return
value to use `.to_dict()` before passing to `NodeResult.metadata: Dict[str, Any]`. Removed
3 unused imports caught by ruff. All 19 contract tests pass.

**Deviations from spec**: none

---
type: Wiki Overview
title: 'TASK-976: Add `shared_data` to FlowContext + introduce `NodeResult`'
id: doc:sdd-tasks-completed-task-976-add-shared-data-and-noderesult-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: from dataclasses import dataclass, field
relates_to:
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# TASK-976: Add `shared_data` to FlowContext + introduce `NodeResult`

**Feature**: FEAT-143 — Flows Consolidation
**Spec**: `sdd/specs/flows-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Spec Module 4. The core primitives in `flows.core` must be extended before
> any crew code can be moved. `FlowContext` needs a `shared_data` field so it
> can replace `AgentContext` in AgentCrew. `NodeResult` replaces `AgentResult`
> as the unified per-node execution record for `ExecutionMemory` and FAISS
> vectorization across all flow engines.

---

## Scope

- Add `shared_data: Dict[str, Any] = field(default_factory=dict)` to `FlowContext`
- Create `NodeResult` dataclass in `flows/core/result.py` (port from
  `AgentResult` in `parrot.models.crew` with node-centric naming)
- Add backward-compat `agent_id`/`agent_name` property aliases to `NodeResult`
- Port the `to_text()` method verbatim from `AgentResult`
- Update `ExecutionMemory` type annotations: `AgentResult` → `NodeResult`
- Update `VectorStoreMixin` type annotations: `AgentResult` → `NodeResult`
- Update `flows/core/storage/__init__.py` if needed to export `NodeResult`
- Export `NodeResult` from `flows/core/__init__.py` and `flows/__init__.py`

**NOT in scope**: Moving `AgentCrew`, changing crew.py, moving any files from
`orchestration/`. Only core primitives are modified here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/context.py` | MODIFY | Add `shared_data` field |
| `packages/ai-parrot/src/parrot/bots/flows/core/result.py` | MODIFY | Add `NodeResult` dataclass |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/memory.py` | MODIFY | `AgentResult` → `NodeResult` |
| `packages/ai-parrot/src/parrot/bots/flows/core/storage/mixin.py` | MODIFY | `AgentResult` → `NodeResult` |
| `packages/ai-parrot/src/parrot/bots/flows/core/__init__.py` | MODIFY | Export `NodeResult` |
| `packages/ai-parrot/src/parrot/bots/flows/__init__.py` | MODIFY | Export `NodeResult` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# flows.core.context (verified: packages/ai-parrot/src/parrot/bots/flows/core/context.py:19-20)
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

# flows.core.result (verified: packages/ai-parrot/src/parrot/bots/flows/core/result.py:15-16)
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

# storage/memory.py imports AgentResult (verified: line 12)
from .....models.crew import AgentResult

# storage/mixin.py imports AgentResult + VectorStoreProtocol (verified: line 12)
from .....models.crew import AgentResult, VectorStoreProtocol
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/context.py:26-62
@dataclass
class FlowContext:
    initial_task: str
    results: Dict[str, Any] = field(default_factory=dict)
    responses: Dict[str, Any] = field(default_factory=dict)
    node_metadata: Dict[str, NodeExecutionInfo] = field(default_factory=dict)
    completion_order: List[str] = field(default_factory=list)
    errors: Dict[str, Exception] = field(default_factory=dict)
    active_tasks: Set[str] = field(default_factory=set)
    completed_tasks: Set[str] = field(default_factory=set)
    # NEW: shared_data goes here ↑

# packages/ai-parrot/src/parrot/models/crew.py:385-446 — AgentResult to port
@dataclass
class AgentResult:
    agent_id: str
    agent_name: str
    task: str
    result: Any
    ai_message: Optional['AIMessage'] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    parent_execution_id: Optional[str] = None
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    def to_text(self) -> str: ...  # lines 399-446

# packages/ai-parrot/src/parrot/bots/flows/core/storage/memory.py:17
@dataclass
class ExecutionMemory(VectorStoreMixin):
    results: Dict[str, AgentResult] = field(default_factory=dict)  # line 31
    # add_result method uses AgentResult

# packages/ai-parrot/src/parrot/bots/flows/core/storage/mixin.py:15
class VectorStoreMixin:
    _vector_chunks: List[Tuple[str, str]] = []  # (chunk_text, agent_id) — line 30
```

### Does NOT Exist
- ~~`FlowContext.shared_data`~~ — does not exist yet (this task creates it)
- ~~`NodeResult`~~ — does not exist yet (this task creates it)
- ~~`flows.core.result.NodeResult`~~ — does not exist yet
- ~~`FlowContext.agent_results`~~ — does NOT exist; use `FlowContext.results`

---

## Implementation Notes

### Pattern to Follow
```python
# NodeResult in flows/core/result.py — port from AgentResult with renaming
@dataclass
class NodeResult:
    """Per-node execution record for storage and vectorization."""
    node_id: str
    node_name: str
    task: str
    result: Any
    ai_message: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    parent_execution_id: Optional[str] = None
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def agent_id(self) -> str: return self.node_id
    @property
    def agent_name(self) -> str: return self.node_name

    def to_text(self) -> str:
        # Copy verbatim from AgentResult.to_text() — replace self.agent_name
        # with self.node_name (same value via property but cleaner)
        ...

# FlowContext — add shared_data after completed_tasks field
@dataclass
class FlowContext:
    ...
    completed_tasks: Set[str] = field(default_factory=set)
    shared_data: Dict[str, Any] = field(default_factory=dict)
    """Arbitrary key-value data shared across all nodes."""
```

### Key Constraints
- `NodeResult.to_text()` must import `pandas.DataFrame` lazily (same as `AgentResult`)
- `NodeResult.to_text()` references `json_encoder` from `datamodel.parsers.json`
- `ExecutionMemory.results` type changes from `Dict[str, AgentResult]` to `Dict[str, NodeResult]`
- `VectorStoreMixin` references `AgentResult` in type hints and `VectorStoreProtocol` — update type hints to `NodeResult` but keep `VectorStoreProtocol` import
- `shared_data` must be a field with `default_factory=dict` (not a default `{}`)

### References in Codebase
- `parrot/models/crew.py:385-446` — `AgentResult` source to port
- `parrot/bots/flows/core/storage/memory.py` — `ExecutionMemory` to update
- `parrot/bots/flows/core/storage/mixin.py` — `VectorStoreMixin` to update

---

## Acceptance Criteria

- [ ] `from parrot.bots.flows.core.result import NodeResult` works
- [ ] `from parrot.bots.flows.core import NodeResult` works
- [ ] `from parrot.bots.flows import NodeResult` works
- [ ] `NodeResult` has `node_id`, `node_name`, `task`, `result`, `to_text()`, `agent_id` (property), `agent_name` (property)
- [ ] `FlowContext(initial_task="x", shared_data={"k": "v"})` works
- [ ] `FlowContext(initial_task="x").shared_data == {}`
- [ ] `ExecutionMemory` type annotations use `NodeResult`
- [ ] No import of `AgentResult` remains in `flows/core/storage/memory.py`
- [ ] No import of `AgentResult` remains in `flows/core/storage/mixin.py`

---

## Test Specification

```python
# tests/unit/test_noderesult_and_shared_data.py
import pytest
from parrot.bots.flows.core.result import NodeResult
from parrot.bots.flows.core.context import FlowContext


class TestNodeResult:
    def test_import(self):
        from parrot.bots.flows.core import NodeResult as NR
        assert NR is NodeResult

    def test_basic_construction(self):
        nr = NodeResult(node_id="n1", node_name="Agent1", task="do stuff", result="ok")
        assert nr.node_id == "n1"
        assert nr.node_name == "Agent1"
        assert nr.task == "do stuff"
        assert nr.result == "ok"

    def test_backward_compat_aliases(self):
        nr = NodeResult(node_id="n1", node_name="Agent1", task="t", result="r")
        assert nr.agent_id == "n1"
        assert nr.agent_name == "Agent1"

    def test_to_text_string_result(self):
        nr = NodeResult(node_id="n1", node_name="Agent1", task="t", result="hello world")
        text = nr.to_text()
        assert "Agent1" in text or "n1" in text
        assert "hello world" in text

    def test_to_text_dict_result(self):
        nr = NodeResult(node_id="n1", node_name="Agent1", task="t", result={"key": "value"})
        text = nr.to_text()
        assert "key" in text

    def test_execution_id_generated(self):
        nr = NodeResult(node_id="n1", node_name="Agent1", task="t", result="r")
        assert nr.execution_id is not None
        assert len(nr.execution_id) > 0


class TestFlowContextSharedData:
    def test_default_empty(self):
        ctx = FlowContext(initial_task="test")
        assert ctx.shared_data == {}

    def test_explicit_shared_data(self):
        ctx = FlowContext(initial_task="test", shared_data={"user_id": "u1"})
        assert ctx.shared_data["user_id"] == "u1"

    def test_mutable_shared_data(self):
        ctx = FlowContext(initial_task="test")
        ctx.shared_data["new_key"] = "new_value"
        assert ctx.shared_data["new_key"] == "new_value"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none; it can start immediately
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists
   - Confirm `FlowContext` and `AgentResult` signatures match
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-976-add-shared-data-and-noderesult.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

---

## Completion Note (filled)

**Completed by**: sdd-worker agent
**Date**: 2026-05-04
**Notes**: Added `shared_data: Dict[str, Any] = field(default_factory=dict)` to FlowContext. Created `NodeResult` dataclass in `flows/core/result.py` with node-centric naming (`node_id`/`node_name`), backward-compat `agent_id`/`agent_name` property aliases, and `to_text()` for FAISS vectorization. Updated `ExecutionMemory` and `VectorStoreMixin` to use `NodeResult` instead of `AgentResult`. Exported `NodeResult` from both `flows/core/__init__.py` and `flows/__init__.py`. All 6 files modified as specified.

**Deviations from spec**: none

---
type: Wiki Overview
title: 'TASK-915: Result Models — FlowResult, NodeExecutionInfo, FlowStatus Utilities'
id: doc:sdd-tasks-completed-task-915-flow-primitives-result-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Creates `FlowResult` (replacing `CrewResult`) and `NodeExecutionInfo` (replacing
relates_to:
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.core.types
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# TASK-915: Result Models — FlowResult, NodeExecutionInfo, FlowStatus Utilities

**Feature**: FEAT-134 — Flow Primitives — Shared Core for AgentCrew & AgentsFlow
**Spec**: `sdd/specs/flow-primitives.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-913
**Assigned-to**: unassigned

---

## Context

Creates `FlowResult` (replacing `CrewResult`) and `NodeExecutionInfo` (replacing
`AgentExecutionInfo`) in the shared core module. These are the canonical result
models that both orchestration engines will produce.

`AgentResult` stays in `parrot.models.crew` per brainstorm D11.

Implements Spec §3 Module 4.

---

## Scope

- Create `packages/ai-parrot/src/parrot/bots/flows/core/result.py` containing:
  - `NodeExecutionInfo` — all fields from `AgentExecutionInfo` with renamed
    primaries (`node_id`, `node_name`) and backward-compat aliases
    (`agent_id`, `agent_name`).
  - `FlowResult` — all fields from `CrewResult` with `nodes` as primary field
    (was `agents`), backward-compat aliases (`.agents`, `.agent_results`,
    `.content`, `.success`, `.completed`, `.failed`), `to_dict()`, and
    `__getitem__` support.
  - `build_node_metadata()` — adapted from `build_agent_metadata()`.
  - `determine_run_status()` — copied from `parrot.models.crew`.
- Write unit tests.

**NOT in scope**: Moving `AgentResult` (stays in `parrot.models.crew`),
modifying `parrot.models.crew` (re-exports are TASK-920).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/result.py` | CREATE | Result models |
| `packages/ai-parrot/tests/test_flow_primitives/test_result.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/models/crew.py:1-13
from __future__ import annotations
from typing import List, Dict, Any, Optional, Literal, Union, Protocol
from datetime import datetime
import uuid
from dataclasses import dataclass, field
from .responses import AIMessage, AgentResponse

ResponseType = Union[AIMessage, AgentResponse, Any]
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/crew.py:20-57
@dataclass
class AgentExecutionInfo:
    agent_id: str
    agent_name: str
    provider: Optional[str] = None
    model: Optional[str] = None
    execution_time: float = 0.0
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    status: Literal['completed', 'failed', 'pending', 'running'] = 'pending'
    error: Optional[str] = None
    client: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    def to_dict(self) -> Dict[str, Any]: ...

# packages/ai-parrot/src/parrot/models/crew.py:60-251
@dataclass
class CrewResult:
    output: Any
    responses: Dict[str, ResponseType] = field(default_factory=dict)
    summary: str = ""
    agents: List[AgentExecutionInfo] = field(default_factory=list)
    execution_log: List[Dict[str, Any]] = field(default_factory=list)
    total_time: float = 0.0
    status: Literal['completed', 'partial', 'failed'] = 'completed'
    errors: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Properties: content, final_result, success, agent_results, completed, failed
    # Methods: to_dict(), __getitem__, __str__, __repr__, __setattr__

# packages/ai-parrot/src/parrot/models/crew.py:255-264
def determine_run_status(success_count: int, failure_count: int) -> Literal[...]: ...

# packages/ai-parrot/src/parrot/models/crew.py:322-383
def build_agent_metadata(agent_id, agent, response, output, execution_time, status, error=None) -> AgentExecutionInfo: ...
```

### Does NOT Exist
- ~~`FlowResult`~~ — does not exist yet; created by this task
- ~~`NodeExecutionInfo`~~ — does not exist yet; created by this task
- ~~`build_node_metadata`~~ — does not exist yet; created by this task
- ~~`NodeResult`~~ — will NOT be created (brainstorm D11: AgentResult stays in models)

---

## Implementation Notes

### Pattern to Follow
- Use `@dataclass` consistently (not Pydantic) to match existing `CrewResult`.
- `FlowResult.nodes` is the primary field; `FlowResult.agents` is a `@property`
  alias returning `self.nodes`.
- `FlowResult.status` should use `FlowStatus` enum from `types.py` (TASK-913)
  instead of `Literal['completed', 'partial', 'failed']`.
- `NodeExecutionInfo.node_id` and `.node_name` are primary; `.agent_id` and
  `.agent_name` are `@property` aliases.
- `build_node_metadata()` mirrors `build_agent_metadata()` but returns
  `NodeExecutionInfo`. It may import `AIMessage`/`AgentResponse` for
  response introspection.

### Key Constraints
- Preserve ALL observable behavior from `CrewResult`: `__getitem__`, `__str__`,
  `__repr__`, `__setattr__` override for `summary`.
- `to_dict()` must produce JSON-serializable output.
- No deprecation warnings in this spec (Spec 2 concern).

---

## Acceptance Criteria

- [ ] `FlowResult` preserves all `CrewResult` observable properties
- [ ] `FlowResult.nodes` is the primary field; `.agents` alias works
- [ ] `FlowResult.status` uses `FlowStatus` enum
- [ ] `NodeExecutionInfo` preserves all `AgentExecutionInfo` fields
- [ ] `.agent_id` returns `.node_id`; `.agent_name` returns `.node_name`
- [ ] `build_node_metadata()` returns `NodeExecutionInfo`
- [ ] `determine_run_status()` logic matches existing
- [ ] `to_dict()` round-trip serialization works
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_flow_primitives/test_result.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_flow_primitives/test_result.py
import pytest
from parrot.bots.flows.core.result import (
    FlowResult, NodeExecutionInfo, FlowStatus,
    determine_run_status, build_node_metadata,
)
from parrot.bots.flows.core.types import FlowStatus


class TestNodeExecutionInfo:
    def test_backward_compat_aliases(self):
        info = NodeExecutionInfo(node_id="n1", node_name="agent-1")
        assert info.agent_id == "n1"
        assert info.agent_name == "agent-1"

    def test_to_dict(self):
        info = NodeExecutionInfo(node_id="n1", node_name="agent-1", status="completed")
        d = info.to_dict()
        assert d["node_id"] == "n1"
        assert d["status"] == "completed"


class TestFlowResult:
    def test_nodes_is_primary(self):
        info = NodeExecutionInfo(node_id="n1", node_name="a1")
        r = FlowResult(output="done", nodes=[info])
        assert r.nodes == [info]
        assert r.agents == [info]  # alias

    def test_content_alias(self):
        r = FlowResult(output="hello")
        assert r.content == "hello"

    def test_success_property(self):
        r = FlowResult(output="ok", status=FlowStatus.COMPLETED)
        assert r.success is True
        r2 = FlowResult(output="fail", status=FlowStatus.FAILED)
        assert r2.success is False

    def test_to_dict_round_trip(self):
        r = FlowResult(output="test", status=FlowStatus.COMPLETED)
        d = r.to_dict()
        assert isinstance(d, dict)
        assert d["output"] == "test"
        assert d["status"] in ("completed", FlowStatus.COMPLETED)

    def test_backward_compat_agent_results(self):
        r = FlowResult(output="ok")
        assert isinstance(r.node_results, dict)
        assert r.agent_results == r.node_results


class TestDetermineRunStatus:
    def test_all_success(self):
        assert determine_run_status(3, 0) == "completed"

    def test_all_failed(self):
        assert determine_run_status(0, 3) == "failed"

    def test_partial(self):
        assert determine_run_status(2, 1) == "partial"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/flow-primitives.spec.md` §2 Data Models and §3 Module 4
2. **Check dependencies** — verify TASK-913 is completed
3. **Verify** that `CrewResult` and `AgentExecutionInfo` signatures in
   `packages/ai-parrot/src/parrot/models/crew.py` still match the contract above
4. **Implement** result.py following the existing dataclass patterns
5. **Run tests**: `pytest packages/ai-parrot/tests/test_flow_primitives/test_result.py -v`

---

## Completion Note

Completed 2026-04-29. Created `parrot/bots/flows/core/result.py` with:
- `NodeExecutionInfo` dataclass: primary fields `node_id`/`node_name`, backward-compat `@property` aliases `agent_id`/`agent_name`, `to_dict()`.
- `FlowResult` dataclass: primary field `nodes` (replacing `agents`), `status: FlowStatus`, backward-compat aliases (`.agents`, `.agent_results`, `.content`, `.success`, `.completed`, `.failed`), `__getitem__`, `to_dict()`, `__str__`, `__repr__`, `__setattr__`.
- `build_node_metadata()` adapted from `build_agent_metadata()` returning `NodeExecutionInfo`.
- `determine_run_status()` copied from `parrot.models.crew`.
All 31 unit tests pass.

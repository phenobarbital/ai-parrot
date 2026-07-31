---
type: Wiki Overview
title: 'TASK-916: Node Hierarchy — Node ABC, AgentNode, StartNode, EndNode'
id: doc:sdd-tasks-completed-task-916-flow-primitives-node-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Creates the shared node hierarchy in `parrot.bots.flows.core.node`. The `Node`
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core.fsm
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.bots.flows.core.types
  rel: mentions
---

# TASK-916: Node Hierarchy — Node ABC, AgentNode, StartNode, EndNode

**Feature**: FEAT-134 — Flow Primitives — Shared Core for AgentCrew & AgentsFlow
**Spec**: `sdd/specs/flow-primitives.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-913, TASK-914
**Assigned-to**: unassigned

---

## Context

Creates the shared node hierarchy in `parrot.bots.flows.core.node`. The `Node`
ABC adds a `node_id` field (separate from `name`). `AgentNode` wraps an
`AgentLike` + `AgentTaskMachine` with distinct `node_id` and `agent.name`.
`StartNode` and `EndNode` are virtual entry/exit nodes.

The existing `Node` ABC in `parrot.bots.flow.node` does NOT have `node_id` —
adding it is the key change. The existing `AgentNode` in
`parrot.bots.orchestration.crew` has NO base class and no FSM — the new one
combines both.

Implements Spec §3 Module 3.

---

## Scope

- Create `packages/ai-parrot/src/parrot/bots/flows/core/node.py` containing:
  - `Node(ABC)` — lean base with `node_id: str`, `logger`, `_pre_actions`,
    `_post_actions`, `_init_node()`, abstract `name` property, action hooks
    (`add_pre_action`, `add_post_action`, `run_pre_actions`, `run_post_actions`).
  - `AgentNode(Node)` — wraps `AgentLike` agent + `AgentTaskMachine` FSM.
    Has `node_id` (unique per graph instance) separate from `agent.name`.
    Fields: `dependencies: Set[str]`, `successors: Set[str]`.
  - `StartNode(Node)` — virtual entry node, name defaults to `"__start__"`.
  - `EndNode(Node)` — virtual exit node, name defaults to `"__end__"`.
- Write unit tests.

**NOT in scope**: `FlowNode` stays in `parrot.bots.flow.fsm` (engine-specific).
The crew's `AgentNode` stays in `crew.py` unchanged (Spec 2 migration).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/node.py` | CREATE | Node hierarchy |
| `packages/ai-parrot/tests/test_flow_primitives/test_node.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Existing Node ABC to adopt:
# packages/ai-parrot/src/parrot/bots/flow/node.py:1-11
from abc import ABC, abstractmethod
from typing import Any, Callable, List, Union, Awaitable
import asyncio
from navconfig.logging import logging
ActionCallback = Callable[..., Union[None, Awaitable[None]]]

# Types from TASK-913:
from parrot.bots.flows.core.types import AgentLike, ActionCallback

# FSM from TASK-914:
from parrot.bots.flows.core.fsm import AgentTaskMachine
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flow/node.py:14-106
class Node(ABC):
    logger: logging.Logger
    _pre_actions: List[ActionCallback]
    _post_actions: List[ActionCallback]
    def _init_node(self, name: str) -> None: ...          # line 48
    @property @abstractmethod
    def name(self) -> str: ...                             # line 59
    def add_pre_action(self, action: ActionCallback): ...  # line 66
    def add_post_action(self, action: ActionCallback): ... # line 70
    async def run_pre_actions(self, prompt="", **ctx): ... # line 76
    async def run_post_actions(self, result=None, **ctx):  # line 92

# packages/ai-parrot/src/parrot/bots/flow/nodes/start.py:6-47
class StartNode(Node):
    is_configured: bool = True
    def __init__(self, name="__start__", *, metadata=None): ...
    @property
    def name(self) -> str: ...
    async def ask(self, question="", **ctx) -> str: ...
    async def configure(self) -> None: ...

# packages/ai-parrot/src/parrot/bots/flow/nodes/end.py:6-46
class EndNode(Node):  # same structure as StartNode
```

### Does NOT Exist
- ~~`Node.node_id`~~ — does NOT exist on the current Node ABC; this task adds it
- ~~`AgentNode` as a `Node` subclass~~ — current `AgentNode` in crew.py has NO base class
- ~~`AgentNode.fsm`~~ — current crew.py `AgentNode` has NO FSM
- ~~`parrot.bots.flows.core.node`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
```python
class Node(ABC):
    node_id: str
    # ... preserve all action hook logic from existing Node ABC ...

    def _init_node(self, node_id: str, name: str) -> None:
        self.node_id = node_id
        self.logger = logging.getLogger(f"parrot.node.{name}")
        self._pre_actions = []
        self._post_actions = []


@dataclass
class AgentNode(Node):
    agent: AgentLike
    node_id: str                              # unique per graph instance
    dependencies: Set[str] = field(default_factory=set)
    successors: Set[str] = field(default_factory=set)
    fsm: AgentTaskMachine = field(default=None)

    def __post_init__(self):
        if self.fsm is None:
            self.fsm = AgentTaskMachine(agent_name=self.agent.name)
        self._init_node(self.node_id, self.agent.name)

    @property
    def name(self) -> str:
        return self.agent.name
```

### Key Constraints
- `Node.node_id` and `Node.name` are separate concepts:
  - `node_id` = unique per graph instance (e.g., `"researcher-1"`)
  - `name` = agent identity (e.g., `"researcher"`)
- `StartNode` and `EndNode` use duck-typing to satisfy `AgentLike`-like
  usage (they have `ask()`, `name`, `is_configured`, `configure()`). They do
  NOT implement `AgentLike.invoke()` — they are special nodes, not agents.
- Action hook logic (sync/async detection via `asyncio.iscoroutine()`) must
  be preserved exactly.

---

## Acceptance Criteria

- [ ] `Node` ABC has `node_id: str` field separate from `name` property
- [ ] `AgentNode` wraps `AgentLike` + `AgentTaskMachine` with distinct `node_id` and `agent.name`
- [ ] `StartNode` and `EndNode` instantiate with defaults
- [ ] Action hooks (pre/post) work for both sync and async callbacks
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_flow_primitives/test_node.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_flow_primitives/test_node.py
import pytest
from parrot.bots.flows.core.node import Node, AgentNode, StartNode, EndNode
from parrot.bots.flows.core.types import AgentLike


class MockAgent:
    @property
    def name(self) -> str:
        return "test-agent"
    async def invoke(self, prompt: str, **kwargs):
        return f"response: {prompt}"


class TestNodeIdVsName:
    def test_agent_node_separates_id_from_name(self):
        agent = MockAgent()
        node = AgentNode(agent=agent, node_id="node-1")
        assert node.node_id == "node-1"
        assert node.name == "test-agent"
        assert node.node_id != node.name


class TestStartEndNodes:
    def test_start_node_defaults(self):
        node = StartNode()
        assert node.name == "__start__"

    def test_end_node_defaults(self):
        node = EndNode()
        assert node.name == "__end__"

    def test_start_node_custom_name(self):
        node = StartNode(name="entry")
        assert node.name == "entry"


class TestActionHooks:
    def test_pre_action_sync(self):
        calls = []
        node = StartNode()
        node.add_pre_action(lambda n, p, **kw: calls.append(("pre", n, p)))

    @pytest.mark.asyncio
    async def test_pre_action_executes(self):
        calls = []
        node = StartNode()
        node.add_pre_action(lambda n, p, **kw: calls.append(("pre", n)))
        await node.run_pre_actions(prompt="test")
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_post_action_async(self):
        calls = []
        async def async_action(n, r, **kw):
            calls.append(("post", n, r))
        node = StartNode()
        node.add_post_action(async_action)
        await node.run_post_actions(result="done")
        assert len(calls) == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2 New Public Interfaces and §3 Module 3
2. **Check dependencies** — TASK-913 and TASK-914 must be completed
3. **Verify** `Node` ABC in `packages/ai-parrot/src/parrot/bots/flow/node.py`
   and `StartNode`/`EndNode` in `packages/ai-parrot/src/parrot/bots/flow/nodes/`
4. **Implement** `node.py` — adopt the existing action hook pattern exactly
5. **Run tests**

---

## Completion Note

Completed 2026-04-29. Created `parrot/bots/flows/core/node.py` with:
- `Node(ABC)`: extended base with `node_id: str` + `name` abstract property + action hooks (pre/post, sync/async). `_init_node(node_id, name)` initialises both fields.
- `AgentNode(Node)` dataclass: wraps `AgentLike` agent + auto-created `AgentTaskMachine` FSM; distinct `node_id` vs `agent.name`; `dependencies: Set[str]`, `successors: Set[str]`.
- `StartNode(Node)` / `EndNode(Node)`: virtual entry/exit nodes with `is_configured`, `ask()`, `configure()` duck-typing attrs. `node_id` equals `name` for these.
All 31 unit tests pass.

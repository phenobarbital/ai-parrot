---
type: Wiki Overview
title: 'TASK-1060: Reshape `core.node` — Node ABC + AgentNode + StartNode + EndNode
  to frozen Pydantic'
id: doc:sdd-tasks-completed-task-1060-reshape-core-node-frozen-pydantic-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements Spec §3 Module 1. Promotes the existing `parrot/bots/flows/core/node.py`
  classes (`Node` ABC, `AgentNode`, `StartNode`, `EndNode`) from `@dataclass` to frozen
  Pydantic `BaseModel` with `model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)`.
  Action-hook '
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots.flows.core.fsm
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
---

# TASK-1060: Reshape `core.node` — Node ABC + AgentNode + StartNode + EndNode to frozen Pydantic

**Feature**: FEAT-163 — AgentsFlow Refactor — DAG Engine on flows.core
**Spec**: `sdd/specs/agentsflow-refactor-spec3.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements Spec §3 Module 1. Promotes the existing `parrot/bots/flows/core/node.py` classes (`Node` ABC, `AgentNode`, `StartNode`, `EndNode`) from `@dataclass` to frozen Pydantic `BaseModel` with `model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)`. Action-hook lists move to `PrivateAttr(default_factory=list)` so the existing imperative `add_pre_action` / `add_post_action` API survives `frozen=True` (Pydantic v2 frozen blocks attribute reassignment but allows mutation of nested objects and `PrivateAttr` is not subject to the frozen contract). `AgentNode.execute()` signature changes from `(prompt, *, timeout, **ctx)` to `(ctx: FlowContext, deps: DependencyResults, **kwargs)`; default prompt derivation moves into a new overridable `_build_prompt(ctx, deps)` method. FSM stays as a field on `AgentNode` (B-lite — confirmed in spec §1 Goals + §8 OQ-3 resolution).

This task is the foundation: every other module depends on this new shape. The build will be temporarily broken for `parrot/bots/flows/crew/` until TASK-1062 lands — that is expected.

---

## Scope

- Convert `Node` ABC from `@dataclass` to Pydantic `BaseModel` with `model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)`.
- Convert `AgentNode`, `StartNode`, `EndNode` to Pydantic `BaseModel` (subclasses of the new `Node`).
- Move `_pre_actions` / `_post_actions` to `PrivateAttr(default_factory=list)`; remove the `_init_node(node_id, name)` pattern (use `model_post_init(__context)` for any post-construction setup like FSM auto-creation).
- Change `AgentNode.execute()` signature to `(self, ctx: FlowContext, deps: DependencyResults, **kwargs) -> Any`.
- Add `_build_prompt(self, ctx: FlowContext, deps: DependencyResults) -> str` as a default method on `AgentNode` that returns `ctx.get_input_for_agent(self.agent.name, self.dependencies)` (so subclasses like `CrewAgentNode` can override).
- Inside the new `AgentNode.execute()`: call `await self.run_pre_actions(prompt=prompt, **kwargs)`, then `self.agent.ask(question=prompt, _trusted_source=True, **kwargs)`, then `await self.run_post_actions(result=response, **kwargs)`. Return the response (or a dict matching legacy shape — match the existing return contract from `core/node.py:200-232`, preserving `'response' / 'output' / 'execution_time' / 'prompt'` keys for now since downstream code may consume them; verify with grep). **FSM transitions are NOT called inside `execute()`** — the scheduler manages FSM lifecycle externally (`node.fsm.start()` before, `.succeed()` / `.fail()` after).
- Keep `StartNode` / `EndNode` behavior identical: `is_configured: bool = True`, `name`, `metadata`, async `ask()` no-op pass-through, async `configure()` no-op.
- Update the module docstring at the top of `core/node.py` to reflect the new Pydantic shape.

**NOT in scope**:
- AgentCrew migration (TASK-1062).
- Extracting `fsm` into a separate `NodeRunState` class — that's B-full, explicitly rejected (spec §1 Non-Goals).
- Touching `parrot/bots/flow/node.py` (the legacy Node ABC at a different path).
- Modifying `parrot/bots/orchestration/` (spec non-goal: separate deletion track).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/node.py` | MODIFY | Reshape Node, AgentNode, StartNode, EndNode to frozen Pydantic |
| `packages/ai-parrot/tests/bots/flows/core/test_node.py` | CREATE or MODIFY | Unit tests for the new shape (see §Test Specification) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr
from typing import Any, Optional, Dict, Set, Awaitable, Callable
from abc import ABC, abstractmethod
import asyncio
from navconfig.logging import logging

from .fsm import AgentTaskMachine        # verified: parrot/bots/flows/core/fsm.py:40
from .types import (                     # verified: parrot/bots/flows/core/types.py
    ActionCallback,                      # line 27
    AgentLike,                           # line 55 (Protocol)
    DependencyResults,                   # line 30
)
# FlowContext used only as a forward-ref type annotation; use TYPE_CHECKING
# to avoid an import cycle (core.context imports from elsewhere in core).
```

### Existing Signatures (CURRENT shape — to be replaced)

```python
# packages/ai-parrot/src/parrot/bots/flows/core/node.py

# Line 34
class Node(ABC):
    node_id: str
    logger: logging.Logger
    _pre_actions: list
    _post_actions: list

    def _init_node(self, node_id: str, name: str) -> None: ...
    @property
    @abstractmethod
    def name(self) -> str: ...
    def add_pre_action(self, action: ActionCallback) -> None: ...
    def add_post_action(self, action: ActionCallback) -> None: ...
    async def run_pre_actions(self, prompt: str = "", **ctx) -> None: ...
    async def run_post_actions(self, result: Any = None, **ctx) -> None: ...

# Line 143
@dataclass
class AgentNode(Node):
    agent: AgentLike
    node_id: str
    dependencies: Set[str] = field(default_factory=set)
    successors: Set[str] = field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = field(default=None)

    def __post_init__(self) -> None: ...
    @property
    def name(self) -> str: return self.agent.name
    async def execute(self, prompt: str, *, timeout=None, **ctx) -> Dict[str, Any]: ...

# Line 250
class StartNode(Node):
    is_configured: bool = True
    metadata: Dict[str, Any]
    def __init__(self, name: str = "__start__", *, metadata=None): ...
    async def ask(self, question: str = "", **ctx) -> str: ...
    async def configure(self) -> None: ...

# Line 305
class EndNode(Node):
    # mirrors StartNode shape
```

### Existing Signatures (DEPENDENCIES — do not modify)

```python
# packages/ai-parrot/src/parrot/bots/flows/core/types.py
ActionCallback = Callable[..., Union[None, Awaitable[None]]]   # line 27
DependencyResults = Dict[str, str]                              # line 30
class AgentLike(Protocol):                                      # line 55
    # protocol with .name, .ask(question=..., **kwargs), etc.
AgentRef = Union[str, AgentLike]                                # line 100

# packages/ai-parrot/src/parrot/bots/flows/core/fsm.py
class AgentTaskMachine(StateMachine):                           # line 40
    def __init__(self, agent_name: str): ...
    # methods: .schedule(), .start(), .succeed(), .fail()
    # state: .current_state.id ("idle", "ready", "running", "completed", "failed")
```

### Does NOT Exist

- ~~`Node.model_post_init`~~ — does not exist YET; will be added by this task on the new Pydantic shape.
- ~~`AgentNode._build_prompt`~~ — does not exist yet; added by this task.
- ~~Pydantic `model_config` on the current dataclass `Node`~~ — current class is a dataclass, not a BaseModel.
- ~~`NodeSpec` ABC~~ — never existed; B-lite collapsed that concept (spec §8 OQ-6).
- ~~`NodeRunState`~~ — never existed and not created here (B-lite, spec §1 Non-Goals).

---

## Implementation Notes

### Pattern to Follow

Pydantic v2 frozen-with-mutable-private-attr pattern:

```python
from pydantic import BaseModel, ConfigDict, PrivateAttr

class Node(BaseModel, ABC):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    node_id: str
    _pre_actions: list = PrivateAttr(default_factory=list)
    _post_actions: list = PrivateAttr(default_factory=list)
    _logger: Any = PrivateAttr(default=None)

    def model_post_init(self, __context) -> None:
        # PrivateAttr is settable here even on a frozen model.
        self._logger = logging.getLogger(f"parrot.node.{self.name}")

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def logger(self):
        return self._logger

    def add_pre_action(self, action: ActionCallback) -> None:
        self._pre_actions.append(action)  # mutating list, NOT reassigning field — frozen-safe
```

For `AgentNode.model_post_init` with FSM auto-creation:

```python
def model_post_init(self, __context) -> None:
    super().model_post_init(__context)
    if self.fsm is None:
        # Frozen model: cannot do `self.fsm = ...` directly.
        object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.agent.name))
```

The `object.__setattr__` is the standard escape hatch for setting a frozen Pydantic field inside `model_post_init`. Use it sparingly and only for this one case.

### Key Constraints

- **`arbitrary_types_allowed=True`** is required because `AgentLike` (Protocol), `AgentTaskMachine` (StateMachine subclass from `python-statemachine`), and `logging.Logger` are not Pydantic-native types.
- **DO NOT** call `self.fsm.start()` / `.succeed()` / `.fail()` inside `AgentNode.execute()`. The scheduler (TASK-1067) owns FSM lifecycle.
- **DO** preserve the return-shape contract of the current `execute()` — `{'response', 'output', 'execution_time', 'prompt'}` — unless a downstream consumer breaks (verify with grep). The new signature is `(ctx, deps, **kwargs)` but the return shape can stay the same for compatibility with `CrewAgentNode` callers.
- Import `FlowContext` only under `TYPE_CHECKING` to avoid an import cycle (core/context.py imports things from elsewhere in core that may reference Node).
- Action lists are `_pre_actions: list[ActionCallback] = PrivateAttr(default_factory=list)`. They are NOT model fields and do NOT appear in `model_dump()`.
- Logger: store via `PrivateAttr` since it's a `logging.Logger` instance, not a Pydantic-friendly type.
- Match the existing module docstring style (see `parrot/bots/flows/core/result.py` and `parrot/bots/flows/crew/crew.py` for examples).

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flows/core/node.py` — current dataclass shape (to be replaced).
- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:62-78` — imports from core that this task changes; that file calls `node.fsm.<method>()` extensively (UNCHANGED by this task).
- `packages/ai-parrot/src/parrot/bots/flows/crew/nodes.py:CrewAgentNode` — `core.node.AgentNode` subclass; will need migration in TASK-1062 to match the new Pydantic shape. Aware-of-future but DO NOT touch here.
- Pydantic v2 docs on `PrivateAttr` and `model_post_init`: <https://docs.pydantic.dev/latest/concepts/models/#private-model-attributes>

---

## Acceptance Criteria

- [ ] `core.node.Node`, `AgentNode`, `StartNode`, `EndNode` are Pydantic `BaseModel` subclasses (not dataclasses).
- [ ] All four have `model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)`.
- [ ] `node.field_name = value` raises (frozen enforcement).
- [ ] `node._pre_actions.append(cb)` works (PrivateAttr is mutable).
- [ ] `AgentNode.execute()` signature is `(self, ctx: FlowContext, deps: DependencyResults, **kwargs) -> Any`.
- [ ] `AgentNode._build_prompt(ctx, deps) -> str` exists with the documented default behavior.
- [ ] `AgentNode.model_post_init` auto-creates FSM when not provided.
- [ ] `node.fsm.start()` succeeds on a frozen node (nested-object mutation is allowed).
- [ ] All new unit tests in `tests/bots/flows/core/test_node.py` pass.
- [ ] No imports broken in `parrot/bots/flows/core/` (verify `python -c "from parrot.bots.flows.core.node import Node, AgentNode, StartNode, EndNode"` succeeds).
- [ ] **Expected breakage tolerated**: `parrot/bots/flows/crew/` will fail to import until TASK-1062 lands — document this in the commit message.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/core/node.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/core/test_node.py
import pytest
from pydantic import ValidationError

from parrot.bots.flows.core.node import Node, AgentNode, StartNode, EndNode
from parrot.bots.flows.core.fsm import AgentTaskMachine


class FakeAgent:
    name = "fake-agent"
    async def ask(self, question: str = "", **kwargs):
        return {"content": f"echo: {question}"}


class TestNodeFrozen:
    def test_agent_node_construct(self):
        node = AgentNode(agent=FakeAgent(), node_id="n1")
        assert node.node_id == "n1"
        assert node.name == "fake-agent"
        assert isinstance(node.fsm, AgentTaskMachine)

    def test_agent_node_frozen_blocks_reassignment(self):
        node = AgentNode(agent=FakeAgent(), node_id="n1")
        with pytest.raises((ValidationError, TypeError, AttributeError)):
            node.node_id = "n2"

    def test_agent_node_fsm_state_mutates(self):
        node = AgentNode(agent=FakeAgent(), node_id="n1")
        # FSM mutation is allowed even on frozen model
        node.fsm.schedule()
        node.fsm.start()
        assert str(node.fsm.current_state.id) == "running"

    def test_node_private_action_lists(self):
        node = AgentNode(agent=FakeAgent(), node_id="n1")
        def cb(name, prompt, **ctx): pass
        node.add_pre_action(cb)
        node.add_post_action(cb)
        assert len(node._pre_actions) == 1
        assert len(node._post_actions) == 1

    async def test_agent_node_execute_new_signature(self, flow_context_stub):
        node = AgentNode(agent=FakeAgent(), node_id="n1")
        deps = {}
        result = await node.execute(ctx=flow_context_stub, deps=deps)
        # Return shape — verify with current contract (response/output/execution_time/prompt)
        assert "output" in result or hasattr(result, "content")

    def test_start_node_default_name(self):
        node = StartNode()
        assert node.name == "__start__"
        assert node.is_configured is True

    def test_end_node_default_name(self):
        node = EndNode()
        assert node.name == "__end__"


@pytest.fixture
def flow_context_stub():
    """Minimal FlowContext stub for execute() tests.

    Returns an object with .get_input_for_agent() that yields a static prompt.
    """
    class Stub:
        def get_input_for_agent(self, name, deps): return f"prompt for {name}"
    return Stub()
```

---

## Agent Instructions

When you pick up this task:

1. Read the spec at `sdd/specs/agentsflow-refactor-spec3.spec.md` (focus on §2 Architectural Design, §3 Module 1, §7 Implementation Notes, §6 Codebase Contract).
2. Check dependencies — none here; this is the first task.
3. Verify the Codebase Contract — `grep -n "class Node\|class AgentNode\|class StartNode\|class EndNode" packages/ai-parrot/src/parrot/bots/flows/core/node.py` should still match the line numbers above.
4. Read the current `core/node.py` end-to-end before editing.
5. Implement following the scope, codebase contract, and notes above.
6. Run `pytest packages/ai-parrot/tests/bots/flows/core/test_node.py -v` until all tests pass.
7. Run `ruff check packages/ai-parrot/src/parrot/bots/flows/core/node.py` until clean.
8. Verify acceptance criteria.
9. Commit with a message documenting that AgentCrew imports will fail until TASK-1062 lands.
10. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-12
**Notes**: Node ABC, AgentNode, StartNode, EndNode converted from @dataclass to frozen Pydantic BaseModel. StartNode/EndNode use @property name returning node_id to avoid Pydantic field-shadowing-abstract-property conflict. All 31 original tests pass plus 31 new tests in tests/bots/flows/core/test_node.py.
**Deviations from spec**: StartNode/EndNode do not declare name as a Pydantic field (caused abstract property shadowing returning None). Instead, name is a @property returning node_id. __init__ accepts name= kwarg for backward compat routed to node_id. Functionally equivalent.

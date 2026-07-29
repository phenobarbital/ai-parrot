---
type: Wiki Overview
title: 'TASK-1065: Scaffold `parrot/bots/flows/flow.py` with `NODE_REGISTRY` + `@register_node`
  + `AgentsFlow` class skeleton'
id: doc:sdd-tasks-completed-task-1065-scaffold-flow-py-node-registry-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements Spec §3 Module 4 + the module skeleton from §3 Module 6 (constructor,
  fields, `add_node`, deferred `run_flow`). This is the foundation file for the new
  executor at `parrot/bots/flows/flow.py`. It defines:'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage
  rel: mentions
- concept: mod:parrot.bots.flows.flow
  rel: mentions
- concept: mod:parrot.registry.registry
  rel: mentions
---

# TASK-1065: Scaffold `parrot/bots/flows/flow.py` with `NODE_REGISTRY` + `@register_node` + `AgentsFlow` class skeleton

**Feature**: FEAT-163 — AgentsFlow Refactor — DAG Engine on flows.core
**Spec**: `sdd/specs/agentsflow-refactor-spec3.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1060
**Assigned-to**: unassigned

---

## Context

Implements Spec §3 Module 4 + the module skeleton from §3 Module 6 (constructor, fields, `add_node`, deferred `run_flow`). This is the foundation file for the new executor at `parrot/bots/flows/flow.py`. It defines:

- `NODE_REGISTRY: dict[str, type[Node]]`.
- `@register_node(name)` decorator.
- `CompletionEvent` dataclass.
- `AgentsFlow(PersistenceMixin)` class skeleton — `__init__`, `add_node`, store-the-`FlowDefinition`, deferred (`NotImplementedError` or `...`) for `from_definition` (TASK-1068) and `run_flow` (TASK-1067).
- Registration of the built-in core Node subclasses (`AgentNode`, `StartNode`, `EndNode`) under their type keys (`"agent"`, `"start"`, `"end"`).

The new module sits at the SAME package depth as `parrot/bots/flows/crew/crew.py` and uses the same relative-import style (`from .core.fsm import ...`).

---

## Scope

- Create `parrot/bots/flows/flow.py` with the following structure:
  1. Module docstring summarizing the new architecture (link the brainstorm + spec).
  2. Top-of-file imports from `flows.core` (verified list below).
  3. `CompletionEvent` dataclass (`node_id: str`, `result: Any = None`, `error: BaseException | None = None`).
  4. `NODE_REGISTRY: dict[str, type[Node]] = {}` module-level dict.
  5. `def register_node(name: str) -> Callable[[type[Node]], type[Node]]` decorator factory.
  6. `AgentsFlow(PersistenceMixin)` class with:
     - `__init__(self, name: str, *, definition: FlowDefinition | None = None, agent_registry: AgentRegistry | None = None, **kwargs)`
     - `add_node(self, node: Node) -> None` — appends to an internal dict keyed by `node.node_id`.
     - `from_definition(cls, definition, *, agent_registry=None)` — raise `NotImplementedError("TASK-1068")` (placeholder).
     - `async def run_flow(self, ctx=None, *, on_complete=()) -> FlowResult` — raise `NotImplementedError("TASK-1067")` (placeholder).
  7. After the class definitions, register the core Node subclasses under their type keys via direct calls: `register_node("agent")(AgentNode)`, `register_node("start")(StartNode)`, `register_node("end")(EndNode)`. (The DecisionNode, InteractiveDecisionNode, SynthesisNode classes are added by TASK-1066 and self-register via the decorator.)
- Add a stub `__init__.py` re-export if `parrot/bots/flows/__init__.py` is the established import entry (verify by reading it).

**NOT in scope**:
- The actual scheduler implementation (TASK-1067).
- `from_definition()` implementation (TASK-1068).
- New Node subclasses (TASK-1066).
- Deletion of `parrot/bots/flow/fsm.py` (TASK-1069).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/flow.py` | CREATE | The new executor module skeleton |
| `packages/ai-parrot/src/parrot/bots/flows/__init__.py` | MODIFY (optional) | Re-export `AgentsFlow`, `register_node` if convention |
| `packages/ai-parrot/tests/bots/flows/test_flow_registry.py` | CREATE | Unit tests for `NODE_REGISTRY` + `@register_node` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from navconfig.logging import logging

# Modified by TASK-1060 to Pydantic frozen:
from .core.node import Node, AgentNode, StartNode, EndNode

# Existing core primitives (no duplication):
from .core.fsm import AgentTaskMachine, TransitionCondition
from .core.types import AgentRef, DependencyResults, AgentLike
from .core.transition import FlowTransition
from .core.result import (
    FlowResult, NodeResult, NodeExecutionInfo,
    build_node_metadata, determine_run_status,
)
from .core.context import FlowContext
from .core.storage import PersistenceMixin

# Declarative layer (read-only):
from parrot.bots.flow.definition import FlowDefinition

# Registry:
from parrot.registry.registry import AgentRegistry
```

### Existing Signatures (consume — do not modify)

```python
# After TASK-1060:
class Node(BaseModel, ABC):                       # core/node.py:34 (modified)
class AgentNode(Node):                            # core/node.py:144 (modified)
class StartNode(Node):                            # core/node.py:250 (modified)
class EndNode(Node):                              # core/node.py:305 (modified)

class PersistenceMixin:                           # core/storage/persistence.py
    # AgentsFlow inherits — confirm the constructor signature it expects via super().__init__.

class FlowDefinition(BaseModel):                  # parrot/bots/flow/definition.py:288
    name: str
    nodes: List[NodeDefinition]
    edges: List[EdgeDefinition]
    # ...

class AgentRegistry:                              # parrot/registry/registry.py:228
    # Not actually called in this task — just referenced as a type annotation.
```

### Does NOT Exist (yet)

- ~~`parrot.bots.flows.flow` module~~ — created by this task.
- ~~`NODE_REGISTRY`~~ — created by this task.
- ~~`register_node` decorator~~ — created by this task.
- ~~`AgentsFlow` class at `parrot.bots.flows.flow`~~ — created here (the legacy one still lives at `parrot.bots.flow.fsm` until TASK-1069).
- ~~`CompletionEvent`~~ — created by this task.
- ~~`DecisionNode`, `InteractiveDecisionNode`, `SynthesisNode`~~ — added by TASK-1066.

---

## Implementation Notes

### Pattern to Follow

```python
"""AgentsFlow — DAG execution engine (FEAT-163).

The new executor replaces parrot/bots/flow/fsm.py:AgentsFlow with an
event-driven scheduler consuming parrot.bots.flows.core primitives.

See sdd/specs/agentsflow-refactor-spec3.spec.md for the full design.
"""
from __future__ import annotations
# ... imports ...

logger = logging.getLogger(__name__)

# ─── CompletionEvent ────────────────────────────────────────────────────

@dataclass
class CompletionEvent:
    """Event pushed to the scheduler's completion_queue when a node finishes."""
    node_id: str
    result: Any = None
    error: BaseException | None = None


# ─── NODE_REGISTRY + @register_node ──────────────────────────────────────

NODE_REGISTRY: dict[str, type[Node]] = {}


def register_node(name: str) -> Callable[[type[Node]], type[Node]]:
    """Register a Node subclass under `name`.

    Raises:
        ValueError: if `name` is already registered.
        TypeError: if the decorated class is not a Node subclass.
    """
    def decorator(cls: type[Node]) -> type[Node]:
        if not isinstance(cls, type) or not issubclass(cls, Node):
            raise TypeError(
                f"@register_node('{name}') target must be a Node subclass, got {cls!r}"
            )
        if name in NODE_REGISTRY:
            raise ValueError(
                f"Node type {name!r} already registered to {NODE_REGISTRY[name].__name__}"
            )
        NODE_REGISTRY[name] = cls
        return cls
    return decorator


# ─── AgentsFlow class skeleton ────────────────────────────────────────────

class AgentsFlow(PersistenceMixin):
    """DAG executor consuming parrot.bots.flows.core primitives.

    Scheduler implementation arrives in TASK-1067.
    """

    def __init__(
        self,
        name: str,
        *,
        definition: FlowDefinition | None = None,
        agent_registry: AgentRegistry | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)  # PersistenceMixin
        self.name = name
        self._definition = definition
        self._agent_registry = agent_registry
        self._nodes: dict[str, Node] = {}
        self.logger = logging.getLogger(f"parrot.flow.{name}")

    def add_node(self, node: Node) -> None:
        """Add a Node instance to the graph."""
        if node.node_id in self._nodes:
            raise ValueError(f"Node {node.node_id!r} already added")
        self._nodes[node.node_id] = node

    @classmethod
    def from_definition(
        cls,
        definition: FlowDefinition,
        *,
        agent_registry: AgentRegistry | None = None,
    ) -> "AgentsFlow":
        raise NotImplementedError("Implemented in TASK-1068")

    async def run_flow(
        self,
        ctx: FlowContext | None = None,
        *,
        on_complete: tuple[Callable[[FlowContext, FlowResult], Awaitable[None]], ...] = (),
    ) -> FlowResult:
        raise NotImplementedError("Implemented in TASK-1067")


# ─── Register built-in core Node types ───────────────────────────────────

register_node("agent")(AgentNode)
register_node("start")(StartNode)
register_node("end")(EndNode)
```

### Key Constraints

- **No `asyncio.gather` anywhere in this file** (acceptance criterion enforced from TASK-1067 onward; honor it from the start to avoid temptation).
- **No duplication with `flows.core`** — every symbol that has a core counterpart must be imported, not redefined.
- Match the imports style of `parrot/bots/flows/crew/crew.py` (relative `from .core...`).
- `AgentsFlow` inherits ONLY `PersistenceMixin` (NOT `SynthesisMixin` — spec §1 Goals + §5 Acceptance Criteria).
- The deferred methods raise `NotImplementedError` with a clear marker so the implementer of TASK-1067/1068 knows where to land.
- Optionally add `__all__ = ["AgentsFlow", "NODE_REGISTRY", "register_node", "CompletionEvent"]` for explicit public API.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:1–90` — relative-import style + class header pattern.
- `packages/ai-parrot/src/parrot/bots/flow/actions.py:46–62` — `ACTION_REGISTRY` + `register_action` pattern (mirror for `NODE_REGISTRY` + `register_node`).
- TASK-1060 result — the new core.node shape.

---

## Acceptance Criteria

- [ ] `parrot/bots/flows/flow.py` exists.
- [ ] `from parrot.bots.flows.flow import AgentsFlow, NODE_REGISTRY, register_node, CompletionEvent` works.
- [ ] `@register_node("agent")(AgentNode)` succeeded at module load — `NODE_REGISTRY["agent"] is AgentNode`.
- [ ] Same for `"start"` and `"end"`.
- [ ] Re-registering an existing name raises `ValueError`.
- [ ] Decorating a non-`Node` class raises `TypeError`.
- [ ] `AgentsFlow("name").add_node(some_node)` works and stores in the internal dict.
- [ ] Adding a duplicate `node_id` raises `ValueError`.
- [ ] `AgentsFlow("name").run_flow()` raises `NotImplementedError` (placeholder).
- [ ] `AgentsFlow.from_definition(some_def)` raises `NotImplementedError` (placeholder).
- [ ] `AgentsFlow` inherits ONLY `PersistenceMixin` — `not issubclass(AgentsFlow, SynthesisMixin)`.
- [ ] No `asyncio.gather` anywhere in this file (grep check).
- [ ] No re-definition of `AgentTaskMachine`, `TransitionCondition`, `AgentRef`, `DependencyResults`, `PromptBuilder`, `FlowTransition` (grep check).
- [ ] Tests pass: `pytest packages/ai-parrot/tests/bots/flows/test_flow_registry.py -v`.
- [ ] No linting errors on `flow.py`.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/test_flow_registry.py
import pytest

from parrot.bots.flows.flow import (
    AgentsFlow, NODE_REGISTRY, register_node, CompletionEvent,
)
from parrot.bots.flows.core.node import AgentNode, StartNode, EndNode, Node
from parrot.bots.flows.core.storage import PersistenceMixin, SynthesisMixin


class FakeAgent:
    name = "fake"
    async def ask(self, question="", **kwargs): return question


class TestNodeRegistry:
    def test_core_types_registered(self):
        assert NODE_REGISTRY["agent"] is AgentNode
        assert NODE_REGISTRY["start"] is StartNode
        assert NODE_REGISTRY["end"] is EndNode

    def test_register_node_decorator_works(self):
        @register_node("custom-test-type")
        class CustomNode(Node):
            @property
            def name(self) -> str: return "custom"

        assert NODE_REGISTRY["custom-test-type"] is CustomNode
        # cleanup so subsequent runs don't pollute the registry:
        del NODE_REGISTRY["custom-test-type"]

    def test_register_node_rejects_duplicate(self):
        with pytest.raises(ValueError, match="already registered"):
            register_node("agent")(AgentNode)  # 'agent' is already taken

    def test_register_node_rejects_non_node(self):
        with pytest.raises(TypeError):
            register_node("bogus-test")(int)  # not a Node subclass


class TestAgentsFlowSkeleton:
    def test_inherits_only_persistence_mixin(self):
        assert issubclass(AgentsFlow, PersistenceMixin)
        assert not issubclass(AgentsFlow, SynthesisMixin)

    def test_add_node(self):
        flow = AgentsFlow("test")
        node = AgentNode(agent=FakeAgent(), node_id="n1")
        flow.add_node(node)
        assert flow._nodes["n1"] is node

    def test_add_node_duplicate_id_raises(self):
        flow = AgentsFlow("test")
        node1 = AgentNode(agent=FakeAgent(), node_id="dup")
        node2 = AgentNode(agent=FakeAgent(), node_id="dup")
        flow.add_node(node1)
        with pytest.raises(ValueError, match="already added"):
            flow.add_node(node2)

    async def test_run_flow_placeholder(self):
        flow = AgentsFlow("test")
        with pytest.raises(NotImplementedError, match="TASK-1067"):
            await flow.run_flow()

    def test_from_definition_placeholder(self):
        with pytest.raises(NotImplementedError, match="TASK-1068"):
            AgentsFlow.from_definition(None)


class TestCompletionEvent:
    def test_construct_with_result(self):
        ev = CompletionEvent(node_id="n1", result="x")
        assert ev.error is None

    def test_construct_with_error(self):
        ev = CompletionEvent(node_id="n1", error=RuntimeError("boom"))
        assert ev.result is None
```

---

## Agent Instructions

1. Confirm TASK-1060 is in `sdd/tasks/completed/` and its acceptance criteria all green.
2. Read `parrot/bots/flows/crew/crew.py:1–90` for the import style + class header pattern.
3. Read `parrot/bots/flow/actions.py:46–62` for the registry-decorator pattern.
4. Read `parrot/bots/flows/core/storage/__init__.py` to confirm `PersistenceMixin` is exported there (and its constructor signature — `super().__init__(**kwargs)` must work).
5. Create `flow.py` per the pattern. Keep imports verbatim; this file becomes the import target for all subsequent tasks.
6. Run `pytest packages/ai-parrot/tests/bots/flows/test_flow_registry.py -v`.
7. Verify with `grep -n "asyncio.gather\|class AgentTaskMachine\|class TransitionCondition\|class FlowTransition" packages/ai-parrot/src/parrot/bots/flows/flow.py` → no matches.
8. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: flow.py created with NODE_REGISTRY, register_node decorator, CompletionEvent dataclass, AgentsFlow(PersistenceMixin) skeleton. Built-in types registered (agent/start/end). from_definition and run_flow raise NotImplementedError with TASK markers. flows/__init__.py updated. 15/15 tests pass.
**Deviations from spec**: FakeAgent in tests uses @property name (not class attribute) to satisfy AgentLike protocol correctly.

---
type: Wiki Overview
title: 'TASK-001: Engine — `node_factories` injection for declarative custom nodes'
id: doc:sdd-tasks-completed-task-001-engine-node-factories-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §2.A and Module 1 (G2). `AgentsFlow.from_definition()` today
  can
relates_to:
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.bots.flows.flow.definition
  rel: mentions
- concept: mod:parrot.bots.flows.flow.flow
  rel: mentions
- concept: mod:parrot.flows.dev_loop
  rel: mentions
---

# TASK-001: Engine — `node_factories` injection for declarative custom nodes

**Feature**: FEAT-250 — Dev-Loop Refactor
**Spec**: `sdd/specs/dev-loop-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §2.A and Module 1 (G2). `AgentsFlow.from_definition()` today can
only materialize `agent`/`start`/`end` node types; any other type is built with
the generic `cls(node_id, dependencies, successors)` (`flow/flow.py:515-522`),
with **no way to inject live dependencies** (dispatcher, toolkits). This blocks
expressing the dev-loop declaratively. This task adds a generic `node_factories`
hook and lets `NodeDefinition.type` accept any `NODE_REGISTRY`-registered type.
**No dev-loop imports may leak into `parrot.bots.flows`.**

---

## Scope

- Add an optional `node_factories: Optional[dict[str, Callable[[NodeDefinition, set[str], set[str]], Node]]]`
  parameter to `AgentsFlow.from_definition(...)`; store it on the instance
  (e.g. `self._node_factories`).
- In `_materialize_nodes()`, in the branch for node types that are **not**
  `agent`/`start`/`end`: if a factory exists for `node_def.type`, build the node
  via `factory(node_def, deps, succs)`; otherwise keep the current generic
  construction as fallback.
- Allow custom (registered) node types through `from_definition` validation and
  `NodeDefinition` typing. **Decision (spec §8 open question)**: change
  `NodeDefinition.type` from a closed `Literal` to a `str` validated against
  `NODE_REGISTRY` membership at flow-build time (preferred), OR widen the
  Literal. Pick the `NODE_REGISTRY`-validated approach unless it breaks existing
  definition tests; document the choice in the Completion Note.
- Ensure fresh node instances per `run_flow()` (B-lite contract) still hold —
  the factory is re-invoked (or its result re-created) per run.
- Unit tests in `tests/bots/flows/`.

**NOT in scope**: any dev-loop node, definition, or factory (TASK-010);
`run_flow` signature changes beyond what `from_definition` needs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | MODIFY | `from_definition` param + `_materialize_nodes` factory branch |
| `packages/ai-parrot/src/parrot/bots/flows/flow/definition.py` | MODIFY | Accept registered custom node types in `NodeDefinition.type` |
| `packages/ai-parrot/tests/bots/flows/test_node_factories.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.flow.flow import AgentsFlow, NODE_REGISTRY, register_node  # flow.py:157,106,124
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition, EdgeDefinition  # definition.py:289,125,188
from parrot.bots.flows.core.node import Node          # core/node.py:68
from parrot.bots.flows.core.context import FlowContext  # core/context.py:52
```

### Existing Signatures to Use
```python
# parrot/bots/flows/flow/flow.py
@classmethod
def from_definition(cls, definition, *, agent_registry=None) -> "AgentsFlow"   # :351
def _materialize_nodes(self) -> dict[str, Node]                                 # :440
#   else-branch today (verbatim shape): fresh[nid] = cls(node_id=nid, dependencies=deps, successors=succs)  # :515-522
NODE_REGISTRY: dict[str, Type[Node]]                                            # :106
def register_node(name: str) -> Callable[[Type[Node]], Type[Node]]             # :124

# parrot/bots/flows/flow/definition.py
class NodeDefinition(BaseModel):
    id: str
    type: Literal["start","end","agent","decision","interactive_decision","human"]  # :137  ← widen / NODE_REGISTRY-validate
    agent_ref: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)

# parrot/bots/flows/core/node.py
class Node(BaseModel):                                # :68  (frozen; model_config arbitrary_types_allowed)
    node_id: str
    @property
    def name(self) -> str: ...                        # abstract
    async def execute(self, ctx, deps, **kwargs) -> Any: ...  # abstract
```

### Does NOT Exist
- ~~`node_factories` parameter on `from_definition`~~ — this task adds it.
- ~~dependency injection for non-agent nodes in `_materialize_nodes`~~ — gap this task closes.
- ~~`NodeDefinition.config` carrying live objects~~ — it is plain `Dict[str, Any]`; live deps must arrive via the factory closure.

---

## Implementation Notes

### Pattern to Follow
```python
# from_definition signature after change
@classmethod
def from_definition(cls, definition, *, agent_registry=None, node_factories=None):
    ...
    flow = cls(name=flow_name, definition=definition, agent_registry=agent_registry)
    flow._resolved_agents = resolved_agents
    flow._node_factories = dict(node_factories or {})
    return flow

# _materialize_nodes else-branch
else:
    factory = getattr(self, "_node_factories", {}).get(node_type)
    if factory is not None:
        fresh[nid] = factory(node_def, deps, succs)
    else:
        fresh[nid] = cls(node_id=nid, dependencies=deps, successors=succs)
```

### Key Constraints
- Keep the engine generic — NO imports from `parrot.flows.dev_loop`.
- Factory must return a `Node` whose `node_id == node_def.id`, with
  `dependencies`/`successors` set from the passed sets (mirror the agent branch).
- Backward compatible: omitting `node_factories` reproduces today's behaviour.

### References in Codebase
- `parrot/bots/flows/flow/flow.py:440-524` — `_materialize_nodes` (agent/start/end branches to mirror).
- `examples/flow/agentsflow_standalone.py` — example flow build/run for the test harness.

---

## Acceptance Criteria

- [ ] `from_definition(..., node_factories={...})` stores the map; omitting it is a no-op.
- [ ] A custom registered node type with a factory is materialized via the factory (live dep injected).
- [ ] Two `run_flow()` calls produce independent node instances (no shared FSM state).
- [ ] Existing `start`/`end`/`agent` definitions still materialize unchanged.
- [ ] `NodeDefinition.type` accepts a registered custom type without raising.
- [ ] `pytest packages/ai-parrot/tests/bots/flows/test_node_factories.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/flows/flow/` clean.

---

## Test Specification
```python
# packages/ai-parrot/tests/bots/flows/test_node_factories.py
import pytest
from parrot.bots.flows.flow.flow import AgentsFlow, register_node
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition, EdgeDefinition
from parrot.bots.flows.core.node import Node


def test_from_definition_uses_node_factories():
    """Custom node type is built via its factory with an injected dependency."""
    sentinel = object()

    @register_node("test.custom")
    class _Custom(Node):
        node_id: str
        injected: object = None
        @property
        def name(self): return self.node_id
        async def execute(self, ctx, deps, **kwargs): return {"ok": self.injected is sentinel}

    def factory(node_def, deps, succs):
        return _Custom(node_id=node_def.id, injected=sentinel)

    defn = FlowDefinition(flow="t", nodes=[
        NodeDefinition(id="start", type="start"),
        NodeDefinition(id="c", type="test.custom"),
        NodeDefinition(id="end", type="end"),
    ], edges=[
        EdgeDefinition(**{"from": "start"}, to="c"),
        EdgeDefinition(**{"from": "c"}, to="end"),
    ])
    flow = AgentsFlow.from_definition(defn, agent_registry=..., node_factories={"test.custom": factory})
    nodes = flow._materialize_nodes()
    assert isinstance(nodes["c"], _Custom)
    assert nodes["c"].injected is sentinel
```

---

## Agent Instructions
Follow the standard SDD task lifecycle. Verify the Codebase Contract before
coding; if `_materialize_nodes` line numbers shifted, update the contract first.

## Completion Note

**Status**: done — 2026-06-20

**What changed**
- `flow/flow.py`: added `self._node_factories` to `__init__`; added the optional
  `node_factories` keyword to `from_definition` (stored as
  `flow._node_factories = dict(node_factories or {})`); the
  `_materialize_nodes()` else-branch now prefers a registered factory
  (`factory(node_def, deps, succs)`) and falls back to the previous generic
  `cls(node_id, dependencies, successors)` construction when none is present.
  `NodeDefinition` added to the `.definition` import for annotation resolution.
- `flow/definition.py`: `NodeDefinition.type` relaxed from a closed `Literal`
  to `str` (with a documented description). **Decision (spec §8 OQ)**: chose the
  `NODE_REGISTRY`-validated approach — membership is already enforced at
  flow-build time inside `from_definition`, so validating in the model would
  introduce a circular import (`definition` → `flow`). Relaxing to `str` keeps
  the model import-light; typos surface as a `ValueError` at `from_definition`.
- `tests/bots/flows/test_node_factories.py`: 5 tests (factory materialization,
  injected dep, fresh-per-materialization, backward-compat no-op, start/end
  unaffected, custom type accepted by `NodeDefinition`).

**Verification**
- `pytest test_node_factories.py` → 5 passed.
- Regression: `test_from_definition.py` + `test_agentsflow_models.py` → 20 passed.
- `ruff check` clean on all three changed files (pre-existing `loader.py`
  warnings are unrelated and untouched).

**Notes for downstream (TASK-010)**: `from_definition` still requires a
non-`None` `agent_registry`. A dev-loop graph with no `agent`-type nodes can
pass an empty/stub registry. Factories must return a `Node` whose `node_id ==
node_def.id` and should set `dependencies`/`successors` from the passed sets.

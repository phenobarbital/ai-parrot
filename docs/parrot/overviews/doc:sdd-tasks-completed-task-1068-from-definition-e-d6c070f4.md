---
type: Wiki Overview
title: 'TASK-1068: Implement `AgentsFlow.from_definition()` with eager AgentRegistry
  resolution'
id: doc:sdd-tasks-completed-task-1068-from-definition-eager-resolve-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Spec §3 Module 8 — the bridge between the declarative `FlowDefinition`
  layer and the runtime `AgentsFlow` executor. The factory classmethod walks the definition,
  eagerly resolves every `NodeDefinition.agent_ref` against `AgentRegistry`, and stores
  both the definition A
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.bots.flows.flow
  rel: mentions
- concept: mod:parrot.registry.registry
  rel: mentions
---

# TASK-1068: Implement `AgentsFlow.from_definition()` with eager AgentRegistry resolution

**Feature**: FEAT-163 — AgentsFlow Refactor — DAG Engine on flows.core
**Spec**: `sdd/specs/agentsflow-refactor-spec3.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1064, TASK-1065, TASK-1066
**Assigned-to**: unassigned

---

## Context

Implements Spec §3 Module 8 — the bridge between the declarative `FlowDefinition` layer and the runtime `AgentsFlow` executor. The factory classmethod walks the definition, eagerly resolves every `NodeDefinition.agent_ref` against `AgentRegistry`, and stores both the definition AND a pre-resolved `agent_ref → AgentLike` map on the new `AgentsFlow` instance. The materialization of actual Node instances still happens INSIDE `run_flow()` (concurrent-run safety — TASK-1067 `_materialize_nodes`), but agent lookups are done up front so typos / missing agents fail fast.

Eager resolution is spec §8 OQ-5, resolved.

---

## Scope

Replace `AgentsFlow.from_definition`'s placeholder `NotImplementedError` (from TASK-1065) with:

1. **Definition validation reuse**: `FlowDefinition` already triggers `validate_node_ids` + cycle detection (TASK-1064) on construction. If the caller passes an already-validated `FlowDefinition`, those validators don't re-run — that's fine. But if the caller passes a dict, we can `FlowDefinition.model_validate(dict_data)` to force validation. Document the expectation: callers pass a constructed `FlowDefinition`.

2. **Eager agent resolution**:
   - Iterate `definition.nodes`.
   - For each node with a non-empty `agent_ref` (and `node_type in {"agent"}` or whichever types take an agent_ref — confirm at impl time), call `agent_registry.<getter>(agent_ref)`.
   - The exact getter method name is spec §8 OQ-7 (likely `get_agent`, `get`, `lookup`, or `find` on `AgentRegistry` at `parrot/registry/registry.py:228`). **Verify before implementing**.
   - On miss, raise `AgentNotFoundError(f"Cannot resolve agent_ref {ref!r} for node {node_id!r}")` (the error class added in TASK-1061).
   - Store the resolved map: `self._resolved_agents: dict[str, AgentLike] = {node_id: resolved_agent}`.

3. **Construct the `AgentsFlow` instance**:
   - `flow = cls(name=definition.name, definition=definition, agent_registry=agent_registry)`.
   - Attach `_resolved_agents` to the instance.
   - Return the flow.

4. **Update `_materialize_nodes()` (TASK-1067)**:
   - Read `self._resolved_agents` and pass `agent=self._resolved_agents[node_id]` when instantiating `AgentNode` subclasses.
   - For non-agent node types (`StartNode`, `EndNode`, `DecisionNode`, `InteractiveDecisionNode`, `SynthesisNode`), pass the appropriate fields from `NodeDefinition`. **Coordination with TASK-1067**: if `_materialize_nodes` was written before this task, update it now to consume `_resolved_agents`; if both tasks are in-flight together, the implementer picks the order.

5. **Optional `agent_registry` argument default**:
   - If `agent_registry is None`, try `parrot.registry.registry.AgentRegistry.get_instance()` (or whatever the global singleton accessor is — verify). Document this fallback in the docstring.

**NOT in scope**:
- Lazy resolution (explicitly rejected — OQ-5 says eager).
- `BotManager` integration (spec non-goal — `AgentRegistry` is the single source).
- `AgentCrew.from_definition()` (not asked for; AgentCrew is unchanged here).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/flow.py` | MODIFY | Replace `from_definition` placeholder; possibly update `_materialize_nodes` to consume `_resolved_agents` |
| `packages/ai-parrot/tests/bots/flows/test_from_definition.py` | CREATE | Tests for eager resolution + materialization |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (additions to flow.py)

```python
from parrot.bots.flow.definition import FlowDefinition, NodeDefinition, EdgeDefinition
from parrot.registry.registry import AgentRegistry
from .core.context import AgentNotFoundError    # added in TASK-1061
from .core.types import AgentLike
```

### Existing Signatures (consume — do not modify)

```python
# parrot/bots/flow/definition.py
class FlowDefinition(BaseModel):                # line 288
    name: str
    nodes: List[NodeDefinition]
    edges: List[EdgeDefinition]
    # ... fields verified in TASK-1064 ...
    @model_validator(mode="after")              # cycle check from TASK-1064

class NodeDefinition(BaseModel):                # line 124
    node_id: str
    node_type: str                              # "agent", "start", "end", "decision", "interactive_decision", "synthesis"
    agent_ref: Optional[str]                    # the string this task resolves
    position: NodePosition
    # other fields — verify

# parrot/registry/registry.py
class AgentRegistry:                            # line 228
    # OQ-7: confirm the agent-getter method name.
    # If TASK-1061 used `get_agent`, use the same name here.
```

### Does NOT Exist (yet)

- ~~`AgentsFlow.from_definition` implementation~~ — TASK-1065 left a placeholder.
- ~~`AgentsFlow._resolved_agents` attribute~~ — added by this task.
- ~~`AgentRegistry.get_instance()` singleton accessor~~ — verify before assuming; may or may not exist.

---

## Implementation Notes

### Pattern to Follow

```python
@classmethod
def from_definition(
    cls,
    definition: FlowDefinition,
    *,
    agent_registry: AgentRegistry | None = None,
) -> "AgentsFlow":
    """Materialize an executable AgentsFlow from a FlowDefinition.

    Eagerly resolves every NodeDefinition.agent_ref against `agent_registry`.
    Raises AgentNotFoundError on the first unresolved ref.

    The returned flow stores the FlowDefinition; node instances are
    re-materialized fresh inside each run_flow() call.

    Args:
        definition: A validated FlowDefinition (cycles already caught by its model_validator).
        agent_registry: Optional AgentRegistry. If None, falls back to
            the global AgentRegistry singleton (if available).

    Raises:
        AgentNotFoundError: First node whose agent_ref is unresolvable.
        ValueError: If a NodeDefinition.node_type is not registered in NODE_REGISTRY.
    """
    # 1. Resolve agent_registry (fall back to global if needed; document the lookup).
    if agent_registry is None:
        try:
            agent_registry = AgentRegistry.get_instance()  # verify this exists
        except (AttributeError, RuntimeError):
            raise ValueError(
                "AgentsFlow.from_definition requires an agent_registry argument "
                "or a globally-accessible AgentRegistry singleton."
            )

    # 2. Eager resolve agent_refs.
    resolved_agents: dict[str, AgentLike] = {}
    for node_def in definition.nodes:
        if not node_def.agent_ref:
            continue  # start/end/synthesis don't have agent refs
        # Validate node_type is registered (defensive).
        if node_def.node_type not in NODE_REGISTRY:
            raise ValueError(
                f"NodeDefinition {node_def.node_id!r}: "
                f"node_type {node_def.node_type!r} not in NODE_REGISTRY. "
                f"Registered types: {sorted(NODE_REGISTRY)}"
            )
        # Resolve.
        agent = agent_registry.get_agent(node_def.agent_ref)  # ← OQ-7 method name
        if agent is None:
            raise AgentNotFoundError(
                f"Cannot resolve agent_ref {node_def.agent_ref!r} "
                f"for node {node_def.node_id!r}"
            )
        resolved_agents[node_def.node_id] = agent

    # 3. Construct flow.
    flow = cls(
        name=definition.name,
        definition=definition,
        agent_registry=agent_registry,
    )
    flow._resolved_agents = resolved_agents
    return flow
```

### `_materialize_nodes()` adjustment (coordination with TASK-1067)

```python
def _materialize_nodes(self) -> dict[str, Node]:
    """Build a fresh node set from the stored FlowDefinition.

    Called inside every run_flow() invocation so concurrent runs do not
    share Node instances or FSM state.
    """
    if self._definition is None:
        return dict(self._nodes)  # programmatic builder path: return already-stored nodes

    nodes: dict[str, Node] = {}
    for node_def in self._definition.nodes:
        cls = NODE_REGISTRY[node_def.node_type]
        kwargs: dict[str, Any] = {"node_id": node_def.node_id}
        if node_def.node_type == "agent":
            kwargs["agent"] = self._resolved_agents[node_def.node_id]
        # Add type-specific field mapping for decision, interactive_decision, synthesis...
        # (Read NodeDefinition for fields that map to each Node subclass.)
        # Edge metadata sets up dependencies/successors below.
        nodes[node_def.node_id] = cls(**kwargs)

    # Wire dependencies/successors from edges (NOT included in NodeDefinition itself).
    for edge in self._definition.edges:
        if edge.source in nodes and edge.target in nodes:
            nodes[edge.target].dependencies.add(edge.source)
            nodes[edge.source].successors.add(edge.target)
            # NOTE: dependencies/successors are frozen-Pydantic fields with default_factory=set,
            # but the SET itself is mutable. .add() works on a frozen model's nested object.

    return nodes
```

### Key Constraints

- **Eager**: every `agent_ref` resolved at `from_definition()` time. NO lazy resolution inside `execute()`.
- The fallback to a global `AgentRegistry.get_instance()` MUST be verified before relying on it. If the singleton accessor doesn't exist, drop the fallback and require `agent_registry` explicitly.
- `_resolved_agents` is a `dict[str, AgentLike]` keyed by `node_id`. Storing keyed by `agent_ref` would lose the per-node mapping (multiple nodes can share an agent).
- Cycle detection is already done by `FlowDefinition.model_validator` (TASK-1064). DO NOT re-check here.
- Two materialization paths exist:
  - From `from_definition()` → `_resolved_agents` populated; `_materialize_nodes` builds nodes from `definition.nodes`.
  - Programmatic `add_node()` → `_nodes` dict populated directly; `_materialize_nodes` returns `dict(self._nodes)`.
  - If `_resolved_agents` is empty and `_nodes` is empty, `run_flow()` should raise a meaningful error.

### References in Codebase

- `parrot/bots/flow/definition.py:124–180` — `NodeDefinition` field details.
- `parrot/registry/registry.py:228+` — `AgentRegistry` actual methods (verify getter name).
- TASK-1067 completed `_materialize_nodes` (or in-flight) — coordinate field mapping.
- Spec §8 OQ-7 — open question on `AgentRegistry.get_agent` method name.

---

## Acceptance Criteria

- [ ] `AgentsFlow.from_definition(definition, agent_registry=...)` no longer raises `NotImplementedError`.
- [ ] Returns an `AgentsFlow` instance with `._definition`, `._agent_registry`, `._resolved_agents` attributes populated.
- [ ] Resolving an unknown `agent_ref` raises `AgentNotFoundError` mentioning the node_id and ref.
- [ ] Unknown `node_type` (not in `NODE_REGISTRY`) raises `ValueError` listing the registered types.
- [ ] Construction succeeds for an all-valid `FlowDefinition`.
- [ ] Subsequent `await flow.run_flow()` succeeds (smoke test — integration test in TASK-1070 covers fully).
- [ ] `_materialize_nodes()` updated to consume `_resolved_agents` when present.
- [ ] Concurrent-run safety preserved (test from TASK-1067 still passes).
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/bots/flows/test_from_definition.py -v`.
- [ ] No linting errors.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/test_from_definition.py
import pytest

from parrot.bots.flows.flow import AgentsFlow
from parrot.bots.flows.core.context import AgentNotFoundError
from parrot.bots.flow.definition import FlowDefinition, NodeDefinition, EdgeDefinition, NodePosition


class FakeAgent:
    def __init__(self, name): self.name = name
    async def ask(self, question="", **kwargs): return f"echo: {question}"


class StubRegistry:
    def __init__(self, agents): self._agents = agents
    def get_agent(self, name):  # adjust to actual method name (OQ-7)
        return self._agents.get(name)


def _def(node_defs, edges):
    return FlowDefinition(name="t", nodes=node_defs, edges=edges)


class TestFromDefinitionEagerResolve:
    def test_ok_when_all_refs_resolvable(self):
        reg = StubRegistry({"a": FakeAgent("a"), "b": FakeAgent("b")})
        d = _def([
            NodeDefinition(node_id="n1", node_type="agent", agent_ref="a", position=NodePosition(x=0, y=0)),
            NodeDefinition(node_id="n2", node_type="agent", agent_ref="b", position=NodePosition(x=1, y=0)),
        ], [EdgeDefinition(source="n1", target="n2")])
        flow = AgentsFlow.from_definition(d, agent_registry=reg)
        assert flow._resolved_agents["n1"].name == "a"
        assert flow._resolved_agents["n2"].name == "b"

    def test_raises_for_missing_ref(self):
        reg = StubRegistry({"a": FakeAgent("a")})  # missing "b"
        d = _def([
            NodeDefinition(node_id="n1", node_type="agent", agent_ref="a", position=NodePosition(x=0, y=0)),
            NodeDefinition(node_id="n2", node_type="agent", agent_ref="b", position=NodePosition(x=1, y=0)),
        ], [EdgeDefinition(source="n1", target="n2")])
        with pytest.raises(AgentNotFoundError, match="n2"):
            AgentsFlow.from_definition(d, agent_registry=reg)

    def test_raises_for_unknown_node_type(self):
        reg = StubRegistry({"a": FakeAgent("a")})
        d = _def([
            NodeDefinition(node_id="n1", node_type="bogus_type", agent_ref="a", position=NodePosition(x=0, y=0)),
        ], [])
        with pytest.raises(ValueError, match="bogus_type"):
            AgentsFlow.from_definition(d, agent_registry=reg)

    def test_skips_agent_ref_resolution_for_start_node(self):
        reg = StubRegistry({"a": FakeAgent("a")})
        d = _def([
            NodeDefinition(node_id="start", node_type="start", agent_ref=None, position=NodePosition(x=0, y=0)),
            NodeDefinition(node_id="n1", node_type="agent", agent_ref="a", position=NodePosition(x=1, y=0)),
        ], [EdgeDefinition(source="start", target="n1")])
        flow = AgentsFlow.from_definition(d, agent_registry=reg)
        assert "start" not in flow._resolved_agents
        assert "n1" in flow._resolved_agents
```

---

## Agent Instructions

1. Confirm TASK-1064, TASK-1065, TASK-1066 are in `sdd/tasks/completed/`.
2. **First action**: resolve OQ-7 — `grep -n "def " packages/ai-parrot/src/parrot/registry/registry.py | grep -E "agent|get|lookup|find"` to find the getter method name on `AgentRegistry`. If TASK-1061 already used this name, mirror it exactly. Update the contract + tests.
3. Check if `AgentRegistry.get_instance()` (or similar singleton accessor) exists. If not, drop the fallback and require `agent_registry` explicitly.
4. Read `NodeDefinition` (definition.py:124) to confirm field names and which fields each `node_type` maps to in the registered Node subclass.
5. Implement `from_definition` per the pattern. Coordinate with TASK-1067's `_materialize_nodes` if necessary.
6. Run `pytest packages/ai-parrot/tests/bots/flows/test_from_definition.py -v`.
7. Run a regression: `pytest packages/ai-parrot/tests/bots/flows/test_scheduler.py -v` (TASK-1067) — concurrent-run test must still pass.
8. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: from_definition() implemented with eager resolution via AgentRegistry.get_bot_instance (sync, mirrors TASK-1061 pattern). _resolved_agents keyed by node_id. _materialize_nodes updated to lookup by node_id. FlowDefinition uses .flow field for name. 13/13 new tests pass; 126/126 total.
**Deviations from spec**: AgentRegistry has no get_agent method — used get_bot_instance (sync). No global singleton fallback — requires explicit registry. Test spec used wrong field names — corrected to actual FlowDefinition field names (id/flow vs node_id/name).

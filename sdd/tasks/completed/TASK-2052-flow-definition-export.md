# TASK-2052: `AgentsFlow.to_definition()` export + `FlowContext.to_snapshot()` + FlowMetadata checkpoint block

**Feature**: FEAT-399 — AgentsFlow State Checkpointing (Two-Tier Persistence)
**Spec**: `sdd/specs/agentsflow-state-checkpointing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2046
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (flow-layer half, resolved OQ7): programmatic
(`add_node`/`add_edge`) flows must be checkpointable, which requires exporting
the live graph to a `FlowDefinition`. Also adds the `FlowContext.to_snapshot()`
helper and the optional checkpoint block on `FlowMetadata`. Independent of the
checkpoint stores — touches only flow-layer files.

---

## Scope

- Implement `AgentsFlow.to_definition() -> FlowDefinition` in
  `flow/flow.py`:
  - Map programmatically-added `Node` instances → `NodeDefinition` entries
    and `FlowEdge`s → `EdgeDefinition` entries (invert what
    `from_definition()` does — read flow.py:362+ in full first).
  - Every node's type must be resolvable in `NODE_REGISTRY`; otherwise raise
    `FlowNotExportableError` naming the offending node id/class.
  - Round-trip invariant: `AgentsFlow.from_definition(flow.to_definition())`
    produces an equivalent graph (same node ids, types, edges, predicates).
- Implement `FlowContext.to_snapshot(*, serializer, include_responses=False)
  -> ContextSnapshot` in `core/context.py` — encapsulates the field mapping
  (results/completed/order/shared_data; errors → structured dicts; excludes
  agent_registry/synthesis_client/trace_context).
- Add optional checkpoint config block to `FlowMetadata`
  (`flow/definition.py`): `checkpoint: bool = False`,
  `checkpoint_retention: Optional[int]`, `checkpoint_history: Optional[int]`,
  `checkpoint_include_responses: bool = False`, `durable: bool = False`.
- Unit tests: round-trip, unregistered-node error, snapshot mapping.

**NOT in scope**: checkpointer wiring, suspend/resume (TASK-2053) — do NOT
add `checkpoint=` kwargs to `AgentsFlow.__init__` here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | MODIFY | Add `to_definition()` |
| `packages/ai-parrot/src/parrot/bots/flows/flow/definition.py` | MODIFY | FlowMetadata checkpoint block |
| `packages/ai-parrot/src/parrot/bots/flows/core/context.py` | MODIFY | Add `to_snapshot()` |
| `packages/ai-parrot/tests/flows/checkpoint/test_flow_export.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition  # definition.py:296,125
from parrot.bots.flows.core.checkpoint.model import ContextSnapshot          # TASK-2046
from parrot.bots.flows.core.checkpoint.errors import FlowNotExportableError  # TASK-2046
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
class AgentsFlow(PersistenceMixin):                            # line 159
    def add_node(self, node: Node) -> None: ...                # line 234 — internal graph structures
    def add_edge(self, from_, to, ...) -> None: ...            # line 251 — FlowEdge, EDGE_CONDITIONS
    @classmethod
    def from_definition(cls, definition, ...) -> "AgentsFlow": # line 362 — INVERT this mapping
# NODE_REGISTRY + @register_node are module-level in flow.py (see module docstring)

# packages/ai-parrot/src/parrot/bots/flows/flow/definition.py
class NodeDefinition(BaseModel): ...    # line 125 — validate_agent_ref: agent nodes require agent_ref
class EdgeDefinition(BaseModel): ...    # line 195 — validate_predicate: on_condition edges require predicate
class FlowMetadata(BaseModel): ...      # line 254 — extend with checkpoint block
class FlowDefinition(BaseModel): ...    # line 296 — validate_node_ids + _validate_acyclic run on construction

# packages/ai-parrot/src/parrot/bots/flows/core/context.py
class FlowContext:                      # line 52 — dataclass; fields at lines 68-108
    errors: Dict[str, Exception]        # line 81 — encode {type, message, repr}
    agent_registry / synthesis_client / trace_context  # lines 93/100/108 — EXCLUDE from snapshot
```

### Does NOT Exist
- ~~`AgentsFlow.to_definition()`~~ — introduced HERE.
- ~~`FlowContext.to_snapshot()` / `from_snapshot()`~~ — `to_snapshot` introduced HERE; there is NO `from_snapshot` (resume seeds via `mark_completed()`, TASK-2053).
- ~~`FlowMetadata.checkpoint*` fields today~~ — introduced HERE.
- ~~A public getter for AgentsFlow's internal node/edge dicts~~ — inspect the actual private attributes set by `add_node`/`add_edge` (read flow.py:234-306) rather than assuming names.

---

## Implementation Notes

### Key Constraints
- `to_definition()` must not mutate the flow; it is a pure export.
- `FlowDefinition`'s own validators (`validate_node_ids`, `_validate_acyclic`)
  are the final gate — construct the definition and let them run.
- New `FlowMetadata` fields must default so existing definitions parse
  unchanged (backwards compatible).
- Agent nodes: `NodeDefinition.agent_ref` must carry the registry name when
  the node holds a live agent — if the node has no resolvable string ref,
  that is also `FlowNotExportableError` (a live-object agent cannot be
  reconstructed on resume).

---

## Acceptance Criteria

- [ ] `test_to_definition_roundtrip` — programmatic flow → definition → `from_definition` equivalence (node ids, types, edges).
- [ ] `test_to_definition_unregistered_node_raises` — `FlowNotExportableError` naming the node.
- [ ] `FlowContext.to_snapshot()` maps all fields per spec, excludes non-serializable ones, errors structured.
- [ ] Existing definitions (no checkpoint block) still validate — run the existing flow test suite.
- [ ] `pytest packages/ai-parrot/tests/flows/checkpoint/test_flow_export.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/checkpoint/test_flow_export.py
def test_roundtrip_equivalence(programmatic_flow):
    definition = programmatic_flow.to_definition()
    rebuilt = AgentsFlow.from_definition(definition, agent_registry=registry)
    assert rebuilt_to_comparable(rebuilt) == rebuilt_to_comparable(programmatic_flow)

def test_unregistered_node_raises():
    class RogueNode(Node): ...
    flow.add_node(RogueNode(...))
    with pytest.raises(FlowNotExportableError, match="RogueNode"):
        flow.to_definition()

def test_context_snapshot_excludes_runtime_bindings(flow_context):
    snap = flow_context.to_snapshot(serializer=s)
    assert not hasattr(snap, "agent_registry")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context
2. **Check dependencies** — TASK-2046 in `tasks/completed/`
3. **Verify the Codebase Contract** — read flow.py:159-560 (graph internals + from_definition) BEFORE designing the export
4. **Update status** in `sdd/tasks/index/agentsflow-state-checkpointing.json` → `"in-progress"`
5. **Implement**, then **verify** all acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

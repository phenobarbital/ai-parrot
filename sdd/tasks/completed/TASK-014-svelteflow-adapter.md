# TASK-014: SvelteFlow Adapter

**Feature**: AgentsFlow Persistency
**Spec**: `sdd/specs/agentsflow-persistency.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-009
**Assigned-to**: c5c51100-9236-4823-bdc3-26829271174f

---

## Context

> Visual flow builders like SvelteFlow and ReactFlow use a specific node/edge format. This adapter provides bidirectional conversion between `FlowDefinition` and SvelteFlow format, enabling visual editing of agent workflows. Implements Module 5 from the spec.

---

## Scope

> Implement `to_svelteflow()` and `from_svelteflow()` conversion functions.

- Implement `to_svelteflow(definition: FlowDefinition) -> Dict[str, Any]`
- Implement `from_svelteflow(sf_data: Dict, flow_name: str) -> FlowDefinition`
- Map fields correctly:
  - `node.id` ↔ `node.id`
  - `node.label` ↔ `node.data.label`
  - `node.type` ↔ `node.type`
  - `node.position` ↔ `node.position`
  - `edge.from` ↔ `edge.source`
  - `edge.to` ↔ `edge.target`
- Preserve all node data (agent_ref, instruction, config, actions) in `node.data`
- Write tests ensuring roundtrip consistency

**NOT in scope**:
- Actual SvelteFlow UI (separate project)
- Edge styling/animation properties
- Custom node rendering logic

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/flow/svelteflow.py` | CREATE | Adapter functions |
| `parrot/bots/flow/__init__.py` | MODIFY | Export `to_svelteflow`, `from_svelteflow` |
| `tests/test_svelteflow_adapter.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/bots/flow/svelteflow.py
from typing import Any, Dict
from .definition import FlowDefinition, NodeDefinition, EdgeDefinition


def to_svelteflow(definition: FlowDefinition) -> Dict[str, Any]:
    """Convert FlowDefinition to SvelteFlow format.

    Returns:
        Dict with 'nodes' and 'edges' arrays in SvelteFlow format.
    """
    nodes = [
        {
            "id": n.id,
            "type": n.type,
            "position": {"x": n.position.x, "y": n.position.y},
            "data": {
                "label": n.label or n.id,
                "agent_ref": n.agent_ref,
                "instruction": n.instruction,
                "config": n.config,
                "pre_actions": [a.model_dump() for a in n.pre_actions],
                "post_actions": [a.model_dump() for a in n.post_actions],
                "metadata": n.metadata,
                "max_retries": n.max_retries,
            },
        }
        for n in definition.nodes
    ]

    edges = []
    for e in definition.edges:
        # Handle fan-out (to can be list)
        targets = [e.to] if isinstance(e.to, str) else e.to
        for target in targets:
            edges.append({
                "id": e.id or f"{e.from_}->{target}",
                "source": e.from_,
                "target": target,
                "label": e.label or e.condition,
                "data": {
                    "condition": e.condition,
                    "predicate": e.predicate,
                    "instruction": e.instruction,
                    "priority": e.priority,
                },
            })

    return {"nodes": nodes, "edges": edges}


def from_svelteflow(sf_data: Dict[str, Any], flow_name: str) -> FlowDefinition:
    """Convert SvelteFlow format to FlowDefinition.

    Args:
        sf_data: Dict with 'nodes' and 'edges' from SvelteFlow
        flow_name: Name for the flow

    Returns:
        FlowDefinition ready for persistence or materialization.
    """
    ...
```

### Field Mapping Table
| FlowDefinition | SvelteFlow |
|----------------|------------|
| `node.id` | `node.id` |
| `node.label` | `node.data.label` |
| `node.type` | `node.type` |
| `node.position.x/y` | `node.position.x/y` |
| `node.agent_ref` | `node.data.agent_ref` |
| `node.config` | `node.data.config` |
| `edge.from_` | `edge.source` |
| `edge.to` | `edge.target` |
| `edge.condition` | `edge.data.condition` |
| `edge.predicate` | `edge.data.predicate` |

### Key Constraints
- Fan-out edges (one source, multiple targets) expand to multiple SvelteFlow edges
- Fan-in edges require grouping by target in `from_svelteflow()`
- Preserve all action data through roundtrip
- Use `node.data` for all custom properties (SvelteFlow convention)

### References in Codebase
- `parrot/bots/flow/definition.py` — Pydantic models (TASK-009)

---

## Acceptance Criteria

- [ ] `to_svelteflow()` converts FlowDefinition to SvelteFlow format
- [ ] `from_svelteflow()` converts SvelteFlow format to FlowDefinition
- [ ] Roundtrip is lossless: `from_svelteflow(to_svelteflow(def))` equals original
- [ ] Fan-out edges expanded to individual edges in SvelteFlow
- [ ] All node data preserved in `node.data`
- [ ] All tests pass: `pytest tests/test_svelteflow_adapter.py -v`
- [ ] Import works: `from parrot.bots.flow import to_svelteflow, from_svelteflow`

---

## Test Specification

```python
# tests/test_svelteflow_adapter.py
import pytest
from parrot.bots.flow.svelteflow import to_svelteflow, from_svelteflow
from parrot.bots.flow.definition import (
    FlowDefinition, NodeDefinition, EdgeDefinition,
    NodePosition, LogActionDef
)


@pytest.fixture
def sample_flow():
    return FlowDefinition(
        flow="TestFlow",
        version="1.0",
        nodes=[
            NodeDefinition(
                id="start",
                type="start",
                label="Begin",
                position=NodePosition(x=100, y=200)
            ),
            NodeDefinition(
                id="worker",
                type="agent",
                agent_ref="my_agent",
                label="Process",
                position=NodePosition(x=300, y=200),
                pre_actions=[LogActionDef(level="info", message="Starting {node_name}")]
            ),
            NodeDefinition(
                id="end",
                type="end",
                position=NodePosition(x=500, y=200)
            ),
        ],
        edges=[
            EdgeDefinition(**{"from": "start", "to": "worker", "condition": "always"}),
            EdgeDefinition(**{
                "from": "worker",
                "to": "end",
                "condition": "on_condition",
                "predicate": 'result.status == "ok"'
            }),
        ]
    )


class TestToSvelteflow:
    def test_node_structure(self, sample_flow):
        """Nodes converted to SvelteFlow format."""
        result = to_svelteflow(sample_flow)

        assert "nodes" in result
        assert len(result["nodes"]) == 3

        worker = next(n for n in result["nodes"] if n["id"] == "worker")
        assert worker["type"] == "agent"
        assert worker["position"] == {"x": 300, "y": 200}
        assert worker["data"]["label"] == "Process"
        assert worker["data"]["agent_ref"] == "my_agent"

    def test_edge_structure(self, sample_flow):
        """Edges converted to SvelteFlow format."""
        result = to_svelteflow(sample_flow)

        assert "edges" in result
        assert len(result["edges"]) == 2

        edge = next(e for e in result["edges"] if e["source"] == "worker")
        assert edge["source"] == "worker"
        assert edge["target"] == "end"
        assert edge["data"]["condition"] == "on_condition"
        assert edge["data"]["predicate"] == 'result.status == "ok"'

    def test_fanout_edges_expanded(self):
        """Fan-out edges become multiple SvelteFlow edges."""
        flow = FlowDefinition(
            flow="FanOut",
            nodes=[
                NodeDefinition(id="a", type="start"),
                NodeDefinition(id="b", type="end"),
                NodeDefinition(id="c", type="end"),
            ],
            edges=[
                EdgeDefinition(**{"from": "a", "to": ["b", "c"], "condition": "always"})
            ]
        )

        result = to_svelteflow(flow)

        assert len(result["edges"]) == 2
        targets = {e["target"] for e in result["edges"]}
        assert targets == {"b", "c"}

    def test_actions_preserved(self, sample_flow):
        """Pre/post actions preserved in node data."""
        result = to_svelteflow(sample_flow)

        worker = next(n for n in result["nodes"] if n["id"] == "worker")
        assert len(worker["data"]["pre_actions"]) == 1
        assert worker["data"]["pre_actions"][0]["type"] == "log"


class TestFromSvelteflow:
    def test_parse_svelteflow_data(self):
        """Parse SvelteFlow format into FlowDefinition."""
        sf_data = {
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "position": {"x": 0, "y": 0},
                    "data": {"label": "Start"}
                },
                {
                    "id": "end",
                    "type": "end",
                    "position": {"x": 200, "y": 0},
                    "data": {"label": "End"}
                }
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "start",
                    "target": "end",
                    "data": {"condition": "always"}
                }
            ]
        }

        flow = from_svelteflow(sf_data, "ParsedFlow")

        assert flow.flow == "ParsedFlow"
        assert len(flow.nodes) == 2
        assert len(flow.edges) == 1
        assert flow.edges[0].from_ == "start"
        assert flow.edges[0].to == "end"


class TestRoundtrip:
    def test_lossless_roundtrip(self, sample_flow):
        """Converting to SvelteFlow and back preserves data."""
        sf = to_svelteflow(sample_flow)
        restored = from_svelteflow(sf, sample_flow.flow)

        # Compare key fields (timestamps may differ)
        assert restored.flow == sample_flow.flow
        assert len(restored.nodes) == len(sample_flow.nodes)
        assert len(restored.edges) == len(sample_flow.edges)

        for orig, rest in zip(sample_flow.nodes, restored.nodes):
            assert rest.id == orig.id
            assert rest.type == orig.type
            assert rest.agent_ref == orig.agent_ref

    def test_edge_conditions_preserved(self, sample_flow):
        """Edge conditions and predicates survive roundtrip."""
        sf = to_svelteflow(sample_flow)
        restored = from_svelteflow(sf, sample_flow.flow)

        orig_edge = sample_flow.edges[1]  # on_condition edge
        rest_edge = next(e for e in restored.edges if e.condition == "on_condition")

        assert rest_edge.predicate == orig_edge.predicate
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-persistency.spec.md` Section 2 (Public Interfaces)
2. **Check dependencies** — verify TASK-009 is complete (need definition models)
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-014-svelteflow-adapter.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: c5c51100-9236-4823-bdc3-26829271174f
**Date**: 2026-02-22
**Notes**: Implemented `to_svelteflow()` and `from_svelteflow()` in `parrot/bots/flow/svelteflow.py`. Fan-out edges expand to individual SvelteFlow edges; `from_svelteflow` groups edges with identical (source, condition, predicate) back into fan-out `EdgeDefinition`s. Actions are serialised via `model_dump(by_alias=True)` and re-hydrated through Pydantic's `TypeAdapter`. 15 tests pass covering structure, fan-out, roundtrip, and imports.

**Deviations from spec**: none

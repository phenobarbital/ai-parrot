---
type: Wiki Overview
title: 'TASK-1064: Add cycle detection `model_validator` to `FlowDefinition`'
id: doc:sdd-tasks-completed-task-1064-flowdefinition-cycle-detection-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Spec §3 Module 9. The legacy executor's `_would_create_cycle`
  method (`parrot/bots/flow/fsm.py:1252`) only checks cycles at `task_flow()` time
  — runtime, after the flow has already been mostly built. With this refactor, cycle
  detection moves into `FlowDefinition.model_
relates_to:
- concept: mod:parrot.bots
  rel: mentions
---

# TASK-1064: Add cycle detection `model_validator` to `FlowDefinition`

**Feature**: FEAT-163 — AgentsFlow Refactor — DAG Engine on flows.core
**Spec**: `sdd/specs/agentsflow-refactor-spec3.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements Spec §3 Module 9. The legacy executor's `_would_create_cycle` method (`parrot/bots/flow/fsm.py:1252`) only checks cycles at `task_flow()` time — runtime, after the flow has already been mostly built. With this refactor, cycle detection moves into `FlowDefinition.model_validator(mode="after")` so that ANY construction path (JSON load, programmatic build, SvelteFlow round-trip) fails fast at definition time. The runtime check disappears with `fsm.py` deletion in TASK-1069.

`FlowDefinition` already has a `validate_node_ids` validator at `parrot/bots/flow/definition.py:338` that checks reference integrity (every edge's source/target exists as a node). Cycle detection is the second post-validator, added alongside it.

This task is fully independent of TASK-1060/1061/1062 — it only touches `parrot/bots/flow/definition.py`.

---

## Scope

- Add a `@model_validator(mode="after")` method on `FlowDefinition` (in `parrot/bots/flow/definition.py:288`) that:
  - Builds an adjacency list from `self.edges` (`EdgeDefinition.source` → `EdgeDefinition.target`).
  - Runs DFS or Kahn's algorithm to detect cycles.
  - On cycle: raise `ValueError("Cycle detected: <node_ids in the cycle>")`.
  - On acyclic: return `self`.
- Place the new validator **immediately after** the existing `validate_node_ids` at line 338 so reference integrity is checked first (avoids surfacing a confusing cycle error when the real problem is a dangling reference).
- Update the `FlowDefinition` class docstring to mention cycle detection.

**NOT in scope**:
- Removing `_would_create_cycle` from `parrot/bots/flow/fsm.py` — that file is deleted in TASK-1069.
- Cycle detection on other models (`NodeDefinition`, `EdgeDefinition` — they're per-element, no cycles to detect).
- Cycle detection at the `SvelteFlowAdapter` boundary — the round-trip produces a `FlowDefinition`, so the validator catches it transitively.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flow/definition.py` | MODIFY | Add cycle-detection `@model_validator` to `FlowDefinition` |
| `packages/ai-parrot/tests/bots/flow/test_definition_cycle.py` | CREATE | Cycle / acyclic regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already present in parrot/bots/flow/definition.py:
from pydantic import BaseModel, Field, model_validator
from typing import List

# Standard library:
from collections import defaultdict
# (For Kahn's / DFS adjacency construction.)
```

### Existing Signatures (to extend — do not replace)

```python
# packages/ai-parrot/src/parrot/bots/flow/definition.py:288
class FlowDefinition(BaseModel):
    name: str
    description: Optional[str]
    nodes: List[NodeDefinition]
    edges: List[EdgeDefinition]
    metadata: Optional[FlowMetadata]
    # ... other fields ...

    @model_validator(mode="after")             # line 338 — EXISTING
    def validate_node_ids(self) -> "FlowDefinition":
        """Existing validator: checks every edge.source/target exists in self.nodes."""
        ...

    # NEW (this task): _validate_acyclic, mode="after", placed below validate_node_ids.

# packages/ai-parrot/src/parrot/bots/flow/definition.py:187
class EdgeDefinition(BaseModel):
    source: str                                # node_id of the upstream node
    target: str                                # node_id of the downstream node
    # ... other fields (condition, etc.) — confirm via read

# packages/ai-parrot/src/parrot/bots/flow/definition.py:124
class NodeDefinition(BaseModel):
    node_id: str                               # unique within the flow
    node_type: str
    agent_ref: Optional[str]
    # ... other fields
```

### Does NOT Exist (yet)

- ~~`FlowDefinition._validate_acyclic`~~ — added by this task.
- ~~Cycle detection anywhere outside the legacy runtime `_would_create_cycle` in `fsm.py`~~ — the legacy is deleted in TASK-1069.

---

## Implementation Notes

### Pattern to Follow — Kahn's algorithm

```python
from collections import defaultdict

@model_validator(mode="after")
def _validate_acyclic(self) -> "FlowDefinition":
    """Reject FlowDefinition whose edges form a cycle.

    Runs Kahn's algorithm: repeatedly remove nodes with in-degree 0.
    If any node remains after the queue empties, it's part of a cycle.

    Placed AFTER `validate_node_ids` so dangling-reference errors surface
    first (cycle detection assumes referential integrity).
    """
    in_degree: dict[str, int] = defaultdict(int)
    adj: dict[str, list[str]] = defaultdict(list)
    node_ids = {n.node_id for n in self.nodes}

    for n in self.nodes:
        in_degree.setdefault(n.node_id, 0)

    for e in self.edges:
        # Reference-integrity already validated above; defensive guard:
        if e.source in node_ids and e.target in node_ids:
            adj[e.source].append(e.target)
            in_degree[e.target] += 1

    queue = [nid for nid in in_degree if in_degree[nid] == 0]
    visited = 0
    while queue:
        node = queue.pop()
        visited += 1
        for nxt in adj[node]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if visited < len(in_degree):
        # The unvisited nodes form / participate in cycles.
        cyclic = [nid for nid, deg in in_degree.items() if deg > 0]
        raise ValueError(f"Cycle detected in flow definition. Nodes in cycle: {cyclic}")

    return self
```

### Key Constraints

- The validator MUST be `mode="after"` so that `self.nodes` and `self.edges` are populated.
- Place it BELOW `validate_node_ids` in source order — Pydantic v2 runs `mode="after"` validators in declaration order.
- Use `defaultdict` for adjacency / in-degree to avoid `KeyError` on isolated nodes.
- Self-loops (`source == target`) are cycles — Kahn handles this naturally (in-degree of that node is ≥ 1 with no predecessor to decrement).
- DO NOT modify `EdgeDefinition` or `NodeDefinition`.

### References in Codebase

- `parrot/bots/flow/definition.py:288–360` — `FlowDefinition` class body.
- `parrot/bots/flow/fsm.py:1252` — legacy `_would_create_cycle` (deleted in TASK-1069; informational only).
- `parrot/bots/flow/svelteflow.py` — round-trip adapter; verify a SvelteFlow → FlowDefinition that contains a cycle is now rejected.

---

## Acceptance Criteria

- [ ] `FlowDefinition._validate_acyclic` exists as a `@model_validator(mode="after")` method.
- [ ] Validator runs AFTER `validate_node_ids` (source order in the class body).
- [ ] `FlowDefinition` with `A → B → A` raises `ValueError` mentioning the cycle.
- [ ] `FlowDefinition` with `A → A` (self-loop) raises `ValueError`.
- [ ] Valid DAG constructs without error.
- [ ] Existing `validate_node_ids` behavior unchanged — dangling reference still raises its own error first.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/bots/flow/test_definition_cycle.py -v`.
- [ ] Existing `FlowDefinition` tests pass (regression check): `pytest packages/ai-parrot/tests/bots/flow/test_definition.py -v` (if exists).
- [ ] No linting errors.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flow/test_definition_cycle.py
import pytest
from pydantic import ValidationError

from parrot.bots.flow.definition import (
    FlowDefinition, NodeDefinition, EdgeDefinition, NodePosition,
)


def _node(nid: str) -> NodeDefinition:
    """Minimal NodeDefinition factory — confirm required fields against current model."""
    return NodeDefinition(
        node_id=nid,
        node_type="agent",
        position=NodePosition(x=0, y=0),
        # add other required fields as needed
    )


def _edge(src: str, tgt: str) -> EdgeDefinition:
    return EdgeDefinition(source=src, target=tgt)


class TestFlowDefinitionCycleDetection:
    def test_accepts_linear_dag(self):
        FlowDefinition(
            name="linear",
            nodes=[_node("a"), _node("b"), _node("c")],
            edges=[_edge("a", "b"), _edge("b", "c")],
        )  # should not raise

    def test_accepts_fan_out_fan_in(self):
        FlowDefinition(
            name="diamond",
            nodes=[_node("a"), _node("b"), _node("c"), _node("d")],
            edges=[
                _edge("a", "b"), _edge("a", "c"),
                _edge("b", "d"), _edge("c", "d"),
            ],
        )  # should not raise

    def test_rejects_two_node_cycle(self):
        with pytest.raises((ValidationError, ValueError), match="[Cc]ycle"):
            FlowDefinition(
                name="cycle",
                nodes=[_node("a"), _node("b")],
                edges=[_edge("a", "b"), _edge("b", "a")],
            )

    def test_rejects_self_loop(self):
        with pytest.raises((ValidationError, ValueError), match="[Cc]ycle"):
            FlowDefinition(
                name="self-loop",
                nodes=[_node("a")],
                edges=[_edge("a", "a")],
            )

    def test_rejects_three_node_cycle(self):
        with pytest.raises((ValidationError, ValueError), match="[Cc]ycle"):
            FlowDefinition(
                name="triangle",
                nodes=[_node("a"), _node("b"), _node("c")],
                edges=[_edge("a", "b"), _edge("b", "c"), _edge("c", "a")],
            )

    def test_reference_error_takes_precedence_over_cycle(self):
        """If both errors are present, the existing validate_node_ids surfaces first."""
        with pytest.raises((ValidationError, ValueError)) as exc:
            FlowDefinition(
                name="bad",
                nodes=[_node("a")],
                edges=[_edge("a", "missing"), _edge("missing", "a")],  # dangling AND cyclic
            )
        # Expect the dangling-reference error (existing validator), not the cycle error.
        assert "missing" in str(exc.value) or "reference" in str(exc.value).lower()
```

---

## Agent Instructions

1. No dependencies; this task is fully self-contained.
2. **First action**: read `parrot/bots/flow/definition.py:288–360` end-to-end. Note the existing `validate_node_ids` style, error messages, and class layout. Match it.
3. Confirm `EdgeDefinition` field names (`source`, `target`) by reading lines 187–239. If they differ, update the implementation.
4. Confirm `NodeDefinition` required fields for the test factory `_node(...)` — adjust the test to construct valid instances.
5. Implement Kahn's algorithm per the pattern above. Place it below `validate_node_ids`.
6. Run `pytest packages/ai-parrot/tests/bots/flow/ -v` — all tests must pass (regression check on existing tests).
7. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: _validate_acyclic added to FlowDefinition using Kahn's algorithm. Placed after validate_node_ids. Handles fan-out (to: List[str]). 9/9 tests pass.
**Deviations from spec**: Codebase Contract listed EdgeDefinition.source/target but real fields are from_/to (verified by reading file). Test factory adjusted accordingly. Also added defaultdict import to definition.py imports.

# TASK-4787: C4 layout (`compute_c4_positions`) + nested-aware `_group_boxes`

**Feature**: FEAT-754 — C4 architecture diagrams as a `Graph` kind
**Spec**: `sdd/specs/a2ui-c4-diagrams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4784
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. Deterministic, dependency-free C4 placement (persons tier 0, internal elements in
nested boundary boxes tier 1, externals tier 2) and nested boundary boxes for every kind via the
shared `_group_boxes`. `build_graph` (TASK-4789) reaches it through `compute_positions` dispatch.

---

## Scope

- Create `graph/layout_c4.py`: `DEFAULT_SHAPE_IN_ROW = 4`, `DEFAULT_BOUNDARY_IN_ROW = 2`,
  `compute_c4_positions`, `_tier_of`, `_boundary_tree`, `_footprint`, `_place` — rules 1–6 of spec §3 M3.
- In `layout.py`: dispatch `kind == "c4"` AFTER the cap check and BEFORE `_break_cycles`
  (function-local import); make `_group_boxes` nested-aware (union of member positions and child boxes,
  children first; groups with neither skipped).
- Create `graph/test_layout_c4.py` (spec §4 M3 rows).

**NOT in scope**: re-export from `graph/__init__.py` (TASK-4793); any SVG/ECharts satellite change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout_c4.py` | CREATE | C4 tier/grid layout |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout.py` | MODIFY | dispatch + nested `_group_boxes` |
| `packages/ai-parrot/tests/outputs/a2ui/graph/test_layout_c4.py` | CREATE | M3 tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.graph.layout import (  # verified: layout.py:60,64,65,68,85,310,293,337
    MAX_STATIC_NODES, _GROUP_PADDING, _LAYOUT_PADDING, GraphTooLargeError, LayoutResult,
    _extent, _oriented_position, _group_boxes, compute_positions,
)
from parrot.outputs.a2ui.graph.models import Direction, GraphGroup, GraphNode, GraphSpec, Position  # verified: models.py:48,110,57,179,127
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout.py (verified at 65144d730)
MAX_STATIC_NODES = 200                                                     # 60
_GROUP_PADDING = 20.0; _LAYOUT_PADDING = 20.0                              # 64-65
class GraphTooLargeError(CatalogValidationError): def __init__(self, node_count: int)  # 68
class LayoutResult(BaseModel): positions; width; height; group_boxes: dict[str, tuple[float,float,float,float]]; reversed_edges: list[tuple[str,str]]  # 85-107
def compute_positions(spec, *, rank_sep: float = 80.0, node_sep: float = 40.0) -> LayoutResult  # 228
    # cap check 251-253; `    dag_edges, reversed_edges = _break_cycles(node_ids, edge_pairs)` 258; logger.debug summary 277-282
def _oriented_position(rank_coord: float, cross_coord: float, direction: Direction) -> Position  # 293
def _extent(positions, max_rank, rank_sep, node_sep, direction, by_rank) -> tuple[float, float]  # 310 (BT/RL mirroring)
def _group_boxes(spec, positions) -> dict[str, tuple[float, float, float, float]]  # 337-348:
    # for group in spec.groups or []: member_positions = [...]; if not member_positions: continue; padded min/max → (x, y, w, h)
```

### Does NOT Exist
- ~~`networkx` in `layout_c4.py`~~ — do not import it.
- ~~`parrot.outputs.a2ui.graph.layout_c4`~~, ~~`compute_c4_positions`~~ — created HERE.
- ~~centring of tier rows~~ — rows are left-aligned (spec rule 3).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout_c4.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/graph/test_layout_c4.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout.py#compute_positions",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout.py#_group_boxes",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout.py#_extent",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout.py#LayoutResult"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Integer slot arithmetic, scaled by `rank_sep`/`node_sep` at the end (like `layout.py:228-290`).
- Footprints computed bottom-up before placement so sibling boxes never overlap.
- `reversed_edges == []` always; cap check first.
- `_group_boxes` for flowchart groups (no `parent`) must produce identical numbers to today
  (`graph/test_layout.py::TestLayoutGroupBoxesContainMembers` unchanged).
- Spec §8 Q5: `person_ext` stays on tier 0.

---

## Implementation Blueprint

### Steps (in order)
1. Make `_group_boxes` nested-aware first — *why*: `compute_c4_positions` returns its result, and the change must be proven neutral on existing tests.
2. Create `layout_c4.py`.
3. Insert the dispatch in `compute_positions`.
4. Write tests; run `test_layout.py` too.

### `packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    dag_edges, reversed_edges = _break_cycles(node_ids, edge_pairs)' layout.py)
# BEFORE — insert above that line (layout.py:258); it sits after `edge_pairs = ...` (256)
    if spec.kind == "c4":
        # Function-local: layout_c4 imports this module (LayoutResult, padding, _extent).
        from .layout_c4 import compute_c4_positions

        return compute_c4_positions(spec, rank_sep=rank_sep, node_sep=node_sep)
```
```python
# occurrences: 1 (verified: grep -c 'def _group_boxes(spec: GraphSpec, positions: dict\[str, Position\]) -> dict\[str, tuple\[float, float, float, float\]\]:' layout.py)
# REPLACE body of _group_boxes (layout.py:337-348), keep signature:
def _group_boxes(spec: GraphSpec, positions: dict[str, Position]) -> dict[str, tuple[float, float, float, float]]:
    """Padded box per group: union of direct member positions and child group boxes (children first)."""
    groups = spec.groups or []
    children: dict[str, list[str]] = {}
    for group in groups:
        parent = getattr(group, "parent", None)
        if parent is not None:
            children.setdefault(parent, []).append(group.id)
    boxes: dict[str, tuple[float, float, float, float]] = {}
    # FILL IN: post-order (iterative) over groups so a child's box exists before its parent's;
    #          rect union of member points ± _GROUP_PADDING and child boxes ± _GROUP_PADDING;
    #          skip a group with neither — bounded by flowchart numbers unchanged (test_layout.py:83)
    return boxes
```

### `packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout_c4.py` (CREATE)
```python
"""Deterministic C4 layout for ``GraphSpec(kind="c4")`` (FEAT-754, spec §3 Module 3).

Tier 0 = persons, tier 1 = internal elements laid in nested boundary boxes, tier 2 = other ``*_ext``.
Pure integer slot arithmetic, scaled at the end; no networkx.
"""

from __future__ import annotations

import logging
from typing import Optional

from .layout import (
    MAX_STATIC_NODES,
    _GROUP_PADDING,
    _LAYOUT_PADDING,
    GraphTooLargeError,
    LayoutResult,
    _extent,
    _group_boxes,
    _oriented_position,
)
from .models import GraphGroup, GraphNode, GraphSpec, Position

__all__ = ["DEFAULT_BOUNDARY_IN_ROW", "DEFAULT_SHAPE_IN_ROW", "compute_c4_positions"]

logger = logging.getLogger(__name__)

DEFAULT_SHAPE_IN_ROW: int = 4  # Mermaid's $c4ShapeInRow default
DEFAULT_BOUNDARY_IN_ROW: int = 2  # Mermaid's $c4BoundaryInRow default


def _tier_of(node: GraphNode) -> int:
    """0 for person/person_ext, 2 for any other ``*_ext``, else 1."""
    c4_type = node.c4_type or ""
    if c4_type.startswith("person"):
        return 0
    return 2 if c4_type.endswith("_ext") else 1


def _boundary_tree(spec: GraphSpec) -> dict[Optional[str], list[GraphGroup]]:
    """Children keyed by parent id (``None`` = top level), preserving ``groups[]`` order."""
    tree: dict[Optional[str], list[GraphGroup]] = {}
    for group in spec.groups or []:
        tree.setdefault(group.parent, []).append(group)
    return tree


def _footprint(group_id: Optional[str], members: list[str], children: dict[Optional[str], list[GraphGroup]],
               shape_in_row: int, depth: int) -> tuple[int, int]:
    """Bottom-up (slots wide, slots high) of a boundary including its padding and children."""
    # FILL IN: rows = ceil(len(members)/shape_in_row); width = max(min(len, shape_in_row), child widths);
    #          height = rows + sum(child heights) — spec §3 M3 rule 2
    raise NotImplementedError


def _place(spec: GraphSpec, shape_in_row: int, boundary_in_row: int) -> dict[str, tuple[int, int]]:
    """Integer (rank_slot, cross_slot) per node id — the only place that walks the tree top-down."""
    # FILL IN: tier 0 rows, tier 1 grid (implicit leading pseudo-box for ungrouped tier-1 nodes, then
    #          top-level boundaries in rows of boundary_in_row), tier 2 rows — spec §3 M3 rules 1-4
    raise NotImplementedError


def compute_c4_positions(spec: GraphSpec, *, rank_sep: float = 80.0, node_sep: float = 40.0) -> LayoutResult:
    """Deterministic C4 placement. Same contract as ``compute_positions``; ``reversed_edges`` is always empty.

    Raises:
        GraphTooLargeError: above ``MAX_STATIC_NODES``.
    """
    if len(spec.nodes) > MAX_STATIC_NODES:
        raise GraphTooLargeError(len(spec.nodes))
    layout = spec.layout
    shape_in_row = (layout.shape_in_row if layout else None) or DEFAULT_SHAPE_IN_ROW
    boundary_in_row = (layout.boundary_in_row if layout else None) or DEFAULT_BOUNDARY_IN_ROW
    slots = _place(spec, shape_in_row, boundary_in_row)
    # FILL IN: scale slots → Position via _oriented_position(rank*rank_sep + pad, cross*node_sep + pad, direction);
    #          width/height via _extent (check its by_rank argument shape) — bounded by layout.py:277-310
    positions: dict[str, Position] = {}
    width, height = 0.0, 0.0
    logger.debug("c4 layout: %d nodes, %d groups", len(spec.nodes), len(spec.groups or []))
    return LayoutResult(
        positions=positions, width=width, height=height,
        group_boxes=_group_boxes(spec, positions), reversed_edges=[],
    )
```
**Why**: signatures fixed by spec §3 M3. `_LAYOUT_PADDING` is the outer pad; `_GROUP_PADDING` grows with depth.

### `packages/ai-parrot/tests/outputs/a2ui/graph/test_layout_c4.py` (CREATE)
```python
"""FEAT-754 M3 — C4 layout."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.outputs.a2ui.graph.layout import GraphTooLargeError, MAX_STATIC_NODES, compute_positions
from parrot.outputs.a2ui.graph.layout_c4 import compute_c4_positions
from parrot.outputs.a2ui.graph.models import GraphSpec

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "c4_container_diagram.json"


def test_c4_layout_deterministic() -> None: ...
def test_c4_persons_first_tier_externals_last() -> None: ...
def test_c4_boundaries_nested_boxes_contain_members() -> None: ...
def test_c4_shape_in_row_wraps() -> None: ...
def test_c4_reversed_edges_empty_and_cap() -> None: ...
def test_group_boxes_nested_for_any_kind() -> None: ...
def test_compute_positions_dispatches_c4() -> None: ...
# FILL IN: bodies — bounded by spec §4 M3 rows
```

### FILL IN checklist
- [ ] nested `_group_boxes` (iterative post-order)
- [ ] `_footprint`, `_place`, scaling in `compute_c4_positions`
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `compute_positions(c4 spec)` deterministic; persons first tier, externals last; nested boxes contain children; `reversed_edges == []`; cap honoured.
- [ ] `graph/test_layout.py` and the SVG regression gate pass unchanged.

## Validation Commands
- `pytest packages/ai-parrot/tests/outputs/a2ui/graph/test_layout_c4.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/graph/test_layout.py -q`
- `pytest packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_graph_svg.py -q`

---

## Test Specification
Spec §4 M3 rows. Run the SVG file with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-visualizations/src`.

---

## Agent Instructions

Standard FEAT-754 procedure; close with `scripts/sdd/close_task.sh TASK-4787 a2ui-c4-diagrams verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: gpt-5.6-sol (codex), attempt 1
**Date**: 2026-10-27
**Notes**: wave-2 merge tier pytest: 136 passed (engine run). The engine gate's vitest runner stayed red (`pnpm exec vitest`: "Command vitest not found" in the validation sandbox, exit 254) while the same command passes from a normal shell; closed with close_task.sh because finalize_task needs a green engine validation ref (user authorized merging UI tasks on sdd-worker-run test evidence).

**Deviations from spec**: none

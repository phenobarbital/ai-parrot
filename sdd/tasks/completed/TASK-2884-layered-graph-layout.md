# TASK-2884: Implement deterministic layered Graph layout

**Feature**: FEAT-529 - A2UI Graph component under the viz-core catalog
**Spec**: sdd/specs/a2ui-graph-component.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2882
**Assigned-to**: unassigned

## Context

Implements Module 4. Layout is core preparation data, not styling, so every
renderer can use the same positions and static renderers can apply the same
node cap and degradation policy.

## Scope

- Implement compute_positions and LayoutResult in core.
- Assign ranks, reduce crossings with deterministic barycentre sweeps, and assign coordinates.
- Break cycle back-edges for layout while reporting reversed_edges.
- Support TB, LR, BT, and RL orientations.
- Compute group bounding boxes and dimensions.
- Raise GraphTooLargeError above MAX_STATIC_NODES.
- Add deterministic layout tests.

NOT in scope: Mermaid parsing, SVG/ECharts drawing, builder integration, or
force-directed server layout.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout.py | CREATE | Pure layered layout implementation |
| packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py | MODIFY | Export layout APIs |
| packages/ai-parrot/tests/outputs/a2ui/graph/test_layout.py | CREATE | Layout invariants and determinism tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

    import networkx
    from pydantic import BaseModel
    from parrot.outputs.a2ui.graph.models import GraphSpec, Position
    from parrot.outputs.a2ui.catalog.base import CatalogValidationError

### Existing Signatures to Use

    # packages/ai-parrot/pyproject.toml:170
    # networkx >= 3.0 is already a core dependency.

    # packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py
    class GraphSpec(BaseModel): ...
    class Position(BaseModel): ...

### Does NOT Exist

- compute_positions / LayoutResult / MAX_STATIC_NODES - no layout package exists.
- _graph_layout.py in the visualization satellite - layout belongs in core.
- grandalf, graphviz, pydot, lark, or pyparsing dependencies - do not add.

## Implementation Notes

- Use stable input-order tie breakers and integer rank/slot indices before scaling.
- NetworkX may assist with cycle detection/topological generations only.
- Positions must already be transposed/mirrored for the requested direction;
  renderers must not reapply direction.
- Cycles are legal for flowchart/state and must produce positions plus a report.

## Acceptance Criteria

- [ ] Every node receives a position and every non-reversed edge advances rank.
- [ ] Repeated calls return equal LayoutResult values.
- [ ] Cycles are broken and reported without dropping nodes.
- [ ] All four directions and group boxes are handled.
- [ ] Graphs over the static cap raise GraphTooLargeError.

## Test Specification

- test_layout_ranks_follow_edges
- test_layout_deterministic
- test_layout_breaks_cycles
- test_layout_direction_lr_swaps_axes
- test_layout_group_boxes_contain_members
- test_layout_too_large_raises

## Agent Instructions

1. Verify TASK-2882 model aliases and validation behavior first.
2. Keep the implementation synchronous, deterministic, and dependency-light.
3. Do not add renderer-specific colors, dimensions, or library options to GraphSpec.

### Completion Note

Implemented as specified: `compute_positions(spec, *, rank_sep=80.0,
node_sep=40.0) -> LayoutResult`. Cycle breaking is an iterative (no
recursion — avoids stack-depth limits on a 200-node fixture), stable,
3-colour DFS feedback-arc-set over the edges in input order; rank
assignment is a single topological-order pass over the resulting acyclic
edge set (via `networkx.topological_sort`, the only networkx usage);
crossing reduction is 4 barycentre sweeps; coordinates scale integer
rank/slot indices by `rank_sep`/`node_sep` only at the very end.
`TB`/`LR` share the exact same coordinate computation with axes swapped
(satisfies "LR == transposed TB" literally); `BT`/`RL` additionally mirror
the rank axis in a second pass once `max_rank` is known. Group boxes are
the padded min/max of member positions; `GraphTooLargeError` subclasses
`CatalogValidationError` (same pattern as `MermaidCodecError`, TASK-2883).

10 tests in `test_layout.py`: the six named in the Test Specification plus
isolated-node, at-cap (`MAX_STATIC_NODES` exactly, must NOT raise), and an
explicit BT/RL axis-mirroring check.

Verification: `pytest packages/ai-parrot/tests/outputs/a2ui -q` → 706
passed (696 pre-existing + 10 new), 1 skipped; `ruff check` clean on all
three touched/created files.

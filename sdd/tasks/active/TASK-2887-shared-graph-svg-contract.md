# TASK-2887: Implement the shared Graph SVG and renderer contract

**Feature**: FEAT-529 - A2UI Graph component under the viz-core catalog
**Spec**: sdd/specs/a2ui-graph-component.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2881, TASK-2882, TASK-2883, TASK-2884
**Assigned-to**: unassigned

## Context

Implements the shared part of Module 6. Static renderer lanes need one SVG
implementation and one semantic state contract so native renderers agree on
geometry, accessibility, status roles, and degradation boundaries.

## Scope

- Create _graph_svg.py with render_graph_svg and STATE_TO_STATUS.
- Render supported shapes, labels, groups, arrows, edge kinds, metadata titles, and descriptions.
- Use core positions when present and compute them when absent.
- Map semantic status roles to DesignSystem CSS tokens without literal colors.
- Add node state/status data attributes and size/layout intent handling.
- Cover SVG output and shared contract behavior with tests.

NOT in scope: ECharts payloads, interactive HTML embedding, SSR/PDF dispatch,
bundled UI, or changing the core Graph schema.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_graph_svg.py | CREATE | Shared SVG renderer and state mapping |
| packages/ai-parrot-visualizations/tests/a2ui_renderers/test_graph_svg.py | CREATE | SVG contract tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

    from parrot.outputs.a2ui.graph import GraphSpec, compute_positions, GraphTooLargeError
    from parrot.outputs.formats.assets.design_system import DesignSystem
    from parrot.outputs.a2ui.models import Component
    from parrot.outputs.a2ui.catalog import resolve_catalog

### Existing Signatures to Use

    # design_system/__init__.py:79-131
    class DesignSystem: ...
    @classmethod
    def resolve(cls, envelope: CreateSurface, *, theme_default: str | None = None,
                layout_default: str | None = None) -> tuple[str, str]: ...

    # graph/layout.py
    def compute_positions(spec: GraphSpec, *, rank_sep: float = 80.0,
                          node_sep: float = 40.0) -> LayoutResult: ...

### Does NOT Exist

- render_graph_svg / STATE_TO_STATUS - no shared Graph SVG contract exists.
- Literal color values in the Graph schema or SVG contract - use semantic roles and DesignSystem tokens.
- _graph_layout.py in the satellite - layout belongs in core.

## Implementation Notes

- Map completed/waiting/failed/running/pending/skipped to good/warning/critical/primary/neutral.
- Emit title from accessibleDescription and per-node titles from meta.
- Preserve original cycle edge direction even when layout reports a reversed back-edge.
- Use CSS variable names such as --accent-red, never hex literals.
- Static overflow should raise GraphTooLargeError to the owning renderer for degradation.

## Acceptance Criteria

- [ ] SVG has one shape per node, group boxes, labels, arrow markers, and edge-kind styling.
- [ ] State attributes and semantic status roles are present.
- [ ] SVG title equals accessibleDescription and contains no literal hex colors.
- [ ] Missing positions are computed using core layout.
- [ ] Shared tests are deterministic and renderer-independent.

## Test Specification

- test_graph_svg_uses_status_tokens
- test_graph_svg_title_from_description
- test_graph_svg_arrowheads_and_edge_kinds

## Agent Instructions

1. Verify the graph package and DesignSystem APIs after dependency tasks land.
2. Keep the SVG renderer pure apart from reading supplied props/theme.
3. Do not add JavaScript or an SVG/graph dependency.

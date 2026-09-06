# TASK-2886: Implement the Graph builder and FlowDefinition adapter

**Feature**: FEAT-529 - A2UI Graph component under the viz-core catalog
**Spec**: sdd/specs/a2ui-graph-component.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2881, TASK-2882, TASK-2884, TASK-2885
**Assigned-to**: unassigned

## Context

Implements Module 5. Deterministic callers need one builder that validates and
prepares Graph envelopes, while flow callers need a mapping-only adapter that
preserves the A2UI adapters import rule.

## Scope

- Add build_graph and export it through builders.__all__.
- Fill layered positions by default while allowing layout computation to be disabled.
- Preserve the Parrot surface catalog and set the Graph component catalog to viz-core.
- Pass data binding/model and action/origin through the existing builder path.
- Add flow_definition_to_graph accepting the aliased mapping shape.
- Map node types, fan-out edges, conditions, predicates, and default descriptions.
- Export the adapter without importing parrot.bots.
- Add builder, adapter, conformance, and import-rule regression tests.

NOT in scope: modifying FlowDefinition, adding a Graph method to flow classes,
renderers, or live workflow updates.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| packages/ai-parrot/src/parrot/outputs/a2ui/builders.py | MODIFY | build_graph and public exports |
| packages/ai-parrot/src/parrot/outputs/a2ui/adapters/flow.py | CREATE | Mapping-only flow adapter |
| packages/ai-parrot/src/parrot/outputs/a2ui/adapters/__init__.py | MODIFY | Adapter export |
| packages/ai-parrot/tests/outputs/a2ui/test_builders_graph.py | CREATE | Builder and adapter tests |
| packages/ai-parrot/tests/outputs/a2ui/adapters/test_import_rule.py | MODIFY | Preserve no-bots-import coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

    from parrot.outputs.a2ui.builders import build_surface
    from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID
    from parrot.outputs.a2ui.graph import GraphNode, GraphEdge, GraphGroup, GraphLayout, GraphSelection, GraphSpec, compute_positions
    from parrot.outputs.a2ui.models import Action, CreateSurface
    from parrot.outputs.a2ui.catalog.base import ProducerOrigin
    from typing import Any, Mapping, Sequence

### Existing Signatures to Use

    # builders.py:31-59
    __all__ = ["build_card", "build_chart", "build_datatable", "build_html_document", "build_infographic", "build_kpicard", "build_map", "build_surface"]
    def build_surface(component: str, properties: dict[str, Any], *, surface_id: str,
                      component_id: str = _ROOT_COMPONENT_ID,
                      data_model: dict[str, Any] | None = None,
                      origin: ProducerOrigin = ProducerOrigin.LLM,
                      metadata: ComponentMetadata | None = None) -> CreateSurface: ...

    # bots/flows/flow/definition.py:155,246,377
    class NodeDefinition(BaseModel): ...
    class EdgeDefinition(BaseModel): ...
    class FlowDefinition(BaseModel): ...

### Does NOT Exist

- build_graph - not in builders or __all__.
- flow_definition_to_graph - no adapter exists.
- FlowDefinition.to_a2ui_graph - callers pass a mapping; do not add this method.
- Any import from parrot.bots in adapters/flow.py - forbidden by G8.

## Implementation Notes

- build_graph calls build_surface with existing origin/data model, then sets
  only the Graph component catalogId to viz-core.
- Adapter input is Mapping[str, Any] and supports aliased from/to shape.
- to: [...] creates one edge per target; on_error/on_timeout are dashed;
  on_condition uses predicate as label.
- Keep surface catalogId at DEFAULT_CATALOG_ID.

## Acceptance Criteria

- [ ] Default builder output has positions and correct surface/component catalog IDs.
- [ ] compute_layout=False leaves positions absent.
- [ ] TOOL actions work and LLM actions fail through existing validation.
- [ ] Flow adapter maps all specified node/edge rules and generates a description.
- [ ] Adapter import-rule tests remain green.

## Test Specification

- test_build_graph_fills_positions
- test_build_graph_sets_viz_core_catalog_id
- test_build_graph_action_tool_origin_only
- test_flow_definition_to_graph_shapes_and_edges
- test_adapters_flow_has_no_bots_import

## Agent Instructions

1. Verify the builder signature and FlowDefinition mapping shape before coding.
2. Keep the adapter independent from bot implementation modules, including under TYPE_CHECKING.
3. Validate emitted envelopes against the existing conformance helper.

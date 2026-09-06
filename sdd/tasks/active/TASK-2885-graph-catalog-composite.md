# TASK-2885: Implement the viz-core Graph catalog composite and lowering

**Feature**: FEAT-529 - A2UI Graph component under the viz-core catalog
**Spec**: sdd/specs/a2ui-graph-component.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2881, TASK-2882, TASK-2883
**Assigned-to**: unassigned

## Context

Implements Module 2. This task publishes Graph under viz-core, derives its
schema from GraphSpec, and supplies the Basic fallback used by unsupported
renderers and lower-only consumers.

## Scope

- Create GRAPH_SCHEMA with derive_schema and the explicit Action $ref.
- Add Graph instructions for LLM authoring and viz-core constraints.
- Register GraphComponent under VIZ_CORE_CATALOG_ID with the specified flags.
- Implement deterministic Basic lowering with description, title, caption, edge list, and Mermaid source.
- Preserve unresolved data binding under parrot_graph_data.
- Reuse the existing origin gate for action rejection; do not add a new gate.
- Add the golden lowered tree and component/schema tests.

NOT in scope: registry rekeying, GraphSpec/codec/layout implementation,
builders/adapters, native renderers, UI, or docs.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py | CREATE | Graph schema, instructions, registration, lowering |
| packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/__init__.py | MODIFY | Import Graph registration |
| packages/ai-parrot/tests/outputs/a2ui/test_components_graph.py | CREATE | Schema, registration, lowering, and gate tests |
| packages/ai-parrot/tests/outputs/a2ui/golden/graph_lowered.json | CREATE | Lowering golden |
| packages/ai-parrot/tests/outputs/a2ui/test_catalog_parity.py | MODIFY | Graph schema parity |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

    from parrot.outputs.a2ui.catalog import register_component, get_component, validate_envelope
    from parrot.outputs.a2ui.catalog.base import BasicTree, CatalogValidationError, ProducerOrigin
    from parrot.outputs.a2ui.catalog.parrot._derive import derive_schema
    from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID
    from parrot.outputs.a2ui.graph import GraphSpec, to_mermaid
    from parrot.outputs.a2ui.models import Component

### Existing Signatures to Use

    # packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/chart.py
    CHART_SCHEMA = derive_schema(StructuredChartConfig, binding_fields=("data",), required=("type", "x", "y"))
    @register_component("Chart")
    class ChartComponent: ...
    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree: ...

    # catalog/__init__.py:107-117
    def register_component(name: str, *, requires_actions: bool = False,
                           catalog_id: str = DEFAULT_CATALOG_ID, is_primitive: bool = False,
                           allowed_parents: list[str] | None = None,
                           allowed_children: list[str] | None = None,
                           tool_only: bool = False) -> Callable[[type], type]: ...

### Does NOT Exist

- GraphComponent / GRAPH_SCHEMA - no Graph component exists.
- action in Basic ComponentCommon - add the Graph-local Action $ref only.
- selectAction / nodeAction - the standard component-level action is the only interaction.
- Graph in the Parrot catalog - register only under viz-core.

## Implementation Notes

- The schema contains every GraphSpec alias, binding descriptor for data, and
  explicit Action reference without color/font/pixel/library vocabulary.
- Lowering emits only Basic primitives and uses parrot_variant: graph.
- Generated description format is Graph of N nodes and M edges (kind).
- Graph action is accepted for TOOL origin and rejected for LLM origin by existing validation.

## Acceptance Criteria

- [ ] Graph is uniquely resolvable under viz-core and has no action/tool/parent requirements.
- [ ] Schema parity, Action reference, and no-style-vocabulary tests pass.
- [ ] Lowered golden and generated-description behavior are stable.
- [ ] Data binding and nested Infographic lowering preserve required extensions/catalog identity.
- [ ] LLM-origin action rejection uses the existing gate.

## Test Specification

- test_graph_schema_has_all_spec_fields
- test_graph_schema_has_no_colour_vocabulary
- test_graph_registered_under_viz_core
- test_graph_lower_golden
- test_graph_lower_generates_description_when_absent
- test_graph_lower_passes_data_binding_through
- test_graph_llm_origin_rejects_action
- test_graph_in_infographic_section_lowers

## Agent Instructions

1. Verify TASK-2881, TASK-2882, and TASK-2883 contracts before implementation.
2. Keep schema derivation as the source of truth; only merge the explicit Action property.
3. Do not modify legacy Parrot Chart/KPICard definitions.

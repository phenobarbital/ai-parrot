# TASK-2891: Document Graph, validate conformance, and close the feature contract

**Feature**: FEAT-529 - A2UI Graph component under the viz-core catalog
**Spec**: sdd/specs/a2ui-graph-component.spec.md
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2886, TASK-2888, TASK-2889, TASK-2890
**Assigned-to**: unassigned

## Context

Implements Module 8 and owns cross-surface acceptance. The Graph wire contract,
viz-core rules, fallback semantics, and renderer matrix must be discoverable in
the public docs and protected by the full conformance suite.

## Scope

- Document the three-catalog resolution rule and viz-core principles.
- Document Graph schema, lowering roles, actions, state/status mapping, Mermaid subset, and renderer matrix.
- Add the frontend reference Graph example and validate it through existing integration tests.
- Extend conformance and parity coverage for builders, exports, and all registered renderers.
- Verify existing no-exec/import/spec-drift/golden invariants and record final test commands.

NOT in scope: implementation changes to Graph, renderers, UI, catalog shell, or
sibling chart/live-workflow specifications.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| docs/outputs/a2ui-v1.md | MODIFY | Three-catalog and Graph documentation |
| docs/frontend/agentdashboard-a2ui-reference.md | MODIFY | Viz-core Graph reference example |
| packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py | MODIFY | Graph conformance coverage |
| packages/ai-parrot/tests/outputs/a2ui/test_catalog_parity.py | MODIFY | Final Graph parity assertion if needed |
| packages/ai-parrot/tests/integration/test_frontend_guide_examples.py | MODIFY | Graph example validation |
| packages/ai-parrot/tests/outputs/a2ui/fixtures/dev_loop_flow.json | CREATE | Mapping fixture without bot imports |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

    from parrot.outputs.a2ui.builders import build_graph
    from parrot.outputs.a2ui.catalog import validate_envelope
    from parrot.outputs.a2ui.catalog.export import export_catalog_definition

### Existing Signatures to Use

    # conformance/test_all_emitters.py:49
    def _assert_conformant(envelope, *, origin): ...

    # test_frontend_guide_examples.py
    # Existing integration test validates every envelope example in the frontend guide.

    # test_catalog_parity.py:22
    def test_derived_chart_schema_has_all_config_fields(): ...

### Does NOT Exist

- Graph documentation or frontend guide example - no Graph entry exists.
- test_build_graph conformance coverage - builders have no Graph case.
- viz-core Graph in the Parrot catalog export - Graph belongs only to viz-core.
- Live workflow SSE/action transport - owned by the sibling live-workflow spec.

## Implementation Notes

- Keep existing Parrot catalog and envelope examples unchanged except for additive references.
- Explain that the surface remains Basic/Parrot while the Graph component carries viz-core.
- Document lowered parrot_role values: description, title, caption, edge-list, edge, graph-source.
- The example must use the mixed-catalog shape and validate against v1.0 schemas.

## Acceptance Criteria

- [ ] Both docs explain viz-core and Graph for implementers and frontend consumers.
- [ ] Graph builder and flow-to-Mermaid integration tests pass.
- [ ] Every registered renderer either renders Graph natively or records the specified degradation.
- [ ] Viz-core export contains Graph while Parrot export does not.
- [ ] Existing no-exec, adapter import, vendored spec, and golden tests remain green.
- [ ] Full A2UI, visualization, and UI test commands pass.

## Test Specification

- test_build_graph
- test_flow_to_graph_to_mermaid_roundtrip
- test_graph_renders_on_every_registered_renderer
- test_catalog_definition_includes_graph
- test_mixed_catalog_surface_validates
- test_frontend_guide_graph_example_validates

## Agent Instructions

1. Verify all implementation dependencies are complete before changing docs/tests.
2. Keep this task additive and do not edit sibling feature specifications.
3. Run the complete acceptance commands from spec AC-14 and capture failures clearly.

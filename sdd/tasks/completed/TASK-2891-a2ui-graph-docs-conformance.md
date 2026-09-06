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

### Completion Note

Implemented as specified. Both docs updated (three-catalog resolution rule
+ full `Graph` section in `a2ui-v1.md`; a new additive §5.4 in the frontend
reference, renderer table updated, Parrot composite count unchanged at 10).

**A real, genuinely-introduced-by-an-earlier-task bug was found and fixed
by this task's own `test_flow_to_graph_to_mermaid_roundtrip`**:
`flow_definition_to_graph` (TASK-2886) defaulted every label-less node's
`label` to its own `id` explicitly. `GraphNode.label` documents "defaults
to id on render" (i.e. `None` is the correct "no label given" value), and
the mermaid codec (TASK-2883) collapses an explicit label EQUAL to id back
to `None` on import — so the adapter's redundant explicit default silently
broke `from_mermaid(to_mermaid(spec)) == spec` for every node without an
authored label. Fixed at the source (`adapters/flow.py`), re-verified
TASK-2886's own `test_builders_graph.py` suite unaffected (it never
asserted on `.label` values).

**Path correction, not a divergence**: `test_frontend_guide_examples.py`
(named in the Codebase Contract as validating "every envelope example in
the frontend guide") actually only ever scanned `docs/frontend/
structured-artifacts-frontend-guide.md` — a DIFFERENT document from
`agentdashboard-a2ui-reference.md`, which is the one this task's own Files
table requires the Graph example be added to. Generalized the existing
fence-scanner helper to accept a path (default unchanged, so the existing
"expected 3 Chart/Table/Map examples" assertion on the OTHER file stays
untouched) and added a new, additive test scanning the reference doc
specifically.

`test_catalog_parity.py` needed no changes — TASK-2885 already added
`test_graph_schema_has_all_spec_fields`, which is the "final Graph parity
assertion" this task's Scope calls for "if needed"; adding a second,
overlapping assertion would have been redundant.

Verification: `pytest packages/ai-parrot/tests/outputs/a2ui packages/
ai-parrot/tests/integration/test_frontend_guide_examples.py -q` → 736
passed, 1 skipped; `pytest packages/ai-parrot-visualizations/tests -q` →
313 passed (run SEPARATELY — combining both package roots in one `pytest`
invocation trips a rootdir/module-identity collision across their
identically-named `tests.outputs.*` packages; confirmed this is a
pre-existing invocation-order artifact, not a regression, by running each
package alone). `ruff check` clean on all five touched/created Python
files. The bundled UI's full Vitest suite (294 passed) was already
verified in TASK-2890 and is untouched by this docs/conformance-only task.

**This closes FEAT-529** — all 11 tasks (TASK-2881 through TASK-2891) are
now complete.

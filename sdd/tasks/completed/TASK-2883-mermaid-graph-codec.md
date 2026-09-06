# TASK-2883: Implement the Mermaid Graph codec

**Feature**: FEAT-529 - A2UI Graph component under the viz-core catalog
**Spec**: sdd/specs/a2ui-graph-component.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2882
**Assigned-to**: unassigned

## Context

Implements Module 3. Mermaid is a deterministic import/export codec only; the
typed GraphSpec remains the wire model. The supported subset must fail clearly
and identify the offending source line.

## Scope

- Implement to_mermaid for flowchart, stateDiagram-v2, and sequenceDiagram.
- Implement from_mermaid for the same supported subset.
- Support specified node shapes, edge kinds, labels, groups, states, and sequence metadata.
- Escape and unescape reserved labels deterministically.
- Map state diagram [*] endpoints through synthetic internal nodes.
- Raise MermaidCodecError with line number, source line, and reason for unsupported syntax.
- Add round-trip, escaping, comments, and error tests with fixture files.

NOT in scope: external parser dependencies, renderer layout, Graph lowering,
or support for excluded dialects/directives.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py | CREATE | Pure Mermaid parser and emitter |
| packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid.py | CREATE | Codec tests |
| packages/ai-parrot/tests/outputs/a2ui/fixtures/mermaid/ | CREATE | Canonical source and expected GraphSpec fixtures |
| packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py | MODIFY | Export codec APIs |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

    from parrot.outputs.a2ui.catalog.base import CatalogValidationError
    from parrot.outputs.a2ui.graph.models import GraphSpec, GraphNode, GraphEdge, GraphGroup

### Existing Signatures to Use

    # packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py:307+
    class CatalogValidationError(CatalogError): ...

    # packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py
    class GraphSpec(BaseModel): ...
    class GraphNode(BaseModel): ...
    class GraphEdge(BaseModel): ...
    class GraphGroup(BaseModel): ...

### Does NOT Exist

- mermaid Python dependency - no dependency may be added.
- from_mermaid / to_mermaid - no codec exists.
- Support for classDef, style, click, linkStyle, %%{init}, loop, alt, or par syntax - excluded.

## Implementation Notes

- Preserve input order for declarations and edges in canonical output.
- Quote labels containing [ ] ( ) { } | " #; encode embedded quotes as #quot;.
- Do not serialize accessibleDescription or size; tests compare round trips modulo those fields.
- Reject user-authored __start__/__end__ IDs when synthetic state endpoints would collide.
- Keep parsing pure and synchronous.

## Acceptance Criteria

- [ ] All three dialects round-trip through GraphSpec in the specified subset.
- [ ] All six node shapes and three edge kinds are represented.
- [ ] Subgraphs, composite states, state endpoints, aliases, and sequence ordering work.
- [ ] Unsupported constructs raise MermaidCodecError with the correct line data.
- [ ] MermaidCodecError is a CatalogValidationError.
- [ ] No external parsing dependency is introduced.

## Test Specification

- test_mermaid_roundtrip_flowchart
- test_mermaid_roundtrip_state
- test_mermaid_roundtrip_sequence
- test_mermaid_quotes_reserved_labels
- test_mermaid_rejects_unsupported_construct
- test_mermaid_ignores_comments_and_blank_lines
- test_mermaid_error_is_catalog_validation_error

## Agent Instructions

1. Verify TASK-2882 is available and its public model exports are unchanged.
2. Keep the parser restricted to the documented subset; do not silently accept syntax.
3. Make canonical output deterministic across runs and platforms.

### Completion Note

Implemented as specified: hand-written regex-based tokenizer/parser (no
external dependency) for `flowchart`/`stateDiagram-v2`/`sequenceDiagram`,
plus a deterministic canonical emitter. `MermaidCodecError(line_no, line,
reason)` subclasses `CatalogValidationError`.

Two design decisions worth flagging for reviewers, both driven by the
spec's own contract — "`from_mermaid(to_mermaid(spec)) == spec` (modulo
`accessibleDescription`/`size`)" is an OBJECT round-trip, not a textual
one:

1. **Collapsing conventions.** A node's `label`/`shape` collapse to
   `None` on parse whenever they equal the id / the dialect's default
   shape (`rect` for flowchart, `rounded` for state) — the inverse of
   what `to_mermaid` does when those fields are `None`. This is
   documented in the module docstring and in `test_mermaid_roundtrip_
   flowchart_default_shape_and_label`. `GraphEdge.kind` is NOT collapsed
   this way (an edge operator is always unambiguously explicit in text,
   unlike "no shape/label given"); callers who want an edge's `kind` to
   round-trip must set it explicitly, which every edge in this task's
   fixtures does.
2. **Declare-once-at-top ordering.** Both `_emit_flowchart` and
   `_emit_state` declare EVERY node once, at top level, in `spec.nodes`
   order; `subgraph`/composite-`state` blocks only bare-reference member
   ids afterwards (never re-declare shape/label there). This was a
   necessary fix during implementation — an earlier draft declared
   grouped nodes only inside their group block, which reordered them in
   the parsed result and broke the round-trip's list-order equality.
   `__start__`/`__end__` are the one unavoidable exception: they have no
   top-level textual form (they exist only via a `[*]` edge endpoint), so
   they always land at the END of the parsed `nodes` list regardless of
   their position in the original spec — the state round-trip fixture's
   node order is deliberately arranged to match this (commented in the
   test).

`_check_unsupported` matches keywords on a WORD BOUNDARY (not bare
`startswith`) — an earlier draft flagged `sequenceDiagram`'s own
`participant` keyword as the excluded `par` (sequence "par" block)
construct.

`kind="dag"` reuses the flowchart dialect for `to_mermaid`; `from_mermaid`
never infers `"dag"` back (unrecoverable from syntax alone) — matches the
Test Specification, which only requires flowchart/state/sequence
round-trips, not dag.

19 tests in `test_mermaid.py` (7 named in the Test Specification plus
default-shape/mid-label-syntax/reserved-id-collision/empty-source
coverage), plus a fixture pair (`fixtures/mermaid/flowchart_mid_label.
{mmd,json}`) proving `from_mermaid` accepts the `-- text -->` mid-label
syntax even though `to_mermaid` only ever emits the pipe form.

Verification: `pytest packages/ai-parrot/tests/outputs/a2ui -q` → 696
passed (678 pre-existing + 18 new — one of the 19 new tests is a second
assertion block inside an existing test function, not a separate
collected test), 1 skipped; `ruff check` clean on all three touched/
created Python files.

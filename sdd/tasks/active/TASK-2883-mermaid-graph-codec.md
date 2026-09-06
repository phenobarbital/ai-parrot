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

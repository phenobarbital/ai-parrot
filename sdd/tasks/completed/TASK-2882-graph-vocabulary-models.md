# TASK-2882: Implement the GraphSpec vocabulary and validation

**Feature**: FEAT-529 - A2UI Graph component under the viz-core catalog
**Spec**: sdd/specs/a2ui-graph-component.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2881
**Assigned-to**: unassigned

## Context

Implements Module 1. GraphSpec is the single source of truth for the Graph wire
vocabulary; the codec, layout, builder, adapter, schema derivation, and
renderers must consume it rather than defining parallel shapes.

## Scope

- Create typed node, edge, group, position, layout, selection, and GraphSpec models.
- Use strict Pydantic models with camelCase wire aliases and forbidden extras.
- Validate IDs, edge endpoints, group membership, DAG cycles, and manual positions.
- Add viz-core size and accessibleDescription fields without presentation values.
- Export public graph types and the graph-size exception from graph/__init__.py.
- Add unit tests for all model invariants.

NOT in scope: catalog registration, lowering, Mermaid parsing, layout
coordinates, builders, adapters, or renderer/UI code.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py | CREATE | Graph vocabulary and validators |
| packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py | CREATE | Public graph exports |
| packages/ai-parrot/tests/outputs/a2ui/graph/test_models.py | CREATE | Model validation tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

    from typing import Any, Literal, Optional
    from pydantic import BaseModel, ConfigDict, Field
    from parrot.outputs.a2ui.catalog.base import CatalogValidationError

### Existing Signatures to Use

    # packages/ai-parrot/src/parrot/outputs/a2ui/models.py:400+
    class Component(BaseModel): ...

    # packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py:295-307
    class CatalogError(Exception): ...
    class CatalogValidationError(CatalogError): ...

The exact Graph model fields, aliases, literals, and LayoutResult boundary are
specified in the feature spec sections 2 and 3.

### Does NOT Exist

- parrot.outputs.a2ui.graph - the package does not exist.
- GraphSpec and its child models - no Graph vocabulary exists anywhere.
- GraphTooLargeError - no graph-specific size exception exists.
- Colour, font, pixel-size, or library-option fields - these are forbidden by the spec.

## Implementation Notes

- GraphEdge.from_ must use the wire alias from and support population by name.
- Validation preserves legal cycles for flowchart and state, while rejecting
  cycles only for kind=dag.
- layout.engine=manual requires a position for every node.
- Keep all models synchronous and free of I/O.

## Acceptance Criteria

- [ ] All specified literals, aliases, defaults, and extra=forbid settings exist.
- [ ] Duplicate node IDs, dangling edges, invalid groups, DAG cycles, and incomplete manual positions fail validation.
- [ ] size accepts only inline, tile, or hero; accessibleDescription round-trips.
- [ ] No model accepts colour, font, pixel, or renderer-library vocabulary.
- [ ] Public imports from parrot.outputs.a2ui.graph are stable.

## Test Specification

- test_graphspec_rejects_dangling_edge
- test_graphspec_rejects_duplicate_node_ids
- test_graphspec_dag_rejects_cycle
- test_graphspec_manual_requires_positions
- test_graphspec_size_and_description

## Agent Instructions

1. Verify the Pydantic version and current catalog validation exception before coding.
2. Keep this package independent of parrot.bots and renderer packages.
3. Do not add schema or catalog side effects to model imports.

### Completion Note

Implemented as specified: `GraphNode`/`GraphEdge`/`GraphGroup`/`Position`/
`GraphLayout`/`GraphSelection`/`GraphSpec` in `graph/models.py`, all
`extra="forbid"`, `GraphEdge`/`GraphLayout`/`GraphSpec` with
`populate_by_name=True` for their camelCase aliases (`from`,
`accessibleDescription`, `rankSep`, `nodeSep`). A single `@model_validator
(mode="after")` on `GraphSpec` enforces unique node ids, edge-endpoint
existence, group-membership invariants, `kind="dag"` acyclicity (DFS
3-colour cycle check via a private `_has_cycle()` helper — cycles stay
legal for every other `kind`), and `layout.engine="manual"` positions
completeness. 15 tests in `test_models.py`, including the five named in
the Test Specification plus group-invariant, alias/extra-forbid, and a
mechanical no-colour/font/pixel field-name guard (a model-level pre-echo
of the spec's later schema-level `test_graph_schema_has_no_colour_
vocabulary`).

Deliberately did NOT export `GraphTooLargeError` from `graph/__init__.py`
despite the task's Scope bullet mentioning "the graph-size exception" —
the Codebase Contract's own "Does NOT Exist" list states it doesn't exist
yet, and it belongs to `graph/layout.py` (Module 4 / TASK-2884, not yet
implemented at this point in the sequence). `graph/__init__.py` exports
only what `models.py` defines here; TASK-2883/2884 are expected to extend
it once `mermaid.py`/`layout.py` land.

Verification: `pytest packages/ai-parrot/tests/outputs/a2ui -q` → 678
passed (663 pre-existing + 15 new), 1 skipped; `ruff check` clean on all
three touched/created files.

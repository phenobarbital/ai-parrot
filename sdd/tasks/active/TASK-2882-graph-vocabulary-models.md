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

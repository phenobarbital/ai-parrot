# TASK-2881: Implement the viz-core catalog shell and resolution contract

**Feature**: FEAT-529 - A2UI Graph component under the viz-core catalog
**Spec**: sdd/specs/a2ui-graph-component.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implements Module 0, the foundation required before any viz-core component can
register. The existing registry is keyed by bare component name and the
producer/exporter are unscoped. The shell adds catalog identity while keeping
current Parrot and Basic behavior compatible.

## Scope

- Add viz-core constants, instructions, and vendored catalog source.
- Rekey component registration and lookup by (catalog_id, name).
- Preserve unique bare-name lookup and raise an explicit ambiguity error.
- Add catalog-scoped listing, instructions, export, and producer context.
- Add the catalog-aware renderer interception helper and UI catalog constant.
- Add focused regression tests for legacy and viz-core resolution.

NOT in scope: registering Graph; Graph models, codec, layout, builders, adapters,
renderers, UI rendering, or feature documentation.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py | MODIFY | Key registry, lookups, existence checks, and action gate resolution |
| packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/__init__.py | CREATE | Catalog ID, instructions, registration import hook |
| packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/spec/catalog.json | CREATE | Vendored viz-core catalog draft |
| packages/ai-parrot/src/parrot/outputs/a2ui/catalog/export.py | MODIFY | Catalog-scoped export and writer |
| packages/ai-parrot/src/parrot/outputs/a2ui/producer.py | MODIFY | Pass surface/component catalog IDs to instructions |
| packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_intercept.py | CREATE | Catalog-aware interception helper |
| packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-types.ts | MODIFY | Explicit catalogId and viz-core constant |
| packages/ai-parrot/tests/outputs/a2ui/catalog/test_catalog.py | MODIFY | Keyed registry and ambiguity tests |
| packages/ai-parrot/tests/outputs/a2ui/catalog/test_validation_v1.py | MODIFY | Catalog existence and gate regressions |
| packages/ai-parrot/tests/outputs/a2ui/catalog/test_export.py | MODIFY | Scoped export tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

    from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, ComponentDefinition, CatalogValidationError
    from parrot.outputs.a2ui.catalog import register_component, get_component, list_components, resolve_catalog, validate_envelope

### Existing Signatures to Use

    # packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py:95,107-117,181-194,219-256,266-294,392-397
    _CATALOG: dict[str, RegisteredComponent] = {}
    def register_component(name: str, *, requires_actions: bool = False,
                           catalog_id: str = DEFAULT_CATALOG_ID, is_primitive: bool = False,
                           allowed_parents: list[str] | None = None,
                           allowed_children: list[str] | None = None,
                           tool_only: bool = False) -> Callable[[type], type]: ...
    def get_component(name: str) -> RegisteredComponent: ...
    def list_components() -> list[ComponentDefinition]: ...
    def resolve_catalog(component_catalog_id: str | None, surface_catalog_id: str | None) -> str: ...
    def validate_envelope(envelope: CreateSurface | UpdateComponents, *,
                          origin: ProducerOrigin = ProducerOrigin.TOOL,
                          surface_catalog_id: str | None = None) -> None: ...

    # packages/ai-parrot/src/parrot/outputs/a2ui/catalog/export.py:215-220,299+
    def export_catalog_definition(*, catalog_id: str = DEFAULT_CATALOG_ID,
                                  include_basic: bool = True,
                                  executor: FunctionExecutor | None = None) -> dict[str, Any]: ...
    def write_catalog_definition(path: Path, *, catalog_id: str = DEFAULT_CATALOG_ID) -> None: ...

    # packages/ai-parrot/src/parrot/outputs/a2ui/producer.py:211,243
    instructions = catalog_instructions()
    validate_envelope(envelope, origin=ProducerOrigin.LLM, surface_catalog_id=catalog)

### Does NOT Exist

- _CATALOG[(catalog_id, name)] - the registry is currently bare-name keyed.
- get_component(name, catalog_id=...) - no catalog-aware lookup yet.
- catalog_header_instructions - no catalog header API yet.
- resolve_component_catalog / intercepts - no satellite helper yet.
- Graph registration - owned by TASK-2885.

## Implementation Notes

- Register Basic primitives under their own catalog while retaining the Parrot
  catalog's ref visibility for Basic names.
- A supplied catalog ID is an exact lookup. An omitted catalog ID succeeds only
  for one match and otherwise reports candidate IDs through CatalogError.
- Keep the seven existing bare-name callers working until the charts sibling
  spec introduces an intentional ambiguity.
- Import catalog.viz_core after Parrot registration to avoid circular imports.
- The vendored catalog JSON is not loaded at runtime by this task.

## Acceptance Criteria

- [ ] Duplicate (catalog_id, name) registrations fail; same names in different catalogs succeed.
- [ ] Bare-name lookup remains successful for every currently unique component.
- [ ] _component_exists distinguishes Basic, Parrot, and viz-core catalogs.
- [ ] Scoped instructions include the viz-core header and exclude unrelated catalog entries.
- [ ] Viz-core export validates against the vendored catalog-definition schema.
- [ ] Producer instructions are scoped to the surface and declared component catalogs.
- [ ] Existing A2UI catalog and validation tests remain green.

## Test Specification

- test_catalog.py: keyed registry, duplicate-pair, and ambiguity behavior.
- test_validation_v1.py: _component_exists and catalog-aware action-gate lookup.
- test_export.py: scoped viz-core export and catalog writer behavior.
- Add producer and satellite interception helper tests where existing fixtures permit.

## Agent Instructions

1. Verify the listed signatures against the current files before coding.
2. Run the catalog test suite after the registry rekey.
3. Keep this task as the first implementation commit in the feature.
4. Do not register Graph in this task.

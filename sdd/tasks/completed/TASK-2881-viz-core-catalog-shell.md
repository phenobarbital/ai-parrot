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

### Completion Note

Implemented as specified. `_CATALOG` is now keyed by `(catalog_id, name)`;
`register_component` allows idempotent re-registration of the SAME class
under an existing `(catalog_id, name)` pair (needed by the Basic Catalog's
existing `_register_primitives()` idempotency pattern) but raises
`CatalogError` for a genuinely different class claiming the same pair.
`get_component(name, catalog_id=None)` resolves uniquely or raises
`CatalogError` with `.candidates` (set post-construction — `CatalogError`
itself, in `catalog/base.py`, was intentionally left untouched; it is not
in this task's file list). `list_components`, `catalog_instructions`
(+ new `catalog_header_instructions`), `_component_exists`, and
`export_catalog_definition`/`write_catalog_definition` are all catalog-id
scoped now. `validate_envelope`'s action/tool-only gate and
allowed-parent/child checks resolve each component's catalog once and
reuse it (a `resolved_catalog_by_id` map) instead of a bare-name
`_CATALOG.get`. The producer scopes its system-prompt instructions to
`catalog=` when given (unscoped/aggregate when omitted — unchanged
default). Added `catalog/viz_core/__init__.py` (`VIZ_CORE_CATALOG_ID`,
`VIZ_CORE_INSTRUCTIONS`, verified byte-for-byte against the vendored
draft) and its vendored `spec/catalog.json`; no component registered here
(Module 2/TASK-2885 owns `Graph`). Added the satellite's
`_intercept.py` (`resolve_component_catalog`, `intercepts`). Extended
`a2ui-types.ts` with an explicit `catalogId` field and the
`VIZ_CORE_CATALOG_ID` constant.

**One file outside the task's table was touched to keep an existing
acceptance criterion ("Existing A2UI catalog and validation tests remain
green") true**: `packages/ai-parrot-visualizations/tests/outputs/
a2ui_renderers/test_semantic_classes.py::TestGoldensUntouched::
test_no_catalog_file_modified` is a FEAT-527-era diff guard that
allowlists specific historical file touches under `catalog/`; it does not
anticipate ANY future catalog work, and unconditionally failed against
this task's mandated `catalog/__init__.py`/`catalog/export.py` edits and
new `catalog/viz_core/` files. Extended its allowlist with an explicit,
commented FEAT-529 Module 0 entry, following the file's own established
per-feature-block convention.

Verification: `pytest packages/ai-parrot/tests/outputs/a2ui
packages/ai-parrot-visualizations/tests -q` → 948 passed, 1 skipped;
`ruff check` clean on every touched Python file. Frontend `a2ui-types.ts`
change is additive-only (new const + one explicit interface field
already covered by the existing index signature) — no `npm test` run
needed to validate it (no runtime logic added), deferred to a task that
touches `.svelte`/`.test.ts` files.

**Worktree note**: this worktree's `packages/ai-parrot/src/parrot/utils/
types.cpython-312-x86_64-linux-gnu.so` and `.../parsers/toml.cpython-312-
x86_64-linux-gnu.so` were copied from the main checkout's `.venv`-matching
build (gitignored, not committed) purely to run the test suite locally —
the editable install resolves `parrot.*`/`parrot_*` to the MAIN repo
checkout by default, so a `PYTHONPATH` prefix of this worktree's `packages/
*/src` dirs was used ahead of site-packages for every test run in this
task, to exercise the worktree's own source instead of the main repo's.

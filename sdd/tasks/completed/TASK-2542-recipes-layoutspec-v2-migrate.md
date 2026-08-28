# TASK-2542: Recetas: LayoutSpec v2, SUPPORTED_SCHEMA_VERSION=2, migrate_layout/migrate_store, freeze v2

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-2540
**Assigned-to**: unassigned
**Parallel**: true — Toca recipes/ y tools/infographic_recipes/; paralelo con TASK-2541.

---

## Context

Módulo 6 (parte recetas). G5 migración.

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- `LayoutSpec` v2: `component` + props top-level (`extra="allow"`), `child/children`, bindings `{path}`; `InfographicRecipe.schema_version` default 2; `SUPPORTED_SCHEMA_VERSION = 2`.
- `recipes/migrate.py`: `migrate_layout(layout: dict, *, from_version) -> dict` (usa `compat.normalize_legacy_component`); `async migrate_store(store, *, dry_run=False) -> MigrationReport` idempotente; stores leen v1 (auto-migrar en memoria) y escriben v2; `DBRecipeStore` transacción por receta.
- `RecipeRunner`/`freeze` producen v2; ejemplo YAML actualizado.

**NOT in scope**: CLI (open question; no implementar salvo que se resuelva). Adapter (2541).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py` | MODIFY |  |
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/store.py` | MODIFY |  |
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/__init__.py` | MODIFY |  |
| `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/migrate.py` | CREATE |  |
| `packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py` | MODIFY |  |
| `packages/ai-parrot/src/parrot/tools/infographic_recipes/freeze.py` | MODIFY |  |
| `packages/ai-parrot/tests/outputs/a2ui/recipes/test_models.py` | MODIFY |  |
| `packages/ai-parrot/tests/outputs/a2ui/recipes/test_store.py` | MODIFY |  |
| `packages/ai-parrot/tests/outputs/a2ui/recipes/test_migrate.py` | CREATE |  |
| `packages/ai-parrot/tests/tools/infographic_recipes/test_runner.py` | MODIFY |  |

---

## Codebase Contract (Anti-Hallucination)

> Verificado 2026-08-28 sobre `dev`. Re-verificar con `grep`/`read` antes de implementar: las tareas previas de esta feature cambian estos archivos.

### Verified Imports
```python
from parrot.outputs.a2ui.models import Component, CreateSurface            # packages/ai-parrot/src/parrot/outputs/a2ui/models.py
from parrot.outputs.a2ui.serialization import serialize, deserialize       # packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py:48/:64
from parrot.outputs.a2ui.catalog import register_component, get_component, list_components, catalog_instructions, validate_envelope  # packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py:57-165
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, ProducerOrigin, BasicNode, ComponentDefinition, CatalogValidationError  # packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py:38-124
from parrot.outputs.a2ui.renderers import RendererCapabilities, AbstractA2UIRenderer, register_a2ui_renderer  # packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py:48-97
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class LayoutSpec(BaseModel): extra="forbid"; component: str; properties: dict[str, Any]   # line 99
class InfographicRecipe(BaseModel): schema_version: int = 1                               # line 175 / :211 ; to_yaml :226 ; from_yaml :237
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/__init__.py: SUPPORTED_SCHEMA_VERSION (re-export :36, __all__ :76)
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/store.py: AbstractRecipeStore, FileRecipeStore, DBRecipeStore, RecipeNotFoundError, RecipeSchemaVersionError
# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py: RecipeRunner (ensambla envelope :66-79, resuelve renderer y entrega :610-640) ; freeze.py (freeze envelope → recipe)
```

### Does NOT Exist
- ~~`recipes.migrate` / `migrate_layout` / `migrate_store`~~ — no existen hasta TASK-2542; `SUPPORTED_SCHEMA_VERSION == 1`

---

## Implementation Notes

`RecipeSchemaVersionError` sólo para versiones > 2 o < 1.

### Key Constraints
- Async donde aplique; Pydantic v2; docstrings Google; `self.logger`/`logging.getLogger(__name__)`.
- Invariantes: G8 (a2ui core no importa `parrot.bots`/`parrot.clients`/DatasetManager), G3 (`version` sólo en `serialization.py`), G4 (`lower()` obligatorio salvo primitivas), `test_no_exec`.
- Wire siempre v1.0: props top-level, `{"path"}`, sobre por clave. Semántica de presentación en `metadata.extensions.parrot_*`.
- `source .venv/bin/activate` antes de cualquier comando; `uv` para deps.

### References in Codebase
- Spec §2 Data Models / New Public Interfaces y §6 Codebase Contract.
- Schemas oficiales: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/spec/*.json` (desde TASK-2534) o `https://raw.githubusercontent.com/google/A2UI/90157ec10f36cf8e192daa71c95d2684af20c756/specification/v1_0/`.

---

## Acceptance Criteria

- [ ] Implementación completa según Scope
- [ ] Tests de este task en verde y sin regresiones fuera de los `xfail` documentados
- [ ] `ruff check` sin errores en los archivos tocados
- [ ] Receta YAML v1 del repo carga y `migrate_layout` produce v2 que valida con `validate_envelope`

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2542:
    def test_layout_spec_v2_and_migrate(self): ...  # ver spec §4
    def test_recipe_schema_version_bump(self): ...  # ver spec §4
    def test_store_reads_v1_writes_v2(self): ...  # ver spec §4
    def test_migrate_store_idempotent_dry_run(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2542 — <título corto>`.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-28
**Notes**:
- `LayoutSpec` v2 (`recipes/models.py`): `component` field + `extra="allow"`
  top-level props (mirroring the wire `Component`), plus `child`/`children`
  (shape parity, unused) and a new `metadata: Optional[ComponentMetadata]`
  field. Added a `.props` property (`dict(self.model_extra or {})`) since
  `.properties` no longer exists as a real field. A binding's `optional`
  marker is NOT an inline sibling key on `{"path": ...}` (the wire's
  `DataBinding` is `extra="forbid"`) — it is hoisted into the layout's own
  `metadata.extensions.parrot_optional` (a flat list of pointers), exactly
  mirroring `baking._optional_paths()` for a wire `Component`.
  `InfographicRecipe.schema_version` default bumped 1 -> 2.
- `recipes/migrate.py` (new): `migrate_layout(layout, *, from_version)`
  reuses `compat.normalize_legacy_component` (wraps the v1 layout dict with
  a placeholder `id`, since that function mirrors a wire `Component` dict
  and requires one, then strips it back out) — this single reuse gets both
  the top-level-props promotion AND the `$bind`->`path` + `optional`-hoist
  for free, since a v1 `LayoutSpec` IS exactly that legacy single-component
  shape. `MigrationReport`/`migrate_store(store, *, dry_run=False)` sweep
  `store.list(owner=None)`, using the new `AbstractRecipeStore._raw_schema_version()`
  (NOT `store.get()`, which always returns an in-memory-migrated recipe) to
  tell "already v2 on disk" apart from "needs migrating" — each recipe is
  read+saved individually (`DBRecipeStore.save()` is a single atomic `SET`
  per recipe, satisfying "transacción por receta"), so one recipe's failure
  is collected in `MigrationReport.errors` without aborting the sweep.
- `recipes/store.py`: `SUPPORTED_SCHEMA_VERSION = 2`; `FileRecipeStore`/
  `DBRecipeStore.get()` now route through a new `_load_and_migrate(raw, ...)`
  helper that promotes a v1 `layout` dict via `migrate_layout` BEFORE
  Pydantic validation (a naive `InfographicRecipe.model_validate()` on a raw
  v1 dict would NOT error — v2 `LayoutSpec`'s `extra="allow"` would just
  silently store `properties` as an ordinary, unpromoted extra field, which
  is why the promotion must happen on the raw dict first). `migrate_layout`
  is imported LOCALLY inside `_load_and_migrate` to avoid a circular import
  with `recipes/migrate.py` (which imports `SUPPORTED_SCHEMA_VERSION`/
  `AbstractRecipeStore` from this module at its own top level).
  `RecipeSchemaVersionError` now only fires for `schema_version` outside
  `[1, 2]` (was a strict `!=` on the single supported version).
- `runner.py`/`freeze.py`: `_collect_bind_pointers` now detects `{"path":
  ...}` (via `is_valid_pointer`) instead of legacy `{"$bind": ...}`;
  optionality is read via a new `_optional_paths(layout)` helper off
  `layout.metadata.extensions.parrot_optional`, not an inline sibling key
  on the pointer itself. `_assemble_envelope_or_raise`/freeze's `LayoutSpec`
  construction use `layout.props`/`component.model_extra` instead of the
  now-nonexistent `.properties`.
- `examples/infographic_recipes/budget-variance-daily.yaml` updated to v2
  (`schema_version: 2`, top-level layout props, `{"path"}` bindings,
  `layout.metadata.extensions.parrot_optional: ["/narrative"]`) — verified
  by hand against the ACTUAL `migrate_layout()` output of the prior v1
  content (byte-for-byte, via a throwaway script), so the new example is
  exactly what migration produces, not a hand-guessed equivalent.
- **Verified the acceptance criterion end-to-end**: loaded the git-HEAD
  (pre-this-commit) v1 YAML, ran `migrate_layout(raw["layout"],
  from_version=1)`, fed the result into `build_infographic()`, and called
  `validate_envelope()` on the resulting `CreateSurface` — no errors.
  Repeated as `test_example_recipe_v1_migrates_to_validating_v2` in
  `test_migrate.py`.
- **Necessary "unblocking fix" pattern (same as TASK-2538/2539/2541 in this
  feature) — 3 files outside this task's own file list, NOT listed above**:
  `infographic_authoring.py`'s template-fallback `LayoutSpec(...)`,
  `infographic_toolkit.py`'s `_build_a2ui_envelope_from_layout` (`layout.properties`
  -> `layout.model_extra`), and `agents/finance_reporter.py`'s two
  hand-authored recipe layouts (`report_descriptor`/`dashboard_descriptor`).
  All three constructed/read a v1-shaped `LayoutSpec` directly; left
  unmigrated they would have silently produced corrupted envelopes (an
  unpromoted `"properties"` extra blob riding along as a useless top-level
  prop) rather than erroring loudly — verified via
  `test_finance_reporter_descriptors.py` (29 passed) that the fix is
  correct. Also updated the consequential test files these three feed:
  `test_example_recipe_yaml.py`, `test_finance_reporter_descriptors.py`,
  `test_publish_recipe.py`, `test_recipe_section_descriptor.py` (a stale
  `schema_version == 1` literal, unrelated to this task's own change but
  broken by the default bump), and 3 `LayoutSpec` construction literals in
  `test_infographic_toolkit_a2ui_wiring.py`.
- Pre-existing, unrelated failures confirmed via standalone diffing against
  git HEAD (NOT fixed, out of scope): `test_infographic_toolkit_a2ui_wiring.py`'s
  `_infographic()` helper (`["properties"]` KeyError — TASK-2547's own file,
  root cause is the emission code TASK-2547 owns, not this task's
  `LayoutSpec` change); `test_delivery_teams.py` (missing `azure` module);
  `test_publish_recipe.py`'s `agent` fixture (missing `google-genai` SDK in
  this venv) — none of these touch `LayoutSpec`/recipes.
- `pytest packages/ai-parrot/tests/outputs/a2ui/recipes/
  packages/ai-parrot/tests/tools/infographic_recipes/`: 180 passed.
  `packages/ai-parrot/tests/outputs/a2ui/` (excluding `test_producer.py`,
  TASK-2547's own file) + the consequential files above: 557 passed, 8
  pre-existing failures (documented, unrelated). `ai-parrot-server`'s
  `test_infographic_recipes.py`: 16 passed. `ruff check` (scoped to lines
  actually introduced by this task — pre-existing style debt in
  `agents/finance_reporter.py`/`infographic_authoring.py` confirmed via
  git-HEAD diff and left untouched): clean.

**Deviations from spec**: `infographic_authoring.py`, `infographic_toolkit.py`,
and `agents/finance_reporter.py` (plus their dependent test files) were
modified beyond this task's own file list — a necessary, narrowly-scoped
consequence of the `LayoutSpec` v2 migration without which these three
production call sites would silently construct/read corrupted layouts
(documented above, matching the established pattern from TASK-2538/2539/2541).

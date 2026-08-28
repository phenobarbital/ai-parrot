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

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none

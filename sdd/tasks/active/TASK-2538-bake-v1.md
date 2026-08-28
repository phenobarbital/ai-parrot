# TASK-2538: bake_envelope v1.0: path (abs/rel), call, ChildTemplate + @index, parrot_optional, post-condición

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2537
**Assigned-to**: unassigned
**Parallel**: false — Modifica baking.py; depende del evaluador.

---

## Context

Módulo 4 (parte bake). Sustituye el manejo de `$bind`/`optional` por `path`/`call`/template.

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- `_resolve_value` resuelve `{"path"}` (jsonpointer lazy, rutas relativas con scope) y evalúa `{"call"}` vía `FunctionEvaluator`; expande `children: ChildTemplate` clonando el componente plantilla por item con ids `<tpl>-<i>` y `@index`; respeta `metadata.extensions.parrot_optional: ["/ptr"]` (omitir clave); `_has_live_binding` detecta `path`/`call` residuales.
- `bake_envelope(envelope: CreateSurface) -> list[dict]` devuelve componentes v1.0 baked (props top-level).

**NOT in scope**: Modelos (hechos). Renderers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/baking.py` | MODIFY |  |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_baking.py` | MODIFY |  |
| `packages/ai-parrot/tests/outputs/a2ui/test_baking_v1.py` | CREATE |  |

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
# packages/ai-parrot/src/parrot/outputs/a2ui/baking.py
class BakeError(Exception) :31 ; _ABSENT = object() :38 ; _import_jsonpointer() :41 ; _load_jsonpointer() :48 (lazy)
def _resolve_value(value: Any, data_model: dict) -> Any :66   # maneja {"$bind", "optional"}
def _has_live_binding(value: Any) -> bool :111
def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]] :122
```

### Does NOT Exist
- ~~`optional` dentro de `DataBinding`~~ — `additionalProperties:false`; usar `parrot_optional`

---

## Implementation Notes

Mantener `jsonpointer` lazy (extra del satélite). El clon de template debe también re-escribir `child`/`children` internos con el sufijo `-<i>`.

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
- [ ] Post-bake: `_has_live_binding(comp) is False` para todos
- [ ] Template de 3 filas produce 3 clones con `${@index}` resuelto a 0,1,2

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2538:
    def test_bake_resolves_path_call_template(self): ...  # ver spec §4
    def test_bake_optional_binding_omitted(self): ...  # ver spec §4
    def test_bake_unresolvable_raises(self): ...  # ver spec §4
    def test_bake_relative_path_in_template_scope(self): ...  # ver spec §4
    def test_bake_postcondition_no_live_binding(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2538 — <título corto>`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none

# TASK-2541: Adaptador Infographic → primitivas v1.0 (Tabs/Divider/List/CheckBox/Image.fit)

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-2540
**Assigned-to**: unassigned
**Parallel**: true — Sólo toca adapters/infographic.py y sus tests; paralelo con TASK-2542.

---

## Context

Módulo 6 (parte adapter). 19 `BlockType`.

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- Emitir `CreateSurface` v1.0 con `root`; `tab_view/accordion` → `Tabs{tabs:[{title, child}]}` (eliminar `_flatten_container` salvo para profundidad > `_MAX_NESTING_DEPTH`); `divider` → `Divider`; `bullet_list`/`steps` → `List{direction:'vertical'}` de `Text`; `checklist` → `List` de `CheckBox{label,value}`; `image` → `Image{url, fit, description}`; `card_grid` → `Row` de `InfoCard`; resto como hoy pero con props top-level, `{path}` y `InfoCard`.
- Actualizar los 55 tests del adapter.

**NOT in scope**: Toolkit Infographic (TASK-2547). Recetas (TASK-2542).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` | MODIFY |  |
| `packages/ai-parrot/tests/outputs/a2ui/adapters/test_infographic_adapter.py` | MODIFY |  |

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
# packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py
CHART_TYPE_MAP ~:80 ; _CHART_FALLBACK = "bar" :91 ; _MAX_NESTING_DEPTH = 4 :95 ; _X_COLUMN = "label" :97
_as_dict :100 · _clean :128 · _descriptor(component, properties) :133 · _unique :138 · _lines :145 · _text(value) :154 (prefiere "en")
class _SectionAccumulator :175 ; class _Converter :225: _bind_rows :235 · _chart :241 · _table :273 · _hero_card :301 · _timeline :312 · _progress :329 · _card_like :343 · _chain :401 · _steps :419 · _code :437 · _card_grid :448 · walk :468 · _flatten_container :538
def infographic_response_to_envelope(...) -> CreateSurface :573
# packages/ai-parrot/src/parrot/models/infographic.py: class BlockType (19 miembros) :78-97
```

### Does NOT Exist
- ~~`Card` propio~~ — `InfoCard`
- ~~`_descriptor(component, properties)` con dict `properties`~~ — pasa a props top-level

---

## Implementation Notes

Mantener `CHART_TYPE_MAP` y `_text()` single-language. `test_import_rule` debe seguir en verde.

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
- [ ] `validate_envelope(infographic_response_to_envelope(resp))` sin errores para los fixtures existentes

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2541:
    def test_adapter_blocktype_remap(self): ...  # ver spec §4
    def test_adapter_emits_root_and_catalog_id(self): ...  # ver spec §4
    def test_adapter_output_validates(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2541 — <título corto>`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none

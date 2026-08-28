# TASK-2536: Catálogo básico: modelos de las 18 primitivas con enums exactos, Checkable e INSTRUCTIONS

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2535
**Assigned-to**: unassigned
**Parallel**: true — Sólo crea archivos bajo catalog/basic/; paralelo con TASK-2537.

---

## Context

Módulo 3. Fuente de verdad: `load_spec('catalog')['components']`.

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- `catalog/basic/layout.py` (Row, Column, List, Card, Tabs, Divider, Modal), `media.py` (Text, Image, Icon, Video, AudioPlayer), `inputs.py` (Button, TextField, CheckBox, ChoicePicker, Slider, DateTimeInput) — modelos Pydantic que extienden `Component` con props tipadas, enums y defaults exactos del JSON (Text.variant {caption,body}; Image.fit {contain,cover,fill,none,scaleDown}=fill, variant 6 valores; Row/Column justify 7 / align 4; List.direction; Divider.axis; Button.variant; TextField.variant; ChoicePicker.variant/displayStyle/options/filterable; Tabs.tabs[{title,child}]; Modal{trigger,content}; Icon.name enum 60 | {svgPath} | DataBinding; Slider{value*,max*,min=0,steps}; DateTimeInput{value,enableDate,enableTime,min,max,label}); `Checkable` mixin (`checks`).
- `INSTRUCTIONS` por primitiva (derivadas de las `description` del JSON) y registro `register_component(name, catalog_id=BASIC_CATALOG_ID, is_primitive=True)` con `allowed_parents/children` del JSON.
- `basic_components() -> list[ComponentDefinition]`.
- Test parametrizado ×18 que compara enums/required/defaults del modelo con el JSON vendorizado (anti-drift interno).

**NOT in scope**: Funciones (TASK-2537). Renderizado (TASK-2543+).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/layout.py` | CREATE |  |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/media.py` | CREATE |  |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/inputs.py` | CREATE |  |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/__init__.py` | MODIFY | registro + basic_components |
| `packages/ai-parrot/tests/outputs/a2ui/catalog/test_basic_primitives.py` | CREATE |  |

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
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py
DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"                 # line 38
class ProducerOrigin(str, Enum): LLM / TOOL                           # line 41
class BasicNode(BaseModel): extra="allow"; component: str; properties: dict; children: list["BasicNode"]  # line 53
BasicTree = BasicNode                                                 # line 75
class ComponentDefinition(BaseModel): name; catalog_id = DEFAULT_CATALOG_ID; schema_ (alias "schema"); instructions = ""; requires_actions = False  # line 79
@dataclass class RegisteredComponent: definition; component_cls      # line 100
class CatalogError :112 ; ComponentContractError :116 ; CatalogValidationError.__init__(...) :124/:133
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
def register_component(...) -> decorator (exige lower())              # line 57 / :81
def unregister_component(name) :105 ; get_component(name) -> RegisteredComponent :110
def list_components() -> list[ComponentDefinition] :119
def catalog_instructions() -> str :124   # línea 131: f"{d.name}: {d.instructions}".rstrip(": ") — bug latente
def _iter_nested_component_names(value) -> list[str] :138
def validate_envelope(envelope: CreateSurface, *, origin: ProducerOrigin = ProducerOrigin.TOOL) -> None  # line 165
```

### Does NOT Exist
- ~~`lower()` en primitivas~~ — no aplica (`is_primitive=True`)
- ~~`Text.role`~~ — no es prop de v1.0; va en `metadata.extensions.parrot_role` (TASK-2539)

---

## Implementation Notes

Generar el test comparando `model.model_json_schema()` con el JSON vendorizado para `enum`, `default`, `required`.

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
- [ ] `len(basic_components()) == 18`
- [ ] `Slider(id='s', value=1)` sin `max` → `ValidationError`

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2536:
    def test_basic_component_enums[18](self): ...  # ver spec §4
    def test_basic_required_fields(self): ...  # ver spec §4
    def test_basic_registered_with_basic_catalog_id(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2536 — <título corto>`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none

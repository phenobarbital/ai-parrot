# TASK-2540: build_form(), export_catalog_definition(), builders emiten root + catalogId

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2539
**Assigned-to**: unassigned
**Parallel**: false — Depende del catálogo parrot v1.0.

---

## Context

Módulo 5 (parte composición/export/builders). G2, G6.

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- `catalog/parrot/form.py`: `FormField`, `FormSubmit`, `build_form(*, id_prefix, title, fields, submit) -> list[Component]` → `Column` con `TextField/CheckBox/ChoicePicker/DateTimeInput/Slider` (según `input`), `checks` (`required`), y `Button{child: Text, action:{event:{name, context}}}`.
- `catalog/export.py`: `export_catalog_definition(*, catalog_id=DEFAULT_CATALOG_ID, include_basic=True) -> dict` válido contra `catalog_definition.json` (`$schema, $id, protocolVersion:'1.0', catalogId, instructions, components` con `$ref` a `catalog.json#/components/<Name>` para los básicos y `SCHEMA` inline para parrot, `functions` con `$ref` a las básicas); `write_catalog_definition(path)`.
- `builders.py`: `build_surface` garantiza `id='root'` (Column) y `catalogId=DEFAULT_CATALOG_ID`; `build_card` emite `InfoCard`; todos emiten props top-level y `{path}`.

**NOT in scope**: Runtime de acciones (FEAT-469). `functions` derivadas de tools (FEAT-469).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/form.py` | CREATE |  |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/export.py` | CREATE |  |
| `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` | MODIFY |  |
| `packages/ai-parrot/tests/outputs/a2ui/test_builders.py` | MODIFY |  |
| `packages/ai-parrot/tests/outputs/a2ui/catalog/test_export.py` | CREATE |  |
| `packages/ai-parrot/tests/outputs/a2ui/catalog/test_build_form.py` | CREATE |  |

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
# packages/ai-parrot/src/parrot/outputs/a2ui/producer.py
DEFAULT_MAX_ATTEMPTS = 3 :45 ; class ProducerResult(BaseModel) :48
def _extract_envelope(output) -> tuple[Optional[CreateSurface], Optional[str]] :71
def _repair_prompt(base_prompt: str, error_text: str, offending: Any) -> str :91
# generate_envelope(...) ~:110-192: client.ask(..., structured_output=StructuredOutputConfig(output_type=CreateSurface)); param `catalog=` no-op (:114); degrade-to-text
# packages/ai-parrot/src/parrot/outputs/a2ui/emission.py: def finalize_a2ui_response(response: Any) -> None :18
# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py: emit_a2ui :171/:217 ; _build_a2ui_envelope, _build_a2ui_envelope_from_layout :501-969 ; build_surface freeze :1295
# packages/ai-parrot/src/parrot/tools/interactive_toolkit.py: emit_a2ui :94 ; _build_a2ui_envelope via build_card :~345
# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py: _DEFAULT_COMPONENT_ID = "blk-000" :37 ; _binding :40 ; build_surface :44 · build_chart :71 · build_kpicard :91 · build_card :111 · build_datatable :128 · build_infographic :151
```
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
- ~~`FormComponent`~~ — eliminado en TASK-2539
- ~~`export_functions(tool_manager)`~~ — FEAT-469

---

## Implementation Notes

`build_form` es `ProducerOrigin.TOOL`-only por construcción (lleva `action`).

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
- [ ] `export_catalog_definition()` valida contra `load_spec('catalog_definition')`
- [ ] `build_surface(...).components[0].id == 'root'`

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2540:
    def test_build_form_composition(self): ...  # ver spec §4
    def test_export_catalog_definition_valid(self): ...  # ver spec §4
    def test_export_includes_basic_refs_and_instructions(self): ...  # ver spec §4
    def test_builders_emit_root(self): ...  # ver spec §4
    def test_build_card_emits_infocard(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2540 — <título corto>`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none

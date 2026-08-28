# TASK-2532: Wire v1.0 models: envelope-by-key, Component v1.0, common types, full message set

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: false — Bloque secuencial #1: todo depende de estos modelos.

---

## Context

Implementa el Módulo 1 (parte modelos) del spec §2 Data Models. Reemplaza el dialecto propio (`messageType`, `properties{}`, `$bind`) por modelos Pydantic que SON el wire A2UI v1.0.

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- Reescribir `models.py`: `DataBinding{path}`, `FunctionCall{call,args,catalogId?}`, `DynamicString/Number/Boolean/StringList`, `ChildTemplate{componentId,path}`, `ChildList`, `EventAction`, `Action` (exactamente uno de `event`|`functionCall`), `CheckRule`, `ValidationResult`, `AccessibilityAttributes`, `Extensions` (claves UAX #31, `a2ui_` reservado), `ComponentMetadata`, `SurfaceMetadata`.
- `Component` v1.0: `id`, `component`, `catalog_id` (alias `catalogId`), `child`, `children: ChildList`, `weight`, `accessibility`, `checks`, `action`, `metadata`; props del catálogo top-level (`extra="allow"`). Eliminar `properties` y `BINDING_KEY="$bind"` de los modelos nuevos (conservar `is_valid_pointer`).
- Mensajes A→R: `CreateSurface` (`surfaceId`, `catalogId?`, `sendDataModel=False`, `components`, `dataModel`, `metadata`), `UpdateComponents`, `UpdateDataModel{surfaceId, path?, value}` (`value` requerido, admite `None`), `DeleteSurface`, `CallRendererFunction`, `AgentFunctionResponse`.
- Mensajes R→A: `ActionMessage`, `CallAgentFunction`, `RendererFunctionResponse`, `ErrorMessage` — leer la forma exacta de `renderer_to_agent.json` (descargar temporalmente de `google/A2UI@90157ec10f36cf8e192daa71c95d2684af20c756`; la copia vendorizada llega en TASK-2534).
- Sobres `A2UIAgentMessage` / `A2UIRendererMessage`: `version: Literal["v1.0"]` + validator 'exactamente una clave de mensaje'. Eliminar `ActionResponse` y `CallFunction` (0.9.1).
- Tests unitarios de forma (ver Test Specification).

**NOT in scope**: `serialize/deserialize/compat` (TASK-2533); validación jsonschema (TASK-2535); actualizar builders/adapters/componentes (tareas posteriores — se romperán temporalmente sus tests; marcar con `xfail(strict=False, reason="FEAT-470 wire")` SOLO los tests que dependan de la forma vieja, no borrarlos).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/models.py` | MODIFY | Reescritura completa al wire v1.0 |
| `packages/ai-parrot/tests/outputs/a2ui/test_models.py` | MODIFY | Tests de forma v1.0 |
| `packages/ai-parrot/tests/outputs/a2ui/_v1.py` | CREATE | Helpers de fixtures (constructores de sobres/componentes v1.0) reutilizados por el resto de tareas |

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
# packages/ai-parrot/src/parrot/outputs/a2ui/models.py  (estado ACTUAL — este task lo reescribe)
BINDING_KEY = "$bind"                                                 # line 50
_JSON_POINTER_RE = re.compile(r"^(?:/(?:[^/~\s]|~[01])*)*$")          # line 56
def is_valid_pointer(pointer: str) -> bool                            # line 59
def is_binding_expression(value: Any) -> bool                         # line 79
class Component(BaseModel): extra="allow"; id; component; properties: dict; children: list[str]   # line 123/138
class A2UIMessageBase(BaseModel): extra="forbid"                      # line 157
class CreateSurface(A2UIMessageBase): message_type alias "messageType"; surface_id; catalog_id (obligatorio); components; data_model  # line 167
class UpdateComponents :183 · class UpdateDataModel(contents: dict) :196 · class Action :220 · class ActionResponse :230 · class CallFunction :241
A2UIMessage = Annotated[Union[...], Field(discriminator="message_type")]  # ~:270
```
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py
A2UI_VERSION = "1.0"; VERSION_FIELD = "version"                       # lines 38, 41
_ADAPTER: TypeAdapter = TypeAdapter(A2UIMessage)                      # ~:45
def serialize(message: A2UIMessageBase) -> dict[str, Any]             # line 48  (model_dump(by_alias=True, mode="json") + version)
def deserialize(data: dict | str | bytes) -> A2UIMessageBase          # line 64  (strip version; NO asserta el valor)
def to_jsonl(messages) -> str :98 ; def iter_jsonl(text) -> Iterator :112
```

### Does NOT Exist
- ~~`parrot.outputs.a2ui.models.DeleteSurface / CallRendererFunction / AgentFunctionResponse / CallAgentFunction / RendererFunctionResponse / ErrorMessage / A2UIAgentMessage / A2UIRendererMessage / DataBinding / FunctionCall / ChildTemplate / CheckRule / ValidationResult`~~ — no existen hasta TASK-2532
- ~~`parrot.outputs.a2ui.compat`~~ — no existe hasta TASK-2533
- ~~`Component.properties`~~ — deja de existir tras este task
- ~~`ActionResponse`, `CallFunction`~~ — se eliminan (no están en v1.0)

---

## Implementation Notes

Mantener `populate_by_name=True` y alias camelCase. `Action` y sobres usan `model_validator(mode="after")` para 'exactamente uno'. Docstring de módulo enlaza a https://a2ui.org/specification/v1.0-a2ui/.

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
- [ ] `Component(id='x', component='Text', text='hi').model_dump(by_alias=True)` no contiene `properties`
- [ ] `A2UIAgentMessage` con dos claves de mensaje → `ValidationError`
- [ ] `UpdateDataModel(surface_id='s')` sin `value` → `ValidationError`; con `value=None` OK
- [ ] `pytest packages/ai-parrot/tests/outputs/a2ui/test_models.py -v` en verde

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2532:
    def test_component_props_top_level(self): ...  # ver spec §4
    def test_children_list_or_template(self): ...  # ver spec §4
    def test_data_binding_path_only(self): ...  # ver spec §4
    def test_update_data_model_value_required(self): ...  # ver spec §4
    def test_envelope_exactly_one_key(self): ...  # ver spec §4
    def test_action_event_xor_function_call(self): ...  # ver spec §4
    def test_extensions_keys_uax31_and_reserved_prefix(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2532 — <título corto>`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none

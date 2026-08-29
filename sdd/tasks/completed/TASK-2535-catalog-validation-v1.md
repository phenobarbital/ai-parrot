# TASK-2535: Validación de catálogo v1.0: resolve_catalog, validate_message (jsonschema), validate_envelope ampliado, FunctionDefinition/allowed_*

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2533, TASK-2534
**Assigned-to**: unassigned
**Parallel**: false — Cierra el bloque secuencial; desbloquea los carriles paralelos.

---

## Context

Módulo 2 (parte validación). Resolución estricta de `catalogId`, `root`, ids únicos, `allowedParents/Children`, códigos v1.0, gate LLM/TOOL.

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- `catalog/base.py`: `ComponentDefinition.allowed_parents/allowed_children`, `is_primitive: bool = False`; nuevo `FunctionDefinition` (`name, catalog_id, args_schema, return_type, allowed_callers, requires_user_activation`); `CatalogValidationError.code` con constantes `CATALOG_UNRESOLVED`, `UNALLOWED_PARENT`, `UNALLOWED_CHILD`, `INVALID_FUNCTION_CALL`, `MISSING_ROOT`, `DUPLICATE_ID`, `DANGLING_CHILD`.
- `catalog/__init__.py`: `register_component(name, *, catalog_id=DEFAULT_CATALOG_ID, is_primitive=False, ...)` — `lower()` obligatorio salvo `is_primitive`; `register_function`; `resolve_catalog(component_catalog_id, surface_catalog_id) -> str`; `validate_message(msg)` con jsonschema contra `agent_to_renderer`/`renderer_to_agent`; `validate_envelope(envelope, *, origin, surface_catalog_id=None)` que además valida cada componente contra el schema del catálogo resuelto (básico: `catalog.json#/components/<Name>`; parrot: `SCHEMA` del componente) y aplica `allowed*`, `root`, ids, hijos, y gate (LLM no puede emitir `action` ni `callAgentFunction`). Reporta TODOS los errores.
- Corregir el `rstrip(": ")` de `catalog_instructions()`.

**NOT in scope**: Registrar las 18 primitivas (TASK-2536). Export del catálogo (TASK-2540).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py` | MODIFY |  |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` | MODIFY |  |
| `packages/ai-parrot/tests/outputs/a2ui/test_catalog.py` | MODIFY |  |
| `packages/ai-parrot/tests/outputs/a2ui/catalog/test_validation_v1.py` | CREATE |  |

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

### Does NOT Exist
- ~~`parrot.outputs.a2ui.catalog.basic`~~ (`BASIC_CATALOG_ID`, `SPEC_COMMIT`, `load_spec`, `FunctionEvaluator`) — no existe hasta TASK-2534/2536/2537
- ~~`validate_envelope(..., surface_catalog_id=)`~~ — parámetro nuevo de este task
- ~~`register_function`~~ — nuevo

---

## Implementation Notes

Hasta TASK-2536 el catálogo básico no tiene componentes registrados: `validate_envelope` debe resolver los nombres básicos consultando `load_spec('catalog')['components']` directamente (fuente de verdad), no el registro Python.

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
- [ ] Envelope con `Text` sin `catalogId` y superficie `catalogId=parrot` valida (parrot incluye el básico)
- [ ] Sin `root` → error `MISSING_ROOT`
- [ ] `origin=LLM` + `Button.action` → `CatalogValidationError`

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2535:
    def test_validate_message_agent_to_renderer(self): ...  # ver spec §4
    def test_resolve_catalog_precedence(self): ...  # ver spec §4
    def test_validate_root_required_and_unique_ids(self): ...  # ver spec §4
    def test_dangling_child_reported(self): ...  # ver spec §4
    def test_unallowed_parent_child_codes(self): ...  # ver spec §4
    def test_llm_origin_rejects_action(self): ...  # ver spec §4
    def test_all_errors_reported_at_once(self): ...  # ver spec §4
    def test_catalog_instructions_no_rstrip_bug(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2535 — <título corto>`.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-28
**Notes**:
- `catalog/base.py`: added `is_primitive`/`allowed_parents`/`allowed_children`
  to `ComponentDefinition`; added `FunctionDefinition`; added the seven
  error-code constants; `CatalogValidationError` now supports both a
  single `code=` (e.g. `resolve_catalog`) and an aggregate `issues=` list
  (e.g. `validate_envelope`'s "report everything" contract), keeping
  `.unknown_components`/`.action_components` for backward compatibility.
- `catalog/__init__.py`: `resolve_catalog`, `register_function`/
  `get_function`/`list_functions`, `validate_message` (jsonschema against
  the vendored `agent_to_renderer`/`renderer_to_agent` schemas via
  `catalog.basic.schema_registry()`), and a full `validate_envelope`
  rewrite for the v1.0 flat-adjacency-list wire (root required, duplicate
  ids, dangling `child`/`children` (list or `ChildTemplate`),
  `allowed_parents`/`allowed_children`, and the LLM action gate).
- Per the task's own Implementation Notes (the Python registry has no
  basic-catalog primitives until TASK-2536), `_component_exists` checks
  the vendored `catalog.json`'s component list directly as the source of
  truth for the Basic Catalog, and ALSO treats it as available under
  `DEFAULT_CATALOG_ID` (parrot) — implementing G2 ("el catálogo parrot
  incluye el básico") at the validation layer.
- LLM action gate: implemented as `comp.action is not None` (checks the
  actual wire instance) OR the legacy `ComponentDefinition.requires_actions`
  flag (kept for backward compatibility with existing registered
  components/tests) — origin=LLM rejects either.
- `catalog_instructions()`'s `.rstrip(": ")` bug fixed by simply removing
  the (unnecessary, since `list_components()` already filters non-empty
  instructions) strip call.
- `test_catalog.py`: updated `_surface()` helper to wrap components in a
  `root` Column (v1.0 requires `id=="root"`); added `ClassVar` annotations
  to two pre-existing `SCHEMA = {...}` class attributes to satisfy
  `ruff RUF012` since the file was touched.
- `pytest test_catalog.py catalog/`: 31 passed. `ruff check`: clean.

**Deviations from spec**: none — the dual `requires_actions` +
`comp.action is not None` LLM gate is additive (keeps existing behavior
working) on top of the new wire-level check the spec calls for.

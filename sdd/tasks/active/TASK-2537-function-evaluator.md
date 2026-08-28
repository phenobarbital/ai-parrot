# TASK-2537: FunctionEvaluator: 14 funciones renderer-side, formatString, @index, ValidationResult, FunctionDefinitions del básico

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2535
**Assigned-to**: unassigned
**Parallel**: true — Archivo nuevo `catalog/basic/functions.py`; paralelo con TASK-2536.

---

## Context

Módulo 4 (parte funciones). Evaluador puro Python para bake y para tests; sin `eval`/`exec` (test_no_exec).

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- `FunctionEvaluator.evaluate(call, *, data_model, scope_path='', index=None)`; `format_string(template, ...)` con `${/abs}`, `${rel}`, `${fn(arg:'v', other:${/p})}`, escape `\${`; `check(rule) -> ValidationResult`.
- Funciones: `required, regex, length, numeric, email` → `ValidationResult`; `formatString, formatNumber, formatCurrency, formatDate, pluralize` → str; `and, or, not` → bool; `openUrl` → no-op agent-side marcado `requiresUserActivation`; `@index` sólo en scope de template (fuera → `INVALID_FUNCTION_CALL`).
- `basic_functions() -> list[FunctionDefinition]` desde `load_spec('catalog')['functions']` (args schema, returnType, allowedCallers default `rendererOnly`, `requiresUserActivation`).
- Parser de `${...}` con un tokenizador manual (sin regex recursivo ni `eval`).

**NOT in scope**: Integración en bake (TASK-2538). Ejecución de funciones agent-side (FEAT-469).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/functions.py` | CREATE |  |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/__init__.py` | MODIFY | basic_functions |
| `packages/ai-parrot/tests/outputs/a2ui/catalog/test_functions.py` | CREATE |  |

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
# packages/ai-parrot/src/parrot/outputs/a2ui/baking.py
class BakeError(Exception) :31 ; _ABSENT = object() :38 ; _import_jsonpointer() :41 ; _load_jsonpointer() :48 (lazy)
def _resolve_value(value: Any, data_model: dict) -> Any :66   # maneja {"$bind", "optional"}
def _has_live_binding(value: Any) -> bool :111
def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]] :122
```

### Does NOT Exist
- ~~`eval`/`exec`~~ — prohibidos (`test_no_exec.py`)
- ~~`babel`/`pendulum`~~ — no añadir deps; `formatDate` con `datetime.strftime` y patrón mínimo `yyyy/MM/dd/HH/mm/ss`; `formatCurrency` con `locale`-free formato `{symbol}{n:,.2f}`

---

## Implementation Notes

Rutas relativas se resuelven contra `scope_path` (JSON Pointer del item del template). Unknown function → `CatalogValidationError(code=INVALID_FUNCTION_CALL)`.

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
- [ ] `format_string('${/a} \\${x}', data_model={'a':1}) == '1 ${x}'`
- [ ] `len(basic_functions()) == 14`
- [ ] `test_no_exec` sigue en verde

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2537:
    def test_format_string_paths_and_escape(self): ...  # ver spec §4
    def test_format_string_function_named_args(self): ...  # ver spec §4
    def test_index_only_in_template_scope(self): ...  # ver spec §4
    def test_validators_return_validation_result(self): ...  # ver spec §4
    def test_boolean_functions(self): ...  # ver spec §4
    def test_unknown_function_invalid_call(self): ...  # ver spec §4
    def test_basic_functions_count_14(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2537 — <título corto>`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none

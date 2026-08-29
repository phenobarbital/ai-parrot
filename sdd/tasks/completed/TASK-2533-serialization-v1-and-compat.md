# TASK-2533: serialization v1.0 (version 'v1.0', envelope-by-key) + compat.normalize_legacy

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2532
**Assigned-to**: unassigned
**Parallel**: false — Secuencial: cierra el bloque wire.

---

## Context

Módulo 1 (parte serialización + compat). G3: `version` lo escribe sólo `serialization.py`. G5: compat sólo de lectura.

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- `A2UI_VERSION = "v1.0"`; `serialize(msg)` produce `{"version":"v1.0", "<clave>": {...}}` a partir de cualquier mensaje interno o de un sobre ya envuelto.
- `deserialize(data)`: si `"messageType" in data` → `compat.normalize_legacy(data)` + `DeprecationWarning`; luego valida como `A2UIAgentMessage` o `A2UIRendererMessage` según la clave.
- `to_jsonl` / `iter_jsonl` sobre sobres v1.0 (una línea = un sobre).
- Crear `compat.py`: `is_legacy_envelope`, `normalize_legacy` (sobre → clave; `properties` → top-level; `{"$bind"}` → `{"path"}` y `optional:true` → `metadata.extensions.parrot_optional`; `Card` con `properties` → `InfoCard`; `updateDataModel.contents{a,b}` → lista de N sobres `{path,value}` preservando orden; `callFunction` → `callRendererFunction`), `normalize_legacy_component`.
- Actualizar `__init__.py` exports.

**NOT in scope**: Validación jsonschema (TASK-2535). Migración de recetas (TASK-2542). Ningún emisor usa `compat`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py` | MODIFY | Sobre por clave, version v1.0, compat en deserialize |
| `packages/ai-parrot/src/parrot/outputs/a2ui/compat.py` | CREATE | normalize_legacy |
| `packages/ai-parrot/src/parrot/outputs/a2ui/__init__.py` | MODIFY | Exports |
| `packages/ai-parrot/tests/outputs/a2ui/test_serialization.py` | MODIFY |  |
| `packages/ai-parrot/tests/outputs/a2ui/test_compat.py` | CREATE |  |

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
# packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py
A2UI_VERSION = "1.0"; VERSION_FIELD = "version"                       # lines 38, 41
_ADAPTER: TypeAdapter = TypeAdapter(A2UIMessage)                      # ~:45
def serialize(message: A2UIMessageBase) -> dict[str, Any]             # line 48  (model_dump(by_alias=True, mode="json") + version)
def deserialize(data: dict | str | bytes) -> A2UIMessageBase          # line 64  (strip version; NO asserta el valor)
def to_jsonl(messages) -> str :98 ; def iter_jsonl(text) -> Iterator :112
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
- ~~`parrot.outputs.a2ui.compat`~~ — no existe hasta TASK-2533
- ~~flag de emisión legado~~ — rechazado; no añadir
- ~~`deserialize` que asserte `version == '1.0'`~~ — el valor viejo se acepta sólo vía normalize_legacy

---

## Implementation Notes

`normalize_legacy` es puro (dict→dict|list[dict]); no importa `parrot.bots`/`parrot.clients`. Heurística Card legado = 'tiene `properties`'.

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
- [ ] `serialize(CreateSurface(...))['version'] == 'v1.0'` y la única otra clave es `createSurface`
- [ ] `deserialize(legacy_envelope)` emite `DeprecationWarning` y equivale al v1.0 esperado
- [ ] `grep -rn '"1.0"' packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py` vacío

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2533:
    def test_serialize_envelope_by_key(self): ...  # ver spec §4
    def test_serialize_never_emits_message_type(self): ...  # ver spec §4
    def test_legacy_normalize_create_surface(self): ...  # ver spec §4
    def test_legacy_normalize_card_to_infocard(self): ...  # ver spec §4
    def test_legacy_update_data_model_contents_split(self): ...  # ver spec §4
    def test_legacy_bind_optional_to_extensions(self): ...  # ver spec §4
    def test_jsonl_roundtrip(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2533 — <título corto>`.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-28
**Notes**:
- `serialize()` accepts either an inner message (`CreateSurface`, ...) or an
  already-built envelope, and produces exactly `{"version": "v1.0",
  "<key>": {...}}`. Explicit `value: null` on `UpdateDataModel`/
  `AgentFunctionResponse`/`RendererFunctionResponse` is deliberately
  preserved through `exclude_none=True` dumping (re-injected post-dump) —
  losing it would silently turn a "delete this key" into a no-op.
- `deserialize()` detects `"messageType" in data` via
  `compat.is_legacy_envelope`, normalizes via `compat.normalize_legacy`
  (`DeprecationWarning`), then validates as `A2UIAgentMessage`/
  `A2UIRendererMessage` by inspecting which key set is present.
- `compat.normalize_legacy` supports the four legacy message types the
  Scope names explicitly (`createSurface`, `updateComponents`,
  `updateDataModel`, `callFunction`). Legacy `action`/`actionResponse` are
  intentionally NOT translated — the v1.0 `ActionMessage` shape requires
  `sourceComponentId`/`timestamp`/`context` that the legacy `Action` model
  never carried, so a lossless mapping isn't possible; `normalize_legacy`
  raises a clear `ValueError` for any unsupported `messageType` rather than
  guessing (spec §7 Known Risks: "no adivinar").
- `deserialize()`'s return type widens to
  `A2UIAgentMessage | A2UIRendererMessage | list[A2UIAgentMessage]` — the
  list case is the one legacy `updateDataModel` with >1 `contents` key,
  which fans out into N v1.0 envelopes with no single-message equivalent.
  This is a deliberate, documented extension of the original single-message
  contract, driven directly by the Scope's own "N sobres" requirement.
- Reintroduced `A2UIMessageBase` in TASK-2532's `models.py` (see that
  task's Completion Note) so `__init__.py`'s exports here didn't need to
  drop the existing `emission.py` `isinstance` check.
- `pytest test_serialization.py test_compat.py`: 27 passed. `ruff check`:
  clean. `grep -rn '"1.0"' serialization.py`: empty (confirmed only
  `"v1.0"` appears).

**Deviations from spec**: legacy `action`/`actionResponse` messageTypes are
NOT normalized (see Notes) — the Scope bullet list never named them as
translation targets, and the v1.0 `ActionMessage` shape genuinely lacks a
lossless source in the legacy `Action` model.

# TASK-2546: Transporte v1.0: A2A URI/mime, handlers a2ui_envelope, deep links con action v1.0, integraciones

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2540, TASK-2545
**Assigned-to**: unassigned
**Parallel**: false — Cruza tres paquetes; secuencial.

---

## Context

Módulo 8. G10.

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- `a2a/models.py`: `A2UI_EXTENSION_URI = "https://a2ui.org/a2a-extension/a2ui/v1.0"`, `A2UI_MEDIA_TYPE = "application/a2ui+json"`; `Part.metadata = {"mimeType": A2UI_MEDIA_TYPE, "extensionUri": ...}`; `from_a2ui_envelope` lee la clave `createSurface` del sobre (normalizando legado vía `deserialize` si trae `messageType`); `_reject_action_components` inspecciona `action` en componentes v1.0.
- `handlers/agent.py`: `a2ui_envelope` = sobre v1.0 (dict) o lista; sin cambios de forma externa adicionales.
- `deeplink.py`: `ResumePayload.action_payload` debe validar como `A2UIRendererMessage` (`action`); `handlers/deeplink.py` y `integrations/a2ui_resume.py`: `build_structured_message` → `{"type":"a2ui_action","action":<sobre>}`; telegram/msteams wrappers usan el mismo formato.
- `emission.py`/`bots/base.py` líneas 498-500/1421-1494: sin cambio de lógica; verificar que `finalize_a2ui_response` acepta el sobre nuevo.

**NOT in scope**: Montar `setup_deeplink_routes` en manager (FEAT-469 M7). `agent_capabilities` (FEAT-469).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/a2a/models.py` | MODIFY |  |
| `packages/ai-parrot/src/parrot/outputs/a2ui/deeplink.py` | MODIFY |  |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | mínimo |
| `packages/ai-parrot-server/src/parrot/handlers/deeplink.py` | MODIFY |  |
| `packages/ai-parrot-integrations/src/parrot/integrations/a2ui_resume.py` | MODIFY |  |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY |  |
| `packages/ai-parrot/tests/a2a/test_a2ui_extension_emit.py` | MODIFY |  |
| `packages/ai-parrot/tests/outputs/a2ui/test_deeplink.py` | MODIFY |  |
| `packages/ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py` | MODIFY |  |
| `packages/ai-parrot-server/tests/test_deeplink_resume_web.py` | MODIFY |  |
| `packages/ai-parrot-integrations/tests/telegram/test_deeplink_resume.py` | MODIFY |  |
| `packages/ai-parrot-integrations/tests/msteams/test_deeplink_resume.py` | MODIFY |  |

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
# packages/ai-parrot/src/parrot/a2a/models.py
class Part: text, file_uri, file_bytes, file_media_type, filename, data: Optional[Dict], metadata: Optional[Dict]   # line 129
A2UI_EXTENSION_URI = "https://a2ui.org/extensions/a2a/display/v1" :338
A2UI_MEDIA_TYPE = "application/vnd.a2ui.envelope+json" :339
def _reject_action_components(envelope: Dict) -> None :342
class Artifact.from_a2ui_envelope(cls, envelope, *, name="a2ui-surface", artifact_id=None) ~:375  # lee envelope.get("messageType")
# packages/ai-parrot-server/src/parrot/handlers/agent.py
# stream final dict: envelope['a2ui_envelope'] = ai_message.a2ui_envelope   lines 2701-2705
# non-stream A2UI: {"input","output","output_mode":"a2ui","a2ui_envelope"}  lines 2819-2827
# packages/ai-parrot-server/src/parrot/handlers/deeplink.py
def build_structured_message(payload: ResumePayload) -> str  # {"type":"a2ui_action_resume","action":...} ~:55
class DeepLinkResumeHandler(service, invoker).handle(token) ~:66 ; def setup_deeplink_routes(...) :113 (NO montado en manager)
# packages/ai-parrot-integrations/src/parrot/integrations/a2ui_resume.py
def build_structured_message(action_payload: dict) -> str :30 ; class ChannelDeepLinkResume.__init__ :44 ; async resume(token, *, inject) :55
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
def _get_deeplink_resume(self) :316 ; submitted_data = turn_context.activity.value :346 ; a2ui_token = submitted_data.get("a2ui_token") :366-368
# packages/ai-parrot/src/parrot/outputs/a2ui/deeplink.py
_KEY_TEMPLATE = "a2ui:deeplink:{token_id}" :41 ; _DEFAULT_TTL_SECONDS = 900 :42 ; class ResumePayload(BaseModel) (action_payload) :53 ; class DeepLinkService.__init__ :77 ; _resume_url(channel, token_id) :94
```

### Does NOT Exist
- ~~`AgentCapabilities.a2ui`~~ — FEAT-469
- ~~`setup_deeplink_routes` montado~~ — no lo está; no montarlo aquí

---

## Implementation Notes

El test `test_agent_a2ui_stream.py` valida el contrato por inspección de fuente: actualizar sus asserts.

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
- [ ] `A2UI_MEDIA_TYPE == 'application/a2ui+json'`
- [ ] Deep link con payload no-`action` → `ValueError` al crear

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2546:
    def test_a2a_constants_v1(self): ...  # ver spec §4
    def test_artifact_from_v1_envelope(self): ...  # ver spec §4
    def test_handler_a2ui_envelope_is_v1(self): ...  # ver spec §4
    def test_deeplink_payload_is_action_envelope(self): ...  # ver spec §4
    def test_resume_message_format(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2546 — <título corto>`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none

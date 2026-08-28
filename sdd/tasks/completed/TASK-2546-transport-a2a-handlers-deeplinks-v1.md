# TASK-2546: Transporte v1.0: A2A URI/mime, handlers a2ui_envelope, deep links con action v1.0, integraciones

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2540, TASK-2545
**Assigned-to**: sdd-worker (session)
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

> Verificado 2026-08-28 sobre `dev`; **re-verificado 2026-08-29 al implementar** —
> el contrato original estaba desactualizado tras TASK-2534/2536/2537/2540/2545
> (modelos v1.0 por sobre-clave ya existían; `msteams/wrapper.py` ya tenía la
> rama `a2ui_action`). Contrato corregido abajo refleja el estado real al
> implementar TASK-2546.

### Verified Imports
```python
from parrot.outputs.a2ui.models import Component, CreateSurface, Action, EventAction, A2UIAgentMessage, A2UIRendererMessage  # packages/ai-parrot/src/parrot/outputs/a2ui/models.py
from parrot.outputs.a2ui.serialization import serialize, deserialize, A2UI_VERSION  # packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py:104/:155/:55
```

### Existing Signatures Used (as of TASK-2546 implementation)
```python
# packages/ai-parrot/src/parrot/a2a/models.py
class Part: text, file_uri, file_bytes, file_media_type, filename, data: Optional[Dict], metadata: Optional[Dict]   # line 129
A2UI_EXTENSION_URI = "https://a2ui.org/a2a-extension/a2ui/v1.0"   # was ".../extensions/a2a/display/v1"
A2UI_MEDIA_TYPE = "application/a2ui+json"                          # was "application/vnd.a2ui.envelope+json"
def _reject_action_components(components: list[Component]) -> None   # rewritten: inspects parsed Component.action, no catalog lookup
class Artifact.from_a2ui_envelope(cls, envelope, *, name="a2ui-surface", artifact_id=None)
    # now: envelope = deserialize(envelope) (normalizes legacy `messageType` via
    # compat internally); reads message.create_surface; Part.metadata uses "mimeType" key.
# packages/ai-parrot-server/src/parrot/handlers/agent.py
# stream final dict: envelope['a2ui_envelope'] = ai_message.a2ui_envelope   (unchanged, envelope-agnostic; comments now note FEAT-470/v1.0)
# non-stream A2UI: {"input","output","output_mode":"a2ui","a2ui_envelope"}  (unchanged, envelope-agnostic)
# packages/ai-parrot-server/src/parrot/handlers/deeplink.py
def build_structured_message(payload: ResumePayload) -> str  # {"type":"a2ui_action","action":...} — was "a2ui_action_resume"
class DeepLinkResumeHandler(service, invoker).handle(token) ; def setup_deeplink_routes(...) (still NOT montado en manager)
# packages/ai-parrot-integrations/src/parrot/integrations/a2ui_resume.py
def build_structured_message(action_payload: dict) -> str  # {"type":"a2ui_action","action":...} — was "a2ui_action_resume"
class ChannelDeepLinkResume.__init__ ; async resume(token, *, inject)
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py (UNCHANGED — TASK-2545 scope, not touched here)
def _get_deeplink_resume(self) :337 ; submitted_data = turn_context.activity.value :365
a2ui_token = submitted_data.get("a2ui_token") :385 (deep-link resume path, tested here)
a2ui_action = submitted_data.get("a2ui_action") :420 (Adaptive Cards native-input submit path — already routes
    to {"type": "a2ui_action", "action": <full v1.0 envelope>, "values": {...}} — TASK-2545's own scope/tests)
# packages/ai-parrot/src/parrot/outputs/a2ui/deeplink.py
_KEY_TEMPLATE = "a2ui:deeplink:{token_id}" ; _DEFAULT_TTL_SECONDS = 900
class ResumePayload(BaseModel): action_payload now @field_validator'd — must validate as
    A2UIRendererMessage with a non-null `.action` (i.e. {"version":"v1.0","action":{...}});
    non-action/malformed payload raises ValueError (ValidationError, a ValueError subclass) at construction.
class DeepLinkService.__init__ ; mint()'s action_label now derives from action_payload["action"]["name"] (was "label" key, no longer on the wire)
```

### Does NOT Exist
- ~~`AgentCapabilities.a2ui`~~ — FEAT-469
- ~~`setup_deeplink_routes` montado~~ — no lo está; no montarlo aquí (confirmed unchanged)
- ~~`parrot.outputs.a2ui.catalog.get_component` usage in `a2a/models.py`~~ — removed; `_reject_action_components` no longer consults the catalog (v1.0 `Component.action` is checked directly)

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

- [x] Implementación completa según Scope
- [x] Tests de este task en verde y sin regresiones fuera de los `xfail` documentados (33/33 tests verdes en los 6 archivos; suites hermanas `tests/a2a/` + `tests/outputs/a2ui/` sin regresión: 438 passed, 1 pre-existing fail unrelated a este task — `test_delivery_teams.py` falla igual en `dev`/baseline por falta del paquete `azure` — y 1 pre-existing collection error unrelated — `test_producer.py` importa `catalog.components`, módulo renombrado a `catalog.parrot` por una task anterior fuera de este scope)
- [x] `ruff check` sin errores **nuevos** en los archivos tocados (429 issues pre-existentes de estilo sin config de ruff en el repo — mismo conteo por archivo/regla antes y después del diff, verificado con `git stash`; TASK-2545 dejó precedente idéntico)
- [x] `A2UI_MEDIA_TYPE == 'application/a2ui+json'`
- [x] Deep link con payload no-`action` → `ValueError` al crear

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

**Completed by**: sdd-worker (Claude session), on behalf of jesuslarag@gmail.com
**Date**: 2026-08-29
**Notes**:
- `a2a/models.py`: `A2UI_EXTENSION_URI`/`A2UI_MEDIA_TYPE` bumped to the v1.0 values;
  `Part.metadata` now keys the mime under `"mimeType"` (was `"mediaType"`).
  `_reject_action_components` was rewritten to inspect the v1.0
  `Component.action` field directly on parsed `Component` instances — no more
  catalog `get_component`/`requires_actions` lookup (that mechanism still
  exists and is used elsewhere by `catalog.validate_envelope`'s LLM/TOOL
  gate; unrelated to this display-only A2A check).
  `from_a2ui_envelope` now routes through
  `parrot.outputs.a2ui.serialization.deserialize` (the sole owner of legacy
  normalization per spec G5 "Compat sólo de entrada") instead of a raw
  `envelope.get("messageType")` check — a legacy `messageType` payload is
  normalized (with `DeprecationWarning`) and accepted only if it resolves to
  `createSurface`; anything else (including a legacy payload that resolves to
  zero/multiple envelopes, e.g. an empty-`contents` legacy `updateDataModel`)
  is rejected with a `ValueError` mentioning `createSurface`.
- `outputs/a2ui/deeplink.py`: `ResumePayload.action_payload` gained a
  `@field_validator` that validates the dict as
  `A2UIRendererMessage.model_validate(value)` and requires `.action is not
  None` — a non-`action` or malformed envelope raises `ValueError`
  (`pydantic.ValidationError` is a `ValueError` subclass) at construction.
  `DeepLinkService.mint()`'s `action_label` fallback was updated from the
  no-longer-existent `action_payload["label"]` to
  `action_payload["action"]["name"]` (falling back to `"Open"`) since the v1.0
  envelope has no top-level `label` key.
- `handlers/deeplink.py` (server) and `integrations/a2ui_resume.py`: both
  `build_structured_message` implementations changed their `"type"` tag from
  `"a2ui_action_resume"` to `"a2ui_action"` — unifying with the tag TASK-2545's
  Teams Adaptive Cards native-input submit branch
  (`msteams/wrapper.py::_handle_card_submission`) already expects/produces,
  so both ends of the pipe (deep-link resume vs. direct Adaptive Card submit)
  agree on one wire contract. Verified TASK-2545's exact shape by reading its
  test (`msteams/tests/test_a2ui_submit.py`): the `"action"` key there carries
  the **full v1.0 envelope** (`{"version": "v1.0", "action": {...}}`), not just
  the inner `ActionMessage` — `ResumePayload.action_payload` mirrors that
  exact shape for consistency.
- `integrations/telegram/wrapper.py`: no functional change needed —
  `_handle_deeplink_resume` already delegates to
  `ChannelDeepLinkResume`/`build_structured_message` in `a2ui_resume.py`,
  which now emits the unified `"a2ui_action"` format automatically. Added a
  docstring note documenting the wire contract for future readers (Telegram
  has no Adaptive Cards submit path, deep-link resume only).
- `handlers/agent.py` (server): genuinely no logic change — both the stream
  and non-stream `a2ui_envelope` call sites already forward
  `ai_message.a2ui_envelope`/`response.a2ui_envelope` verbatim
  (envelope-agnostic), and that value is guaranteed v1.0-shaped upstream by
  `parrot.outputs.a2ui.emission.finalize_a2ui_response` (verified by reading
  it — unmodified, out of this task's scope per Scope text). Added comments
  documenting the FEAT-470/v1.0 sobre semantics so the source-inspection test
  (`test_handler_a2ui_envelope_is_v1`) has something concrete to assert on.
- `emission.py`/`bots/base.py`: read, not modified, per Scope instruction —
  `finalize_a2ui_response` is envelope-agnostic (accepts whatever
  `response.a2ui_envelope`/`response.output` carries; only re-serializes when
  `output` is an `A2UIMessageBase` instance) and needed no change.
- All 6 target test files updated to v1.0 shapes; the 5 named
  Test-Specification tests
  (`test_a2a_constants_v1`, `test_artifact_from_v1_envelope`,
  `test_handler_a2ui_envelope_is_v1`, `test_deeplink_payload_is_action_envelope`,
  `test_resume_message_format`) all exist verbatim and pass.
- Codebase Contract section above was stale (line numbers, old wire
  constants, old `Component`/message shapes, old `catalog`-based action
  check) — corrected per the actual TASK-2534–2545 state.

**Deviations from spec**:
- `DeepLinkService.mint()`'s `action_label` derivation (not explicitly named
  in Scope) was updated from `action_payload.get("label", "Open")` to derive
  from the v1.0 envelope's `action.name` — the old `"label"` key has no home
  on the v1.0 wire and would otherwise have silently defaulted to `"Open"`
  for every deep link. Small, contained, in-file change; noted here for
  visibility rather than silently left as latent dead code.
- `ruff check` reports 429 pre-existing style violations across the touched
  files (no `ruff.toml`/`[tool.ruff]` config in the repo, so ruff runs its
  full default rule set against files with substantial pre-existing debt
  unrelated to A2UI). Verified via a `git stash`/`git stash pop` before/after
  diff that this task's diff introduces **zero** new violations (identical
  per-file/per-rule counts, one `UP006` in `a2a/models.py` actually
  disappeared). Same situation and same resolution as TASK-2545.

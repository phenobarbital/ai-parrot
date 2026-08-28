# TASK-2545: Adaptive Cards: inputs nativos + Action.Submit{a2ui_action} + Action.OpenUrl; Teams wrapper enruta a2ui_action

**Feature**: FEAT-470 — A2UI v1.0 Dialect
**Spec**: `sdd/specs/a2ui-v1-dialect.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2543
**Assigned-to**: unassigned
**Parallel**: true — Toca adaptive_cards.py y msteams/wrapper.py; sin solape con 2544.

---

## Context

Módulo 7 (parte Adaptive Cards) + parte de Módulo 8 (Teams). Decisión: inputs nativos ya.

Brainstorm: `sdd/proposals/a2ui-v1-dialect.brainstorm.md` (Option B). Diagnóstico: `artifacts/a2ui_v1_gap_diagnosis.md` (no versionado; el spec §1 lo resume).

---

## Scope

- `adaptive_cards.py`: `TextField→Input.Text` (`variant`: longText→isMultiline, number→style number, obscured→style password), `CheckBox→Input.Toggle`, `ChoicePicker→Input.ChoiceSet` (`isMultiSelect`, `style` compact/expanded), `Slider→Input.Number{min,max}`, `DateTimeInput→Input.Date`/`Input.Time`, `Button{action.event}→Action.Submit{data:{a2ui_action:<sobre action v1.0>, surfaceId}}`, `Button{functionCall openUrl}→Action.OpenUrl`; `Input.id` = `path` del binding (codificado si Teams rechaza `/` — ver riesgo); resto de primitivas → TextBlock/Container/ColumnSet/Image/Media.
- `msteams/wrapper.py`: junto a `a2ui_token`, rama `a2ui_action = submitted_data.get('a2ui_action')` → construir turno estructurado `{"type":"a2ui_action","action":<sobre>,"values":{...inputs...}}` e inyectar por el mismo camino que el resume.

**NOT in scope**: `agentFunctionResponse`/runtime (FEAT-469). Deep links (2546).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py` | MODIFY |  |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY |  |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_adaptive_cards.py` | MODIFY |  |
| `packages/ai-parrot-integrations/tests/msteams/test_a2ui_submit.py` | CREATE |  |
| `packages/ai-parrot/tests/notifications/test_teams_adaptive_cards.py` | MODIFY | si aplica |

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
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py
_CONTAINER_COMPONENTS = {"Column":"a2ui-col","Row":"a2ui-row","Card":"a2ui-card"} :47
@register_a2ui_renderer("ssr_html", RendererCapabilities(...)) :50 ; class SSRHTMLRenderer :59 ; _render_component :109 ; _render_basic(node: BasicNode) -> str :129 (solo Text/Image/contenedores)
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py: PDFRenderer :99 ; _rasterize(document: str) -> bytes :137 (weasyprint lazy :36)
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py: InteractiveHTMLRenderer :217 ; _render_top :261 ; _render_descriptor :271 ; _render_via_lowering :292 ; _render_basic :310 ; _render_chart :333 ; _render_datatable :387 ; _render_infographic :423 ; _BEHAVIOR_JS inline ES2017 ; _CHART_JS_SOURCE vendorizado ; _safe_json
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py: EChartsRenderer :56 ; _build_option(props) :110 ; _wrap_html :139
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/folium_map.py: FoliumMapRenderer :61 ; _iter_points :116
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py: AdaptiveCardsRenderer :64 ; render() emite deep links como TextBlock(text=f"{link.action_label}: {link.url}") :81-84 ; _element_for_component :101 ; _map_node(node: BasicNode) -> ACElement :120
```
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
- ~~`Action.Submit`/`Input.*` en adaptive_cards.py~~ — no existen hoy
- ~~`activity.value['a2ui_action']`~~ — rama nueva

---

## Implementation Notes

Slack/email no reciben submits: allí `Button` sigue siendo deep link (TASK-2546 mantiene ese camino).

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
- [ ] Card generada valida como Adaptive Card 1.5 (schema vendorizado si existe en el repo; si no, comprobación estructural)
- [ ] Simulación de `activity.value` con `a2ui_action` produce el turno estructurado

---

## Test Specification

```python
# nombres tomados del spec §4 — el agente escribe el cuerpo
class TestTASK2545:
    def test_adaptive_cards_native_inputs(self): ...  # ver spec §4
    def test_adaptive_cards_submit_carries_action(self): ...  # ver spec §4
    def test_adaptive_cards_openurl(self): ...  # ver spec §4
    def test_teams_wrapper_routes_a2ui_action(self): ...  # ver spec §4
    def test_input_id_encoding_roundtrip(self): ...  # ver spec §4
```

---

## Agent Instructions

1. Lee el spec `sdd/specs/a2ui-v1-dialect.spec.md` (secciones 2, 3, 6, 7) y este task.
2. Verifica `Depends-on` en `sdd/tasks/completed/`.
3. Verifica el Codebase Contract con `grep`/`read`; actualízalo si cambió.
4. Marca `in-progress` en `sdd/tasks/index/a2ui-v1-dialect.json`.
5. Implementa; ejecuta `pytest` de los paths afectados; guarda evidencia en `artifacts/logs/`.
6. Mueve este archivo a `sdd/tasks/completed/`, marca `done` en el índice y rellena la Completion Note.
7. Commit: `sdd: TASK-2545 — <título corto>`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none

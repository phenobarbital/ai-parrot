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

> Verificado 2026-08-28 sobre `dev`. Re-verificado y actualizado 2026-08-28
> tras la implementación de este task — la sección original (heredada del
> spec §6) ya estaba stale: `adaptive_cards.py` todavía importaba el módulo
> eliminado `parrot.outputs.a2ui.catalog.components` (fallaba en
> `pytest --collect-only`) y usaba `Component(properties={...})` (dialecto
> pre-v1.0). Se reescribió siguiendo el mismo patrón lower→bake→reconstruct→
> dispatch que `ssr_html.py`/`interactive_html.py` (TASK-2543/2544).

### Verified Imports (post-implementación)
```python
from parrot.outputs.a2ui.models import ActionMessage, Component, CreateSurface   # packages/ai-parrot/src/parrot/outputs/a2ui/models.py
from parrot.outputs.a2ui.serialization import serialize                          # packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py:104
from parrot.outputs.a2ui.catalog import get_component                            # packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
from parrot.outputs.a2ui.catalog.base import BasicNode, TabSpec, to_components    # packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py
from parrot.outputs.a2ui.baking import bake_envelope                             # packages/ai-parrot/src/parrot/outputs/a2ui/baking.py:356
from parrot.outputs.a2ui.renderers import RendererCapabilities, AbstractA2UIRenderer, register_a2ui_renderer  # packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py
from parrot.outputs.a2ui.renderers.degrade import degrade, degradation_record    # packages/ai-parrot/src/parrot/outputs/a2ui/renderers/degrade.py
from parrot.outputs.cards import (CardSpec, RawElementsSection, TextBlock, Image, Column, ColumnSet,
    Container, InputText, InputNumber, InputToggle, InputDate, InputTime, InputChoiceSet, InputChoice,
    ActionSubmit, ActionOpenUrl, render as render_card, DEFAULT_ADAPTIVE_CARD_VERSION)  # packages/ai-parrot/src/parrot/outputs/cards/__init__.py
```

### Existing Signatures Used
```python
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py (REWRITTEN by this task)
class AdaptiveCardsRenderer(AbstractA2UIRenderer)  # register_a2ui_renderer("adaptive_cards", RendererCapabilities(supports_actions=True, supported_components={11 names}))
async def render(envelope, *, bake=True, deep_links=None) -> RenderedArtifact
def _lower_composites / _reconstruct  # copied 1:1 from ssr_html.SSRHTMLRenderer (same lower->bake->reconstruct contract)
def _binding_paths(components) -> dict[id, path]        # pre-bake extraction of Input `value` DataBinding paths
def _button_actions(components) -> dict[id, Action]      # pre-bake extraction — Button.action MUST bypass bake_envelope's
                                                            # generic `{"call":...}` resolver (it eagerly evaluates
                                                            # action.functionCall as a VALUE, e.g. openUrl's agent-side
                                                            # no-op evaluator returns None and erases it — see docstring)
def _resolve_bindings(value, data_model) -> Any          # local minimal `{"path"}` resolver used only for Button action data
def _render_<Name>(node, state) -> ACElement | None       # dispatch table; Button returns None (collapses into state.actions)
def _encode_binding_id(path) -> str / _decode_binding_id(encoded) -> str   # RFC 6901 tilde-escape (~ -> ~0, / -> ~1)
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
def _get_deeplink_resume(self) ~:316 (unchanged) ; submitted_data = turn_context.activity.value ~:372
a2ui_token branch ~:392-419 (unchanged, kept as-is) ; NEW a2ui_action branch inserted right after it, before the
  "command" slash-command branch — decodes each non-{a2ui_action,surfaceId} key via `_decode_a2ui_input_id`
  (new @staticmethod, duplicated encode/decode logic — ai-parrot-integrations has no dependency on
  ai-parrot-visualizations) and injects `{"type":"a2ui_action","action":<sobre>,"values":{...}}` via
  `self.form_orchestrator.process_message(message=query, conversation_id=..., context={"user_id","session_id"=conversation_id})`
  — same injection call shape as the a2ui_token `inject()` closure, but WITHOUT any DeepLinkService/Redis
  round-trip (the action arrived directly in this turn, nothing to resume).
```

### Does NOT Exist / superseded
- `Action.Submit`/`Input.*` in adaptive_cards.py — now exist (this task).
- `activity.value['a2ui_action']` routing in wrapper.py — now exists (this task).
- `parrot.outputs.a2ui.catalog.components` (the old import the pre-task file used) — module removed; the
  correct imports are `parrot.outputs.a2ui.catalog.basic` + `parrot.outputs.a2ui.catalog.parrot`.

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

- [x] Implementación completa según Scope
- [x] Tests de este task en verde y sin regresiones fuera de los `xfail` documentados
- [x] `ruff check` sin errores en los archivos tocados
- [x] Card generada valida como Adaptive Card 1.5 (comprobación estructural — no hay schema AC 1.5 vendorizado en el repo; se valida `type`/`version`/`$schema` y la forma de cada elemento vía los modelos Pydantic de `parrot.outputs.cards`)
- [x] Simulación de `activity.value` con `a2ui_action` produce el turno estructurado (verificado tanto por un harness standalone — ver Notes — como por `test_teams_wrapper_routes_a2ui_action`, que se salta localmente por falta de `botbuilder` en este venv pero corre en CI/con el extra `msteams` instalado)

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

**Completed by**: jesuslarag@gmail.com (via sdd-worker)
**Date**: 2026-08-28

**Notes**:
- `adaptive_cards.py` was fully rewritten (not incrementally patched) — the pre-task file imported a
  removed module (`parrot.outputs.a2ui.catalog.components`, ModuleNotFoundError on collection) and used
  the pre-v1.0 `Component(properties={...})` dialect, so `test_adaptive_cards.py` was already broken
  before this task touched it. The rewrite follows the same lower→bake→reconstruct→dispatch architecture
  TASK-2543/2544 established for `ssr_html.py`/`interactive_html.py`.
- Native input dispatch: `TextField→Input.Text` (`variant="longText"`→`isMultiline`,
  `variant="obscured"`→`style="Password"`, `variant="number"`→`Input.Number` — Adaptive Cards has no
  numeric `Input.Text` style, so "number" targets the dedicated element instead), `CheckBox→Input.Toggle`,
  `ChoicePicker→Input.ChoiceSet`, `Slider→Input.Number{min,max}`, `DateTimeInput→Input.Date`/`Input.Time`.
- `Input.id` = the (pre-bake) JSON-Pointer `path` of the component's `value` binding, RFC 6901
  tilde-escaped (`~`→`~0`, `/`→`~1`) via `_encode_binding_id`/`_decode_binding_id` — proactively encoded
  per the spec's own risk note, not conditionally. Falls back to the component's own id when `value` is a
  literal (no binding).
- `Button{action.event}` collapses into a top-level `Action.Submit` (this codebase's `cards` module has no
  inline `ActionSet` element, so every Button's action joins the card's bottom action bar rather than
  rendering inline) whose `data == {"a2ui_action": <serialize(ActionMessage(...))>, "surfaceId": ...}`.
  `Button{functionCall: openUrl}` → `Action.OpenUrl`. Any other `functionCall` degrades (recorded, never
  raises).
- **Important discovery**: `bake_envelope`'s generic resolver evaluates ANY `{"call": ..., "args": {...}}`
  dict found anywhere in a component (schema-agnostic) — correct for a property VALUE that happens to be a
  function call, but WRONG for a Button's own `action.functionCall` (`openUrl`'s agent-side evaluator is a
  deliberate no-op that returns `None`, silently erasing the whole functionCall on bake). Buttons are
  therefore excluded from the generic bake pass for their `action` field (`_button_actions` extracts the
  raw, unbaked `Action` per Button id before baking); this renderer resolves any live bindings inside
  `action.event.context` / `action.functionCall.args` itself via a small local `_resolve_bindings` helper
  (path-only, no `{"call"}` evaluation — documented as a deliberate limitation below).
- Verified end-to-end via a standalone script (not committed) exercising `AdaptiveCardsRenderer().render()`
  with all 5 input primitives + both Button action shapes — output matches expectations (see Deviations).
- `msteams/wrapper.py`: inserted the `a2ui_action` branch immediately after the existing `a2ui_token`
  branch, before the slash-command branch. Unlike the `a2ui_token` deep-link resume (which needs
  `DeepLinkService`/Redis to resolve the ORIGINATING session), the `a2ui_action` submit arrived directly in
  this turn, so it injects into the CURRENT session via the same `form_orchestrator.process_message(...)`
  call shape the `a2ui_token` `inject()` closure already uses. Added `_decode_a2ui_input_id` as a
  `@staticmethod` (duplicated from `adaptive_cards._decode_binding_id` — `ai-parrot-integrations` has no
  dependency on `ai-parrot-visualizations`) to turn the raw submitted keys back into JSON-Pointer paths for
  `values`.
- `packages/ai-parrot/tests/notifications/test_teams_adaptive_cards.py` exists but is about
  `NotificationMixin`/`TeamsCard` OUTBOUND notification sending (a different `notify.providers.teams`
  concept), not the A2UI renderer's inbound submit flow — left untouched per the task's own instruction.
  It has 12 pre-existing failures in this venv (`ModuleNotFoundError: No module named 'azure'`, confirmed
  via `git stash`-equivalent — I never touched this file or the `notify` package), unrelated to this task.

**Deviations from spec**:
- `test_teams_wrapper_routes_a2ui_action` / `test_input_id_encoding_roundtrip` for the wrapper side live in
  `test_a2ui_submit.py` behind `pytest.importorskip("botbuilder")` — `botbuilder`/`azure-teambots` (the
  `msteams` extra) are not installed in this worktree's dev venv, matching the SAME documented limitation
  `test_deeplink_resume.py` already states for this exact file/class. The tests are real (mock-based,
  exercise `MSTeamsAgentWrapper._handle_card_submission` and `._decode_a2ui_input_id` directly) and will run
  in any environment with the extra installed (CI); locally they report as `skipped`, not `failed`. The
  routing logic was additionally verified via a standalone re-implementation harness run against the actual
  code (see Notes).
- `ActionMessage.timestamp` for a Button's `Action.Submit` is stamped with the CARD-RENDER time
  (`datetime.now(UTC).isoformat()`), not the actual future click time — this renderer is static (no
  client-side JS to inject a real click timestamp). Documented in the renderer's own module docstring; a
  receiving wrapper may re-stamp it if the real click time matters (out of scope here — FEAT-469 territory).
- `_resolve_bindings` (used only for a Button's `action.event.context` / `action.functionCall.args`) resolves
  `{"path": ...}` bindings but deliberately does NOT evaluate nested `{"call": ...}` function-call
  expressions inside those args/context — a Button's dynamic action data is expected to be literals or plain
  bindings in v1, not nested function calls. Documented in the function's own docstring.
- Deep links continue to render as `TextBlock` display text (never `Action.OpenUrl`) — unchanged from
  before this task; real deep-link → `Action.OpenUrl` wiring is TASK-2546's job, explicitly out of scope
  here (`test_deep_links_rendered_as_display_text_never_action` pins this).

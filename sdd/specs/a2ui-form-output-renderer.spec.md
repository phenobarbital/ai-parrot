---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: A2UI v1.0 Form Renderer for parrot-formdesigner (full interaction cycle)

**Feature ID**: FEAT-544
**Date**: 2026-09-10
**Author**: Jesus Lara
**Status**: review
**Target version**: parrot-formdesigner 1.1.0 / ai-parrot 1.x
**Proposal**: `sdd/proposals/a2ui-form-output-renderer.proposal.md` (research state `sdd/state/FEAT-544/`)

---

## 1. Motivation & Business Requirements

### Problem Statement

parrot-formdesigner exports a `FormSchema` into HTML5, JSON Schema, Adaptive
Cards, XForms, PDF, audio and Telegram, but it has no A2UI output. ai-parrot's
A2UI v1.0 stack (`parrot.outputs.a2ui`) already carries the wire models, the
vendored Basic Catalog and a `build_form()` composition helper, yet today every
A2UI `action` is routed into an LLM agent turn by `A2UIRuntime` — there is no
form-scoped receiver, so an A2UI client cannot fill a FormDesigner form and
submit it back without an agent in the loop.

This feature adds an `a2ui` render format whose surface can be filled by any
v1.0-compliant renderer and whose submit Button points back at the form's own
answer endpoint, and it teaches that endpoint to speak A2UI in both directions
(validation errors and confirmation). The whole render → validate → submit →
response cycle runs over A2UI envelopes.

### Goals

- `GET /api/v1/{tenant}/forms/{form_uid}/render/a2ui` returns a valid A2UI v1.0
  `createSurface` envelope composed exclusively of Basic Catalog primitives,
  with ai-parrot semantics carried in `metadata.extensions.parrot_*`.
- The surface's submit `Button.action.event` targets the form's own
  `POST /api/v1/{tenant}/forms/{form_uid}/data`; the surface is created with
  `sendDataModel: true` so the renderer attaches all answers on submit.
- `POST .../data` and `POST .../validate` are **dual-wire**: they accept the
  existing field_id-keyed JSON body *and* a v1.0 renderer→agent `action`
  envelope (decision U1), and answer A2UI callers with A2UI envelopes —
  per-field `error` on 422, `updateComponents` + `updateDataModel`
  confirmation on 200 (decision U2). Legacy JSON callers see no change.
- Hybrid field coverage (decision U3): every `FieldType` a Basic primitive can
  express is rendered natively; everything else degrades honestly to a
  `Text` notice and a `RenderedForm.warnings` entry — never raises.
- The renderer validates its own output with
  `validate_envelope(origin=ProducerOrigin.TOOL)` and the produced envelope
  passes `validate_message()` (official jsonschema).
- parrot-formdesigner stays importable without the `ai-parrot` extra; the
  `a2ui` format simply is not registered when the import fails.

### Non-Goals (explicitly out of scope)

- Registering a `Form` catalog component — forbidden by the A2UI v1.0 dialect
  spec goal G6 (`sdd/specs/a2ui-v1-dialect.spec.md`); forms are compositions.
- Routing form submissions through `A2UIRuntime` / an LLM agent turn — the form
  endpoint is the sink (proposal U1). A dedicated `POST .../forms/{uid}/a2ui`
  route was rejected in favour of dual-wire `/data`.
- Browser-side dispatch in `ai-parrot-visualizations` renderers
  (`interactive_html`/`ssr_html` keep `supports_actions=False`).
- Binary uploads (`FILE`, `IMAGE`, `IMAGE_DROPZONE`, `MULTI_UPLOAD`,
  `SIGNATURE`, `SIGNATURE_PAD`, `AUDIO`, `AI_CAPTURE`) through the A2UI data
  model — degraded with a notice in v1.
- Partial saves (`/partial`), `depends_on` conditional visibility and the
  lifecycle-event bridge (`/events/{name}`) — explicit v1 non-goals (U4).
- New Parrot-catalog form components (FileUpload, Signature, Rating, …) —
  follow-up feature (U3 hybrid decision defers them).
- Changing `AbstractFormRenderer` or the other renderers.

---

## 2. Architectural Design

### Overview

Two halves, one package boundary:

1. **Renderer half (parrot-formdesigner).** `A2UIFormRenderer` extends
   `AbstractFormRenderer` and lowers a `FormSchema` into a single
   `CreateSurface`:
   - `surfaceId = f"form-{form.form_uid}"`, `catalogId = DEFAULT_CATALOG_ID`
     (`https://parrot.dev/catalogs/v1` — Basic names resolve inside a Parrot
     surface without per-component `catalogId`), `sendDataModel = True`.
   - Root `Column` (id `root`) → optional title/description `Text`s → one
     `Card` per section (title `Text`, then a `Column` per subsection or the
     section's fields) → a `Text` with `parrot_role: "status"` (empty; the
     confirmation target) → a `Row` holding the submit `Button` (and a cancel
     `Button` when `form.cancel_allowed`).
   - Each field lowers to one Basic input bound at the JSON-Pointer
     `/answers/<escaped field_id>` in `dataModel`; `FieldConstraints` lower to
     `checks` using the Basic functions `required`, `regex`, `length`,
     `numeric`, `email`.
   - `dataModel = {"answers": {<field_id>: prefilled|default|None}, "errors": {...}}`.
   - The submit `Button.action.event` is
     `{name: "form.submit", context: {form_uid, form_id, tenant, submit_url,
     method: "POST", answers: {"path": "/answers"}}}` where `submit_url` is
     `/api/v1/{tenant}/forms/{form_uid}/data`. Cancel dispatches
     `{name: "form.cancel", context: {form_uid}}`.
   - Form identity travels in `metadata.extensions`: root carries
     `parrot_variant: "form"`, `parrot_form_uid`, `parrot_form_id`,
     `parrot_form_version`, `parrot_tenant`, `parrot_submit_url`; every field
     component carries `parrot_field_id`, `parrot_field_uid`,
     `parrot_field_type`, `parrot_section_id` (and `parrot_subsection_id`);
     degraded notices carry `parrot_role: "notice"` + `parrot_field_type`.
   - Output: `RenderedForm(content=<envelope dict>, content_type="application/a2ui+json",
     metadata={"surface_id", "catalog_id", "field_paths": {field_id: pointer},
     "degraded": [...]}, warnings=[RenderWarning...])`.
   - `parrot.outputs.a2ui` is imported lazily inside the renderer (the
     `ai-parrot` extra is optional for parrot-formdesigner); the render
     dispatcher seeds `"a2ui"` only when that import succeeds.

2. **Receiver half (parrot-formdesigner API).** `FormAPIHandler.submit_data`
   and `FormAPIHandler.validate` gain an A2UI branch, isolated in a new module
   `api/a2ui_wire.py`:
   - **Detection**: `Content-Type: application/a2ui+json`, or a JSON body whose
     top level is `{"version": "v1.0", "action": {...}}`. Anything else is the
     legacy JSON path, byte-for-byte unchanged.
   - **Unwrap**: `deserialize(body)` → `A2UIRendererMessage.action`
     (`ActionMessage`). Answers come from `action.data_model["answers"]` when
     `dataModel` is attached, else from the resolved `action.context["answers"]`.
     Keys are JSON-Pointer-unescaped back to `field_id`. `surfaceId` must equal
     `form-{form_uid}` (else 400 A2UI generic `error`). The unwrapped dict
     then flows through the **unchanged** validate → lifecycle → persist →
     forward pipeline.
   - **Reply (A2UI callers only)**:
     - 422 → one `error` envelope per failing field:
       `ErrorMessage(code="VALIDATION_FAILED", surfaceId, path="/answers/<field_id>",
       message)`; unknown-field rejections (`__unknown__`) use
       `path="/answers"`; plus one `updateDataModel{path: "/errors", value: {...}}`.
     - 200 → `updateDataModel{path: "/submission", value: {submission_id,
       is_valid, forwarded, forward_status}}` and `updateComponents` replacing
       the `root-status` `Text` with the confirmation message
       (`parrot_role: "status"`, `parrot_state: "submitted"`).
     - Envelope framing mirrors `A2UIHandler`: a single envelope is returned as
       the body with `Content-Type: application/a2ui+json`; several are
       wrapped as `{"messages": [...]}` (`application/json`).
   - `validate` (dry run) returns the same 422 shape, or `{"messages": []}`
     with 200 when valid.

### Component Diagram

```
GET /api/v1/{t}/forms/{uid}/render/a2ui
   api/render.py::handle_render ──► get_renderer("a2ui") ──► A2UIFormRenderer.render(form, locale=…)
                                                                 │  lazy: from parrot.outputs.a2ui.models import …
                                                                 ├─ _lower_layout()   (Column/Card/Text/Row)
                                                                 ├─ _lower_field()    (FieldType → TextField/CheckBox/ChoicePicker/Slider/DateTimeInput | Text notice)
                                                                 ├─ _lower_checks()   (FieldConstraints → CheckRule[required|regex|length|numeric|email])
                                                                 ├─ _submit_button()  (Button.action.event "form.submit" + context.submit_url)
                                                                 └─ validate_envelope(origin=TOOL) → RenderedForm(content=serialize(CreateSurface), a2ui+json)

client fills inputs → presses Button → action{name:"form.submit", surfaceId:"form-<uid>", context, dataModel}

POST /api/v1/{t}/forms/{uid}/data
   FormAPIHandler.submit_data
      ├─ api/a2ui_wire.py::is_a2ui_request(request, body) ── no ──► legacy JSON path (unchanged)
      └─ yes ► unwrap_action(form, body) → answers{field_id: value}
                 └─ (existing) validate → lifecycle → persist → forward
                        ├─ 422 → a2ui_wire.validation_errors(surface_id, errors)  → [error…, updateDataModel]
                        └─ 200 → a2ui_wire.confirmation(surface_id, result)        → [updateDataModel, updateComponents]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractFormRenderer` (`renderers/base.py`) | extends | `A2UIFormRenderer.render()` keeps the exact keyword-only signature |
| `FallbackRenderer` / `RenderWarning` | uses | degraded fields emit a `Text` notice and a `RenderWarning(renderer="a2ui")` |
| `api/render.py::_seed_default_renderers` | modifies | `setdefault("a2ui", A2UIFormRenderer())` inside a guarded import |
| `renderers/__init__.py::_LAZY_EXPORTS` | modifies | `"A2UIFormRenderer": ".a2ui"` (optional dependency) |
| `FormAPIHandler.submit_data` / `.validate` (`api/handlers.py`) | modifies | A2UI detection + unwrap before the body is treated as answers; A2UI reply shaping after the existing result |
| `parrot.outputs.a2ui.models` | uses | `Component`, `CreateSurface`, `Action`, `EventAction`, `CheckRule`, `FunctionCall`, `DataBinding`, `ComponentMetadata`, `Extensions`, `ActionMessage`, `ErrorMessage`, `UpdateComponents`, `UpdateDataModel` |
| `parrot.outputs.a2ui.serialization` | uses | `serialize()` for every outbound envelope, `deserialize()` for the inbound action |
| `parrot.outputs.a2ui.catalog` | uses | `validate_envelope(origin=TOOL, surface_catalog_id=DEFAULT_CATALOG_ID)`; tests also run `validate_message()` |
| `parrot.outputs.a2ui.catalog.parrot.form.build_form` | pattern reference | lowering pattern; **not** called (its `FormField` model is too narrow — 6 kinds) |
| `parrot.a2a.models.A2UI_MEDIA_TYPE` | uses | `"application/a2ui+json"` for `RenderedForm.content_type` and replies |
| `A2UIHandler` (`ai-parrot-server/handlers/a2ui.py`) | pattern reference | envelope framing (single vs `{"messages": [...]}`); not imported |
| `A2UIRuntime` | untouched | agent-turn routing is not involved |

### Data Models

```python
# parrot_formdesigner/renderers/a2ui.py  (renderer-private; not wire models)

class A2UIFieldLowering(BaseModel):
    """How one FieldType lowers to a Basic primitive."""
    primitive: Literal["TextField", "CheckBox", "ChoicePicker", "Slider", "DateTimeInput", "notice", "hidden"]
    props: dict[str, Any] = Field(default_factory=dict)   # e.g. {"variant": "longText"}, {"enableDate": True}
    check_functions: tuple[str, ...] = ()                  # extra functions always attached, e.g. ("email",)

# Module-level table — the single source of truth for coverage (mirrors adaptive_card.py:71-119)
FIELD_LOWERING: dict[FieldType, A2UIFieldLowering]

# parrot_formdesigner/api/a2ui_wire.py

class A2UIActionSubmission(BaseModel):
    """Answers unwrapped from an inbound A2UI `action` envelope."""
    surface_id: str
    action_name: str                       # "form.submit" | "form.validate"
    source_component_id: str
    answers: dict[str, Any]                # field_id-keyed (pointer tokens unescaped)
    raw_context: dict[str, Any]
```

Wire shapes (all produced through `parrot.outputs.a2ui` models + `serialize`,
never hand-written):

```jsonc
// GET .../render/a2ui  → RenderedForm.content
{"version": "v1.0", "createSurface": {
  "surfaceId": "form-<uid>", "catalogId": "https://parrot.dev/catalogs/v1", "sendDataModel": true,
  "components": [
    {"id": "root", "component": "Column", "children": ["root-title", "sec-<section_id>", "root-status", "root-actions"],
     "metadata": {"extensions": {"parrot_variant": "form", "parrot_form_uid": "…", "parrot_form_id": "…",
                                 "parrot_tenant": "…", "parrot_submit_url": "/api/v1/<t>/forms/<uid>/data"}}},
    {"id": "f-<field_id>", "component": "TextField", "label": "…", "value": {"path": "/answers/<field_id>"},
     "variant": "shortText", "checks": [{"condition": {"call": "required", "args": {"value": {"path": "/answers/<field_id>"}}},
                                         "message": "… is required."}],
     "metadata": {"extensions": {"parrot_field_id": "…", "parrot_field_uid": "…", "parrot_field_type": "text", "parrot_section_id": "…"}}},
    {"id": "root-status", "component": "Text", "text": "", "metadata": {"extensions": {"parrot_role": "status"}}},
    {"id": "root-submit", "component": "Button", "variant": "primary", "child": "root-submit-label",
     "action": {"event": {"name": "form.submit",
                          "context": {"form_uid": "…", "form_id": "…", "tenant": "…",
                                      "submit_url": "/api/v1/<t>/forms/<uid>/data", "method": "POST",
                                      "answers": {"path": "/answers"}}}}}
  ],
  "dataModel": {"answers": {"<field_id>": null}, "errors": {}}
}}

// POST .../data (A2UI wire) — inbound
{"version": "v1.0", "action": {"name": "form.submit", "surfaceId": "form-<uid>", "sourceComponentId": "root-submit",
  "timestamp": "…", "context": {"…": "…", "answers": {"<field_id>": "…"}}, "dataModel": {"answers": {"…": "…"}}}}

// 422 — one per invalid field, then the data-model update
{"version": "v1.0", "error": {"code": "VALIDATION_FAILED", "surfaceId": "form-<uid>", "path": "/answers/<field_id>", "message": "…"}}
{"version": "v1.0", "updateDataModel": {"surfaceId": "form-<uid>", "path": "/errors", "value": {"<field_id>": ["…"]}}}

// 200
{"version": "v1.0", "updateDataModel": {"surfaceId": "form-<uid>", "path": "/submission",
   "value": {"submission_id": "…", "is_valid": true, "forwarded": false, "forward_status": null}}}
{"version": "v1.0", "updateComponents": {"surfaceId": "form-<uid>", "components": [
   {"id": "root-status", "component": "Text", "text": "Form submitted.", "metadata": {"extensions": {"parrot_role": "status", "parrot_state": "submitted"}}}]}}
```

### New Public Interfaces

```python
# parrot_formdesigner/renderers/a2ui.py
class A2UIFormRenderer(AbstractFormRenderer):
    """Lower a FormSchema into an A2UI v1.0 createSurface envelope."""

    RENDERER_NAME: ClassVar[str] = "a2ui"

    def __init__(self, *, submit_url_template: str = "/api/v1/{tenant}/forms/{form_uid}/data",
                 catalog_id: str | None = None) -> None: ...

    async def render(self, form: FormSchema, style: StyleSchema | None = None, *,
                     locale: str = "en", prefilled: dict[str, Any] | None = None,
                     errors: dict[str, str] | None = None) -> RenderedForm: ...

def field_pointer(field_id: str) -> str:
    """'/answers/' + RFC 6901-escaped field_id ('~' → '~0', '/' → '~1')."""

def field_id_from_pointer_token(token: str) -> str:
    """Inverse of field_pointer's token escaping."""

# parrot_formdesigner/api/a2ui_wire.py
A2UI_SUBMIT_ACTION = "form.submit"
A2UI_VALIDATE_ACTION = "form.validate"
A2UI_CANCEL_ACTION = "form.cancel"

def is_a2ui_request(request: web.Request, body: Any) -> bool: ...
def unwrap_action(form: FormSchema, body: dict[str, Any]) -> A2UIActionSubmission: ...   # raises A2UIWireError(status, envelope)
def validation_errors(surface_id: str, errors: dict[str, list[str]]) -> list[dict[str, Any]]: ...
def confirmation(surface_id: str, result: dict[str, Any], *, message: str = "Form submitted.") -> list[dict[str, Any]]: ...
def a2ui_response(envelopes: list[dict[str, Any]], *, status: int) -> web.Response: ...  # single → a2ui+json body; many → {"messages": [...]}
```

---

## 3. Module Breakdown

### Module 1: Renderer skeleton, layout and submit action
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py`
- **Responsibility**: `A2UIFormRenderer` class, lazy `parrot.outputs.a2ui` import, surface/root/section/subsection layout lowering, `root-status` placeholder, submit/cancel Buttons with `action.event` + `context.submit_url`, `metadata.extensions.parrot_*` on root and fields, `dataModel` construction from `prefilled`/`default`, `field_pointer()`/`field_id_from_pointer_token()`, final `validate_envelope(origin=TOOL)` and `RenderedForm` assembly (`content_type=A2UI_MEDIA_TYPE`, `metadata.field_paths`).
- **Depends on**: existing `AbstractFormRenderer`, `parrot.outputs.a2ui.models`, `serialization`, `catalog`.

### Module 2: FieldType and constraint lowering table
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py` (same file, `FIELD_LOWERING` + `_lower_field` + `_lower_checks` + `_degrade`)
- **Responsibility**: the full 47-entry `FieldType → A2UIFieldLowering` table (see §7 mapping), `FieldConstraints → checks` (required/regex/length/numeric/email), `FieldOption`/`options_source`-less options → `ChoiceOption`, `MULTI_SELECT`/`TAGS` → `ChoicePicker(variant="multipleSelection")`, `NPS`/`LIKERT`/`RANKING` → `Slider(min/max/steps from scale_*)`, `HIDDEN` → dataModel-only, degraded types → `Text` notice + `RenderWarning`; per-field `errors` → `Text(parrot_role="error")` sibling + `/errors/<field_id>`.
- **Depends on**: Module 1.

### Module 3: Registration and packaging
- **Paths**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py`, `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/__init__.py`, `packages/parrot-formdesigner/pyproject.toml`
- **Responsibility**: `_seed_default_renderers` registers `"a2ui"` inside `try/except ImportError` (log once at INFO when skipped); `_LAZY_EXPORTS["A2UIFormRenderer"] = ".a2ui"` + `__all__`; add `a2ui = ["ai-parrot>=1.0.0"]` optional extra alias next to the existing `ai-parrot` extra; `supported_formats()` lists `a2ui` when available.
- **Depends on**: Module 1.

### Module 4: A2UI wire helpers for the receiver
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py` (new)
- **Responsibility**: `is_a2ui_request`, `unwrap_action` (deserialize → `ActionMessage`; surfaceId check; answers from `dataModel["answers"]` else `context["answers"]`; pointer-token unescape; `A2UIWireError` carrying a ready generic `error` envelope), `validation_errors`, `confirmation`, `a2ui_response`. Lazy import of `parrot.outputs.a2ui`; if unavailable, `is_a2ui_request` returns `False` so the legacy path is untouched.
- **Depends on**: Module 1 (shares pointer helpers).

### Module 5: Dual-wire `submit_data` and `validate`
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
- **Responsibility**: after `body = await request.json()` in `submit_data` (≈ line 1520) and in `validate` (≈ line 1003), branch on `is_a2ui_request`; on A2UI, replace `body` with `submission.answers` and set a local `a2ui_surface_id`; wrap the three existing outcomes (422 field errors incl. `__unknown__`, 422 extras cap, 200 composite) with `validation_errors`/`confirmation` + `a2ui_response` when `a2ui_surface_id` is set. Legacy behaviour and status codes are unchanged; lifecycle hooks, persistence, forwarding and `merge_partials` run exactly as before.
- **Depends on**: Module 4.

### Module 6: Tests
- **Paths**: `packages/parrot-formdesigner/tests/unit/renderers/test_a2ui_renderer.py`, `packages/parrot-formdesigner/tests/unit/api/test_a2ui_wire.py`, `packages/parrot-formdesigner/tests/unit/api/test_submit_a2ui.py`, `packages/parrot-formdesigner/tests/integration/test_a2ui_form_cycle.py`, plus one conformance test in `packages/ai-parrot/tests/outputs/a2ui/catalog/test_formdesigner_surface.py` (skipped when parrot-formdesigner is not installed)
- **Responsibility**: see §4.
- **Depends on**: Modules 1–5.

### Module 7: Documentation
- **Paths**: `docs/outputs/a2ui-v1.md` (new section "Forms from FormDesigner"), `packages/parrot-formdesigner/docs/a2ui-renderer.md` (new), `packages/parrot-formdesigner/CHANGELOG.md`
- **Responsibility**: document the cycle, the `parrot_form_*`/`parrot_field_*` extension keys, the dual-wire contract and the coverage table.
- **Depends on**: Modules 1–5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_render_returns_createsurface_with_a2ui_media_type` | 1 | `content_type == "application/a2ui+json"`, `content["version"] == "v1.0"`, `createSurface.surfaceId == f"form-{uid}"`, `sendDataModel is True` |
| `test_root_is_column_with_one_root_and_status_placeholder` | 1 | exactly one component id `root`; `root-status` Text present with `parrot_role == "status"` |
| `test_sections_and_subsections_become_cards_and_columns` | 1 | section order preserved; titles resolved by `locale` |
| `test_submit_button_action_targets_form_data_endpoint` | 1 | `action.event.name == "form.submit"`, `context.submit_url == "/api/v1/{tenant}/forms/{uid}/data"`, `context.answers == {"path": "/answers"}` |
| `test_cancel_button_only_when_cancel_allowed` | 1 | `form.cancel_allowed=False` → no `form.cancel` Button |
| `test_root_and_field_extensions_carry_identity` | 1 | `parrot_variant/parrot_form_uid/parrot_submit_url` on root; `parrot_field_id/parrot_field_uid/parrot_field_type/parrot_section_id` on every input |
| `test_datamodel_seeds_prefilled_then_default_then_null` | 1 | precedence prefilled > default > None per field |
| `test_field_pointer_escapes_rfc6901_and_roundtrips` | 1 | `a/b` → `/answers/a~1b`; `~` → `~0`; inverse restores field_id |
| `test_envelope_passes_validate_envelope_tool_origin` | 1 | `validate_envelope(CreateSurface, origin=TOOL, surface_catalog_id=DEFAULT_CATALOG_ID)` does not raise; LLM origin raises (action present) |
| `test_every_fieldtype_has_a_lowering_entry` | 2 | `set(FIELD_LOWERING) == set(FieldType)` — coverage is total by construction |
| `test_text_family_maps_to_textfield_variants` | 2 | TEXT→shortText, TEXT_AREA→longText, NUMBER/INTEGER→number, PASSWORD→obscured; EMAIL adds `email` check, URL/PHONE add `regex` |
| `test_boolean_maps_to_checkbox` | 2 | `CheckBox.value` bound to pointer |
| `test_select_and_multiselect_map_to_choicepicker` | 2 | SELECT → `mutuallyExclusive`; MULTI_SELECT/TAGS → `multipleSelection`; options from `FieldOption` with locale-resolved labels |
| `test_date_time_datetime_map_to_datetimeinput_flags` | 2 | DATE→enableDate; TIME→enableTime; DATETIME→both |
| `test_scale_types_map_to_slider` | 2 | NPS/LIKERT/RANKING → `Slider(min=scale_min, max=scale_max, steps)` |
| `test_hidden_is_datamodel_only` | 2 | no component emitted; `dataModel.answers[field_id]` present; `field_paths` includes it |
| `test_constraints_lower_to_checks` | 2 | required→`required`; pattern→`regex`; min/max_length→`length`; min/max_value→`numeric`; `pattern_message` used as `message` |
| `test_unsupported_types_degrade_to_notice_and_warning` | 2 | FILE/GROUP/ARRAY/SIGNATURE… → `Text(parrot_role="notice")` + `RenderWarning(renderer="a2ui")`; never raises |
| `test_errors_param_emits_error_text_and_datamodel_errors` | 2 | `errors={"f": "bad"}` → sibling Text `parrot_role="error"` + `dataModel.errors.f` |
| `test_seed_registers_a2ui_when_ai_parrot_available` | 3 | `"a2ui" in _RENDERERS` after `_seed_default_renderers()` |
| `test_seed_skips_a2ui_when_import_fails` | 3 | monkeypatch import failure → registry has the other five, no exception, one INFO log |
| `test_lazy_export_from_renderers_package` | 3 | `from parrot_formdesigner.renderers import A2UIFormRenderer` works; listed in `__all__` |
| `test_is_a2ui_request_by_media_type_and_body_shape` | 4 | true for `application/a2ui+json` or `{"version","action"}` body; false for legacy dict |
| `test_unwrap_prefers_datamodel_over_context` | 4 | answers from `dataModel.answers` when present, else `context.answers`; tokens unescaped |
| `test_unwrap_rejects_surface_mismatch_and_wrong_action` | 4 | `surfaceId != form-{uid}` or `name` not in {submit, validate} → `A2UIWireError` with generic `error` envelope, status 400 |
| `test_validation_errors_shape` | 4 | one `error{VALIDATION_FAILED, surfaceId, path=/answers/<f>}` per field + `updateDataModel(/errors)`; each passes `validate_message()` |
| `test_confirmation_shape` | 4 | `updateDataModel(/submission)` + `updateComponents([root-status])`; passes `validate_message()` |
| `test_a2ui_response_framing` | 4 | 1 envelope → `application/a2ui+json` body; N → `{"messages": [...]}` |
| `test_submit_legacy_json_unchanged` | 5 | existing `test_submit_unknown_fields.py`-style fixtures still get identical JSON |
| `test_submit_a2ui_422_returns_error_envelopes` | 5 | invalid action → 422, per-field errors, nothing persisted |
| `test_submit_a2ui_200_returns_confirmation` | 5 | valid action → 200, `updateDataModel.value.submission_id` matches store, lifecycle hooks dispatched once |
| `test_validate_a2ui_dry_run` | 5 | `/validate` with action → 422 errors or 200 `{"messages": []}` |
| `test_submit_a2ui_unknown_fields_reject_policy` | 5 | `__unknown__` → `error.path == "/answers"` |

### Integration Tests

| Test | Description |
|---|---|
| `test_a2ui_form_cycle_end_to_end` | aiohttp client: `GET render/a2ui` → build an `action` from the surface (`context.submit_url`, `answers` bound paths) with a missing required field → `POST` to `submit_url` → 422 error envelopes → fix → 200 confirmation; form stored via `submission_storage` |
| `test_a2ui_surface_validates_against_official_schema` | (ai-parrot tests) render a representative FormSchema, run `validate_envelope` + `validate_message` and the SSR-HTML renderer over it — renders without raising, degraded list empty for Basic-only forms |
| `test_public_and_private_form_membership_on_a2ui_submit` | private form + A2UI action without membership → 403 (same as legacy) |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_form() -> FormSchema:
    # reuse packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py::sample_form shape
    # (2 sections; TEXT required, EMAIL, SELECT with 3 options, BOOLEAN, DATE, NPS, FILE degraded)

@pytest.fixture
def a2ui_action(sample_form) -> dict:
    """A v1.0 renderer→agent envelope built from the rendered surface's field_paths."""
    return {"version": "v1.0", "action": {"name": "form.submit", "surfaceId": f"form-{sample_form.form_uid}",
            "sourceComponentId": "root-submit", "timestamp": "2026-09-10T00:00:00Z",
            "context": {"form_uid": str(sample_form.form_uid)}, "dataModel": {"answers": {...}}}}
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `GET /api/v1/{tenant}/forms/{form_uid}/render/a2ui` returns HTTP 200 with `Content-Type: application/a2ui+json` and a body that `deserialize()`s to an `A2UIAgentMessage` whose `create_surface.surface_id == f"form-{form_uid}"` and `send_data_model is True`.
- [ ] The envelope passes `validate_envelope(origin=ProducerOrigin.TOOL, surface_catalog_id=DEFAULT_CATALOG_ID)` and `validate_message()`; it contains exactly one root (`id == "root"`) and **no** component named `Form`.
- [ ] Every input component's `value` (or `checks`) binds to `/answers/<rfc6901-escaped field_id>`; `RenderedForm.metadata["field_paths"]` maps every non-degraded `field_id` to its pointer.
- [ ] The submit `Button.action.event` has `name == "form.submit"` and `context.submit_url == f"/api/v1/{tenant}/forms/{form_uid}/data"`; a cancel Button exists iff `form.cancel_allowed`.
- [ ] Root carries `metadata.extensions.parrot_variant == "form"` plus `parrot_form_uid`, `parrot_form_id`, `parrot_tenant`, `parrot_submit_url`; every input carries `parrot_field_id`, `parrot_field_uid`, `parrot_field_type`, `parrot_section_id`. No `parrot_*` key appears as a top-level component prop.
- [ ] `FIELD_LOWERING` covers all 47 `FieldType` members (test asserts set equality); natively mapped: TEXT, TEXT_AREA, NUMBER, INTEGER, BOOLEAN, DATE, DATETIME, TIME, SELECT, MULTI_SELECT, EMAIL, URL, PHONE, PASSWORD, COLOR, COLOR_PICKER, MASKED, SEARCH, TAGS, NPS, LIKERT, RANKING, HIDDEN (dataModel-only); every other type degrades to a `Text` notice with `parrot_role == "notice"` and one `RenderWarning(renderer="a2ui")` — rendering never raises for any FieldType.
- [ ] `FieldConstraints` lower to `checks`: `required`, `pattern`→`regex`, `min_length`/`max_length`→`length`, `min_value`/`max_value`→`numeric`; EMAIL always adds `email`.
- [ ] `POST .../data` with a legacy JSON body produces byte-identical responses to `dev` HEAD for the existing unit suites (`tests/unit/api/test_submit_unknown_fields.py`, `tests/unit/test_submit_path_branch.py`, `tests/integration/test_unknown_fields_e2e.py` pass unchanged).
- [ ] `POST .../data` with an A2UI `action` envelope (media type or body shape) runs the same validate → lifecycle → persist → forward pipeline and returns: 422 → one `error{code: "VALIDATION_FAILED", surfaceId, path: "/answers/<field_id>"}` per invalid field plus `updateDataModel{path: "/errors"}`; 200 → `updateDataModel{path: "/submission"}` plus `updateComponents` replacing `root-status`. Every reply envelope passes `validate_message()`.
- [ ] A `surfaceId` mismatch or an unknown action name returns HTTP 400 with a generic A2UI `error` envelope; nothing is persisted.
- [ ] `POST .../validate` accepts the same A2UI wire and returns the 422 error shape or 200 `{"messages": []}`.
- [ ] `import parrot_formdesigner.api` succeeds when `ai-parrot` is not installed: `"a2ui"` is simply absent from `supported_formats()` and one INFO line is logged.
- [ ] Tenant/public membership rules on `/data`, `/validate` and `/render/{format}` are unchanged (`enforce_membership_unless_public` still runs before any A2UI unwrap).
- [ ] `A2UIRuntime`, `A2UIHandler`, `build_form()` and all ai-parrot-visualizations renderers are untouched (no diff under those paths).
- [ ] Documentation added: `docs/outputs/a2ui-v1.md` section, `packages/parrot-formdesigner/docs/a2ui-renderer.md`, CHANGELOG entry.
- [ ] All new unit tests pass (`pytest packages/parrot-formdesigner/tests/unit -v`) and integration tests pass (`pytest packages/parrot-formdesigner/tests/integration/test_a2ui_form_cycle.py -v`).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against `dev` at commit `107f37de2` (2026-09-10). Implementation
> agents MUST NOT reference imports, attributes, or methods not listed here
> without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
# parrot-formdesigner (package root: packages/parrot-formdesigner/src/parrot_formdesigner/)
from parrot_formdesigner.renderers.base import AbstractFormRenderer, FallbackRenderer, FieldRenderer   # base.py:57 / :34 / :14
from parrot_formdesigner.core.schema import (                                                            # schema.py
    FormField,        # :65
    FormSubsection,   # :195
    FormSection,      # :229
    SubmitAction,     # :300
    FormSchema,       # :401
    RenderWarning,    # :650
    RenderedForm,     # :671
)
from parrot_formdesigner.core.types import FieldType, LocalizedString   # types.py:16 (47 members, :19-70) / :13 (`str | dict[str, str]`)
from parrot_formdesigner.core.constraints import FieldConstraints        # constraints.py:21
from parrot_formdesigner.core.options import FieldOption, OptionsSource  # options.py:14 / :32
from parrot_formdesigner.core.style import StyleSchema                   # style.py:52 (submit_label :71, cancel_label)
from parrot_formdesigner.core.resolution import find_field_by_uid        # resolution.py:170
from parrot_formdesigner.api.render import (                              # render.py
    _RENDERERS,               # :35  dict[str, AbstractFormRenderer]
    _seed_default_renderers,  # :38
    register_renderer,        # :63
    get_renderer,             # :76
    supported_formats,        # :81
    handle_render,            # :101
)
from parrot_formdesigner.api.handlers import FormAPIHandler, extract_form_uid   # handlers.py:109 / :38
from parrot_formdesigner.api.tenant import declared_tenant, enforce_membership_unless_public   # tenant.py:166 / :189
from parrot_formdesigner.api._utils import _loc_to_str                  # _utils.py:37  (LocalizedString → str | None; NOT locale-aware)
from parrot_formdesigner.services.validators import FormValidator, ValidationResult   # validators.py:199 / :159
from navigator.responses import JSONResponse                            # used by handlers.py:19

# ai-parrot core (packages/ai-parrot/src/parrot/)
from parrot.outputs.a2ui.models import (                                # models.py
    is_valid_pointer,        # :112
    DataBinding,             # :155  (.path validated as JSON Pointer)
    FunctionCall,            # :174  (call, args, catalogId)
    EventAction,             # :232  (name, userMessage?, context: dict)
    Action,                  # :250  (exactly one of event / functionCall)
    CheckRule,               # :272  (condition: FunctionCall | DataBinding, message: str | None)
    Extensions,              # :341  RootModel[dict[str, Any]]
    ComponentMetadata,       # :364  (extensions: Extensions | None)
    Component,               # :400  extra="allow"; id, component, catalogId, weight, accessibility, checks, action, metadata
    CreateSurface,           # :446  (surfaceId, catalogId?, sendDataModel=False, components, dataModel={})
    UpdateComponents,        # :473  (surfaceId, components)
    UpdateDataModel,         # :490  (surfaceId, path: str | None, value: Any)
    ActionMessage,           # :585  (name, userMessage?, surfaceId, sourceComponentId, timestamp, context, metadata?, dataModel?)
    ErrorMessage,            # :648  (code, message, surfaceId?, path?, functionCallId?) — code in {"VALIDATION_FAILED","UNALLOWED_PARENT","UNALLOWED_CHILD"} REQUIRES surfaceId+path (:644)
    A2UIAgentMessage,        # :695
    A2UIRendererMessage,     # :740  (.action: ActionMessage | None :755)
)
from parrot.outputs.a2ui.serialization import serialize, deserialize, iter_jsonl   # serialization.py:104 / :155 / :215
from parrot.outputs.a2ui.catalog import validate_envelope, validate_message, register_component   # catalog/__init__.py:499 / :455 / :111
from parrot.outputs.a2ui.catalog.base import ProducerOrigin, DEFAULT_CATALOG_ID   # base.py:89 / :53 ("https://parrot.dev/catalogs/v1")
from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID                    # basic/__init__.py:44
from parrot.outputs.a2ui.catalog.basic.inputs import (                             # basic/inputs.py
    Button, TextField, CheckBox, ChoiceOption, ChoicePicker, Slider, DateTimeInput,
)
from parrot.outputs.a2ui.catalog.parrot.form import build_form, FormSubmit        # catalog/parrot/form.py:119 / :55 (pattern reference only)
from parrot.outputs.a2ui.runtime.models import A2UIErrorCode, error_envelope      # runtime/models.py:45 / :172
from parrot.a2a.models import A2UI_MEDIA_TYPE                                     # a2a/models.py:336 == "application/a2ui+json"
```

### Existing Class Signatures
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py
class AbstractFormRenderer(ABC):                                            # line 57
    @abstractmethod
    async def render(self, form: FormSchema, style: StyleSchema | None = None, *,
                     locale: str = "en", prefilled: dict[str, Any] | None = None,
                     errors: dict[str, str] | None = None) -> RenderedForm: ...   # lines 67-76

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormField(BaseModel):                                                 # line 65
    field_uid: uuid.UUID; field_id: str; field_type: FieldType; label: LocalizedString   # 123-126
    description: LocalizedString | None; placeholder: LocalizedString | None            # 127-128
    required: bool = False; default: Any = None; read_only: bool = False                # 129-131
    constraints: FieldConstraints | None; options: list[FieldOption] | None            # 132-133
    options_source: OptionsSource | None; depends_on: DependencyRule | None            # 134-135
    children: list[FormField] | None; item_template: FormField | None                  # 137-138
class FormSubsection(BaseModel): subsection_uid, subsection_id: str, title, description, fields: list[FormField], depends_on, meta   # 195, 217-223
class FormSection(BaseModel):    section_uid, section_id, title, description, fields, subsections?, depends_on, meta                  # 229, 250-256
    def iter_fields(self) -> Iterator[FormField]                                        # 258
class SubmitAction(BaseModel):                                              # line 300
    action_type: Literal["tool_call", "endpoint", "event", "callback"]; action_ref: str; method: str = "POST"
    confirm_message: LocalizedString | None; auth: AuthConfig | None                     # 310-314
class FormSchema(BaseModel):                                                # line 401
    form_uid: uuid.UUID; form_id: str; version: str = "1.0"; title: LocalizedString; description  # 453-457
    sections: list[FormSection]; submit: SubmitAction | None; cancel_allowed: bool = True         # 458-460
    tenant: str | None; is_public: bool = False; unknown_fields: UnknownFieldsPolicy               # 463, 471, 475
    def iter_all_fields(self) -> Iterator[FormField]      # 477 — layout order, sections+subsections, does NOT recurse GROUP/ARRAY
    def iter_fields_recursive(self) -> Iterator[FormField] # 490
class RenderWarning(BaseModel): field_id: str; field_uid: uuid.UUID | None; field_type: str; renderer: str; reason: str   # 650
class RenderedForm(BaseModel):  content: Any; content_type: str; style_output: Any | None; metadata: dict | None; warnings: list[RenderWarning] = []   # 671-688

# packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py
class FieldConstraints(BaseModel):                                          # line 21
    min_length, max_length: int | None (44-45); min_value, max_value, step: float | None (46-48)
    pattern: str | None; pattern_message: LocalizedString | None (49-50); min_items, max_items (51-52)
    allowed_mime_types, max_file_size_bytes, max_inline_size_bytes (53-55)
    scale_min: int | None; scale_max: int | None; scale_step: int | None; anchor_labels: dict[int, LocalizedString] | None (65-68)

# packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py
class FieldOption(BaseModel): value: str; label: LocalizedString; description; disabled: bool = False; icon: str | None   # 14

# packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py
_RENDERERS: dict[str, AbstractFormRenderer] = {}                            # 35
def _seed_default_renderers() -> None   # 38 — setdefault html/adaptive/xml/pdf/audio (56-60)
def register_renderer(format_key: str, renderer: AbstractFormRenderer) -> None   # 63
async def handle_render(request: web.Request) -> web.Response   # 101 — passes ONLY locale: `renderer.render(form, locale=locale)` (146); json.dumps for dict content (98)

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
class FormAPIHandler:                                                       # 109
    def _get_tenant(self, request) -> str                                   # 269
    def _assert_form_tenant(self, form, tenant) -> None                     # 322
    def _build_auth_context(self, request) -> AuthContext                   # 355
    def _extract_visit_context(self, form, body) -> tuple[dict, dict | None]   # 400
    async def validate(self, request) -> web.Response                       # 1003 — returns {"is_valid", "errors"} 200/422
    async def submit_data(self, request) -> web.Response                    # 1464 — body = await request.json() (~1520); 422 {"is_valid": False, "errors": {...}} (1610-1615, __unknown__ 1638-1640); 200 {"submission_id", "is_valid": True, "forwarded", "forward_status", "forward_error"} (1842-1850)

# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
class ValidationResult(BaseModel): is_valid: bool; errors: dict[str, list[str]]; sanitized_data: dict; extra_data: dict   # 159, 173-176
class FormValidator:                                                        # 199
    async def validate(self, form: FormSchema, data: dict[str, Any], *, locale: str = "en",
                       auth_context=None, location_vars=None, visit_context=None) -> ValidationResult   # 220-229

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py  (pattern reference)
def _resolve(value: LocalizedString | None, locale: str = "en") -> str      # 45 — module-private; COPY the pattern, do not import
class AdaptiveCardRenderer(AbstractFormRenderer)                            # 121; FieldType→element table 71-119; warnings loop 252-260

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/inputs.py  (exact props)
class TextField(Component):     label: DynamicString; value: DynamicString | None; placeholder; variant: Literal["longText","number","shortText","obscured"] = "shortText"
class CheckBox(Component):      label: DynamicString; value: DynamicBoolean
class ChoiceOption(BaseModel):  label: DynamicString; value: str
class ChoicePicker(Component):  label?; variant: Literal["multipleSelection","mutuallyExclusive"] = "mutuallyExclusive"; options: list[ChoiceOption]; value: DynamicStringList; displayStyle: Literal["checkbox","chips"]; filterable: bool
class Slider(Component):        label?; min: float = 0; max: float; value: DynamicNumber; steps: int | None (ge=1)
class DateTimeInput(Component): value: DynamicString; enableDate: bool = False; enableTime: bool = False; min?; max?; label?
class Button(Component):        child: str; variant: Literal["default","primary","borderless"]; action: Action

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin: ProducerOrigin = ProducerOrigin.TOOL,
                      surface_catalog_id: str | None = None) -> None        # 499
def validate_message(message: A2UIAgentMessage | A2UIRendererMessage) -> None   # 455 (jsonschema)

# packages/ai-parrot/src/parrot/outputs/a2ui/runtime/models.py
def error_envelope(code: A2UIErrorCode, message: str, *, function_call_id=None, surface_id=None, path=None) -> dict   # 172
class A2UIErrorCode(str, Enum): INVALID_FUNCTION_CALL, UNALLOWED_PARENT, UNALLOWED_CHILD, FORBIDDEN, NOT_FOUND, INTERNAL, TIMEOUT   # 45-61 — NO VALIDATION_FAILED member

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/form.py  (pattern reference)
def build_form(*, id_prefix: str, title: str | None, fields: list[FormField], submit: FormSubmit) -> list[Component]   # 119
def _lower_field(id_prefix: str, field: FormField) -> Component            # 73 — required → CheckRule(FunctionCall("required", {"value": {"path": …}}))

# packages/ai-parrot-server/src/parrot/handlers/a2ui.py  (pattern reference — framing)
# single envelope → web.json_response(messages[0], status=200, content_type=A2UI_MEDIA_TYPE); many → {"messages": messages}   # 156-240
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `A2UIFormRenderer.render()` | `AbstractFormRenderer.render()` | override, identical signature | `renderers/base.py:67-76` |
| `A2UIFormRenderer` | `handle_render` | `_RENDERERS["a2ui"]` lookup → `renderer.render(form, locale=locale)` | `api/render.py:117,146` |
| `_seed_default_renderers` | `A2UIFormRenderer()` | `_RENDERERS.setdefault("a2ui", …)` in guarded import | `api/render.py:50-60` |
| `renderers/__init__.py` | `A2UIFormRenderer` | `_LAZY_EXPORTS["A2UIFormRenderer"] = ".a2ui"` | `renderers/__init__.py:19-21` |
| `A2UIFormRenderer` | `CreateSurface` / `Component` / `Action` … | construct → `validate_envelope(origin=TOOL)` → `serialize()` | `models.py:446,400,250`; `catalog/__init__.py:499`; `serialization.py:104` |
| `a2ui_wire.unwrap_action` | `deserialize()` → `A2UIRendererMessage.action` | parse inbound body | `serialization.py:155`; `models.py:740,755` |
| `a2ui_wire.validation_errors` | `ErrorMessage(code="VALIDATION_FAILED", surfaceId, path)` + `UpdateDataModel` | `serialize()` each | `models.py:648,644,490` |
| `a2ui_wire.confirmation` | `UpdateDataModel` + `UpdateComponents` | `serialize()` each | `models.py:490,473` |
| `FormAPIHandler.submit_data` | `a2ui_wire.is_a2ui_request/unwrap_action` | branch right after `body = await request.json()` | `handlers.py:≈1520` |
| `FormAPIHandler.submit_data` | `a2ui_wire.validation_errors/confirmation/a2ui_response` | wrap existing 422/200 returns | `handlers.py:1610-1615, 1638-1640, 1842-1850` |
| `FormAPIHandler.validate` | same helpers | wrap `{"is_valid","errors"}` | `handlers.py:1003-1040` |
| `RenderedForm.content_type` | `A2UI_MEDIA_TYPE` | constant | `a2a/models.py:336` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_formdesigner.renderers.a2ui` / `A2UIFormRenderer`~~ — does not exist yet; created by Module 1.
- ~~`parrot_formdesigner.api.a2ui_wire`~~ — does not exist yet; created by Module 4.
- ~~`class FormHandler`~~ in `api/handlers.py` — the handler class is **`FormAPIHandler`** (line 109).
- ~~`Form` catalog component~~ / ~~`parrot.outputs.a2ui.catalog.parrot.form.Form`~~ — retired (spec G6); only `build_form()`, `FormField`, `FormSubmit` exist there.
- ~~`A2UIErrorCode.VALIDATION_FAILED`~~ — not an enum member; build `ErrorMessage(code="VALIDATION_FAILED", …)` directly (the model accepts the string, `models.py:644`). Do **not** pass it to `error_envelope()`.
- ~~`POST /api/v1/{tenant}/forms/{form_uid}/a2ui`~~ — no such route; rejected in favour of dual-wire `/data`.
- ~~`handle_render(prefilled=…, errors=…)`~~ — the dispatcher passes only `locale` (`render.py:146`); `prefilled`/`errors` are renderer-API only in v1.
- ~~`RenderedForm.surface_id`~~ / ~~`RenderedForm.envelope`~~ — no such attributes; use `metadata["surface_id"]` and `content`.
- ~~`ChoicePicker.multiple`~~ / ~~`ChoicePicker.multi_select`~~ — the prop is `variant="multipleSelection"`.
- ~~`TextField.type`~~ / ~~`TextField.input_type`~~ — the prop is `variant` (`longText|number|shortText|obscured`).
- ~~`Component.disabled`~~, ~~`Component.visible`~~, ~~`Component.hidden`~~ — no such v1.0 props; HIDDEN fields are dataModel-only.
- ~~`Slider.step`~~ — the prop is `steps` (int, number of divisions), not a step size.
- ~~`DateTimeInput.mode`~~ — use `enableDate` / `enableTime`.
- ~~Basic functions `minLength`, `maxLength`, `min`, `max`, `url`, `phone`~~ — only `required`, `regex`, `length`, `numeric`, `email`, `and`, `or`, `not`, `formatString`, `formatNumber`, `formatDate`, `formatCurrency`, `@index` exist (`catalog/basic/functions.py`).
- ~~`parrot_formdesigner.renderers.adaptive_card._resolve` as a shared helper~~ — module-private; copy the pattern into `a2ui.py`.
- ~~`_loc_to_str(value, locale)`~~ — `_loc_to_str` takes one argument and is not locale-aware (`_utils.py:37`).
- ~~`A2UIRuntime.register_form_sink()`~~ / any runtime hook — the runtime is not involved.
- ~~`FormSchema.submit.url`~~ — the field is `SubmitAction.action_ref` (`schema.py:311`); the A2UI submit URL is derived from tenant + form_uid, not from `submit`.

---

## 7. Implementation Notes & Constraints

### FieldType → Basic primitive mapping (normative for Module 2)

| FieldType(s) | Primitive | Props / checks |
|---|---|---|
| TEXT, SEARCH, MASKED, COLOR, COLOR_PICKER | `TextField` | `variant="shortText"`; `placeholder` |
| TEXT_AREA | `TextField` | `variant="longText"` |
| NUMBER, INTEGER | `TextField` | `variant="number"`; `numeric` check from min/max_value |
| PASSWORD | `TextField` | `variant="obscured"` |
| EMAIL | `TextField` | `variant="shortText"` + `email` check always |
| URL, PHONE | `TextField` | `variant="shortText"` + `regex` check (constraint pattern or a conservative default) |
| BOOLEAN | `CheckBox` | `value` bound |
| DATE / TIME / DATETIME | `DateTimeInput` | `enableDate` / `enableTime` / both; `min`/`max` from constraints when ISO strings |
| SELECT, DYNAMIC_SELECT (static options only) | `ChoicePicker` | `variant="mutuallyExclusive"`, `options` from `FieldOption` |
| MULTI_SELECT, TAGS, TRANSFER_LIST | `ChoicePicker` | `variant="multipleSelection"`, `displayStyle="chips"` for TAGS |
| NPS, LIKERT, RANKING | `Slider` | `min=scale_min or 0`, `max=scale_max or 10`, `steps` from `scale_step`; `anchor_labels` → `parrot_anchor_labels` extension |
| HIDDEN | — (dataModel only) | seeded in `/answers`; listed in `field_paths`; no component |
| FILE, IMAGE, IMAGE_DROPZONE, MULTI_UPLOAD, SIGNATURE, SIGNATURE_PAD, AUDIO, AI_CAPTURE | `Text` notice | `parrot_role="notice"`, `parrot_field_type`; `RenderWarning(reason="no A2UI v1.0 primitive for uploads/capture")` |
| GROUP, ARRAY, REMOTE_RESPONSE, AVAILABILITY, LOCATION, PLACE, REST, FORMULA, EMOJI, CRON, TREE_SELECT, CREDIT_CARD | `Text` notice | same degradation; GROUP/ARRAY children are NOT recursed in v1 |

`read_only` fields render their primitive with the value bound but are excluded
from `context.answers`-driven validation only if the client omits them; the
server pipeline is unchanged.

### Patterns to Follow
- Table-driven mapping with an explicit degraded set — `renderers/adaptive_card.py:71-119`; warnings loop `:252-260`.
- Lowering shape from `catalog/parrot/form.py::_lower_field` — inputs bound with `{"path": …}`, `required` → `CheckRule(FunctionCall("required", {"value": binding}))`, `Button.action.event` with `context` bindings, root `Column` FIRST in the components list.
- `metadata.extensions.parrot_*` for every ai-parrot semantic (docs/outputs/a2ui-v1.md §"metadata.extensions"); never a bare top-level prop.
- Always `serialize()` outbound envelopes; never write `"version"` by hand.
- Lazy optional import of ai-parrot exactly like `renderers/audio.py:151-154` (`try: from parrot… except ImportError as exc:`).
- Envelope framing exactly like `A2UIHandler.post` (single → `application/a2ui+json` body; many → `{"messages": [...]}`).
- Async-first, Google-style docstrings, strict type hints, Pydantic for the new private models, `self.logger` — per `CLAUDE.md`.
- Component ids: `root`, `root-title`, `root-description`, `sec-<section_id>`, `sub-<subsection_id>`, `f-<field_id>`, `f-<field_id>-error`, `root-status`, `root-actions`, `root-submit`, `root-submit-label`, `root-cancel`, `root-cancel-label` — deterministic so golden tests and `updateComponents` targets are stable.

### Known Risks / Gotchas
- **field_id vs JSON Pointer**: `DataBinding.path` rejects malformed pointers; `/` and `~` in `field_id` must be escaped (`~1`, `~0`) and unescaped on receipt. Component ids may contain the raw field_id (ids are free strings).
- **dataModel size**: `A2UIRuntime` caps at `A2UI_MAX_DATA_MODEL_BYTES` (1 MiB) — the form receiver should apply the same cap (`request.content_length` or `len(body)`), returning a generic `error` with `A2UIErrorCode.INTERNAL`-style code and 413.
- **Two answer sources**: `dataModel.answers` (authoritative when present) vs resolved `context.answers`; a client that never sends `dataModel` (surface created without `sendDataModel`) still works through `context`.
- **Optional dependency**: `_seed_default_renderers` currently treats import failure as a mis-install (`render.py:45-48`); the A2UI import is the one exception and must be guarded separately so the other five renderers still seed.
- **`validate_envelope` rejects unknown component names and LLM-origin actions** — always pass `origin=ProducerOrigin.TOOL`; the renderer must never be reachable from an LLM producer path.
- **Locale**: `LocalizedString` is `str | dict[str, str]`; resolve with the adaptive-card pattern (locale → `"en"` → first value → `""`).
- **Legacy parity**: any change to `submit_data`'s early body handling risks the `visit_context` split (`_extract_visit_context`, `handlers.py:400`) and `merge_partials` — unwrap the A2UI action into a plain dict *before* that split so both features keep working.
- **Confirmation target must exist**: `updateComponents` only replaces `root-status` because the renderer always emits it; do not remove the placeholder.
- **Concurrent ids**: the research-time provisional `FEAT-563` collided with another proposal; FEAT-544 is the reserved id — grep for stray `FEAT-563` in this feature's files before creating tasks.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `ai-parrot` | `>=1.0.0` (existing optional extra of parrot-formdesigner) | `parrot.outputs.a2ui` models, catalog, serialization; `parrot.a2a.models.A2UI_MEDIA_TYPE` |
| `aiohttp` | existing | handlers / tests |
| `pydantic` | existing (v2) | private models |

No new third-party packages.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree
  `.claude/worktrees/feat-FEAT-544-a2ui-form-output-renderer` branched from `dev`.
- **Task ordering**: Module 1 → Module 2 → Module 3 (renderer chain, sequential,
  same file); Module 4 may start in parallel with Module 2 (different file,
  only shares the pointer helpers from Module 1); Module 5 after 4; Module 6
  tests grow alongside each module and close after 5; Module 7 docs last.
- **Parallelizable**: {Module 2} ∥ {Module 4}; {Module 6 renderer tests} ∥
  {Module 6 wire/handler tests}.
- **Cross-feature dependencies**: none blocking. FEAT-527
  (infographic → A2UI migration) touches `catalog/parrot/*` but not
  `form.py`, `models.py` or `serialization.py`; FEAT-542 (LanceDB) is
  unrelated. Rebase-free: merge `dev` into the worktree if either lands first.

---

## 8. Open Questions

> Questions resolved in the proposal (`sdd/proposals/a2ui-form-output-renderer.proposal.md` §5) are carried forward verbatim and routed into the body above.

- [x] **U1 — Where does the A2UI submit action land?** — *Resolved in proposal*: a) Dual-wire `/data` — extend `POST /api/v1/{tenant}/forms/{form_uid}/data` to also accept a v1.0 `action` envelope (detected by body shape or `application/a2ui+json`); `Button.action.event.context` carries the submit URL. → §2 Overview (receiver half), Module 4/5, AC 4 & 9.
- [x] **U2 — What should the endpoint answer after an A2UI submit?** — *Resolved in proposal*: a) Full A2UI cycle — 422 → `error` envelopes with surfaceId+path per invalid field (plus `updateDataModel`); 200 → confirmation via `updateComponents`/`createSurface`; plain JSON stays for non-A2UI callers (content negotiation). → §2 Data Models (wire shapes), Module 4, AC 9. *Spec refinement*: confirmation uses `updateComponents` on the always-present `root-status` Text (not a new `createSurface`) so the surface id is stable.
- [x] **U3 — How should FieldTypes with no Basic primitive be handled in v1?** — *Resolved in proposal*: c) Hybrid — native where Basic can express it (NPS/LIKERT/RANKING→Slider, MULTI_SELECT/TAGS→multi ChoicePicker, HIDDEN→dataModel only, EMAIL/URL/PHONE→TextField+email/regex checks); degrade the rest with `parrot_role: notice` + `RenderedForm.warnings`; Parrot-catalog form components in a follow-up. → §7 mapping table, Module 2, AC 6.
- [x] **U4 — Which parts of the cycle beyond render → validate → submit → response are in scope?** — *Resolved in proposal*: a) Core cycle only — partial saves, `depends_on` conditional visibility and the lifecycle-event bridge are explicit non-goals for v1. → §1 Non-Goals.
- [x] **Exact `parrot_*` extension keys and whether `build_form()` is widened** — *Resolved in spec*: keys fixed in §2 Overview (`parrot_variant`, `parrot_form_uid`, `parrot_form_id`, `parrot_form_version`, `parrot_tenant`, `parrot_submit_url`, `parrot_field_id`, `parrot_field_uid`, `parrot_field_type`, `parrot_section_id`, `parrot_subsection_id`, `parrot_role`, `parrot_state`, `parrot_anchor_labels`); `build_form()` is **not** widened or called — its 6-kind `FormField` is a tool-facing API; the FormDesigner lowering lives in `renderers/a2ui.py`. — *Owner: Jesus Lara*
- [x] **Confirmation content and error code** — *Resolved in spec*: 200 → `updateDataModel(/submission)` echoing `submission_id`/`forwarded`/`forward_status` + `updateComponents` replacing `root-status` with "Form submitted." (`parrot_state: "submitted"`); 422 → `ErrorMessage(code="VALIDATION_FAILED", surfaceId, path=/answers/<field_id>)` built directly (no `A2UIErrorCode` change). — *Owner: Jesus Lara*
- [x] **How `prefilled`/`errors` reach the renderer** — *Resolved in spec*: v1 exposes them only through the Python API (`A2UIFormRenderer.render(prefilled=…, errors=…)`); `handle_render` keeps passing `locale` only (no query-param widening). A later feature may add `?session_id=` partial-aware prefill. — *Owner: Jesus Lara*
- [ ] **Default `regex` for URL/PHONE when the field has no `pattern` constraint** — pick conservative RFC-ish patterns during Module 2 and document them; not blocking. — *Owner: implementer*
- [ ] **Confirmation message localisation** — "Form submitted." is English-only in v1; decide whether to source it from `StyleSchema` (new field) or `form.submit.confirm_message` during Module 4. — *Owner: implementer*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-10 | Jesus Lara | Initial draft from proposal FEAT-544 (research state `sdd/state/FEAT-544/`); id reserved via `reserve_ids.py` after the provisional FEAT-563 collided with the concurrent LanceDB proposal |

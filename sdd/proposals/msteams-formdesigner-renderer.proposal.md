---
id: FEAT-551
title: MS Teams FormDesigner renderer — FormSchema → interactive Adaptive Card with a submit envelope routed through the Teams bot to POST …/forms/{uid}/data
slug: msteams-formdesigner-renderer
type: feature
mode: enrichment
status: accepted
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-11
  summary_oneline: Renderer exporting a FormDesigner Form/Survey as an MS Teams-compatible Adaptive Card JSON whose Submit reaches the existing form-data endpoint.
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-551/
created: 2026-09-11
updated: 2026-09-11
---

# FEAT-551 — MS Teams FormDesigner renderer (Adaptive Card + submit envelope)

> **Mode**: enrichment
> **Confidence**: high (after Q&A — 5/5 unknowns resolved)
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-551/`](../state/FEAT-551/)
> **FEAT-ID**: FEAT-551 — reserved via `reserve_ids.py` on 2026-09-11 (the proposal was drafted under provisional FEAT-564).

---

## 0. Origin

The original request, preserved verbatim (`sdd/state/FEAT-551/source.md`):

> Using the ability of FormDesigner to export a Form or survey in a format using a renderer to build a renderer to export a Form as an interactive Adaptive Card compatible with MS Teams and button for answer question will pointing to the existing endpoint for sending form's payload. for this spec we need to cover the basics of a form in Adaptive Card (in ai-parrot-integrations there are code for rendering input tools as adaptive cards, can we use that code as example we are looking for here), but check if we can upload pictures in a form exposed as an Adaptive Card, the Renderer will be responsible for export a Form Definition as a Adaptive Card but not responsible for sending, only returning the JSON of Form.

**Review-gate correction (user, verbatim)**:

> ai-parrot-integrations have MS bot framework integration to start a "bot" used as receptor of Action.Submit buttons, use that approach for answering forms via MS Teams.

**Initial signals** (extracted, not interpreted):
- Verbs: "export", "build a renderer", "pointing to the existing endpoint", "check if we can upload pictures" → feature/enrichment, no bug.
- Named entities: FormDesigner, renderer, Adaptive Card, MS Teams, `ai-parrot-integrations`, "existing endpoint for sending form's payload".
- Explicit non-goal: the renderer does **not** send; it returns JSON.
- Acceptance criteria provided: no (one explicit constraint: renderer returns JSON only).

---

## 1. Synthesis Summary

FormDesigner already ships an `AdaptiveCardRenderer` (`renderers/adaptive_card.py`) registered under the `adaptive` format key and served by `GET …/forms/{form_uid}/render/adaptive`; it emits native `Input.*` elements keyed by `field_id`, wizard/summary/error cards and i18n. What the request adds is (1) a **Submit that knows where the answers go** — today `Action.Submit.data` is only `{"_action": "submit"}`, which works solely inside a live Teams bot dialog; a standalone card has no receiver, and in Teams an `Action.Submit` can never POST to an HTTP URL (the payload always returns to the bot as `activity.value`). The design is therefore a Teams-targeted renderer subclass that embeds a versioned `_formdesigner` submit envelope (absolute `submit_url`, `form_uid`, `tenant`, form version) in the Submit action, plus a new branch in the existing Bot Framework receiver `MSTeamsAgentWrapper._handle_card_submission` (mirroring the TASK-2545 `a2ui_action` branch) that strips control keys, coerces Teams string values and POSTs the legacy JSON body to `POST …/forms/{form_uid}/data`. (2) **Pictures**: Microsoft's Teams documentation states verbatim that "Adaptive Cards within Teams don't provide support for file or image uploads", and the repo has no in-card upload path; upload fields will degrade explicitly (RenderWarning + `Action.OpenUrl` to the web upload flow) instead of today's silent `Input.Text` fallback. The renderer returns JSON only; the bot does the sending.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-551/findings/`. **No fabricated paths or symbols.**

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py` | `AdaptiveCardRenderer` | 121-1224 | existing FormSchema → Adaptive Card v1.x renderer (header, sections, per-field label/input/error, wizard, summary, error, i18n) — the extension target | F002, F004 |
| 2 | same | `AdaptiveCardRenderer._build_form_actions` | 1079-1113 | Submit button: `{"type":"Action.Submit","data":{"_action":"submit"}}` — no form identity or endpoint (**the gap**) | F004 |
| 3 | same | `_FIELD_TYPE_MAPPING`, upload fallback branch | 70-91, 1028-1044 | FILE/IMAGE/IMAGE_DROPZONE/MULTI_UPLOAD degrade to `Input.Text`; FILE/IMAGE absent from `_AC_FALLBACK_TYPES` (no RenderWarning) | F004, F007 |
| 4 | same | `_build_input_element` (base) | 774-777 | `{"id": field.field_id, "isRequired": field.required}` — inputs keyed by `field_id` | F004 |
| 5 | `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py` | `AbstractFormRenderer.render` | 57-89 | fixed signature `(form, style, *, locale, prefilled, errors) -> RenderedForm`; no channel/target parameter | F005 |
| 6 | `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | `RenderedForm` | 671-688 | `content`, `content_type`, `style_output`, `metadata`, `warnings` | F005 |
| 7 | `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/__init__.py` | exports | 14-44 | where the new renderer is exported | F006 |
| 8 | `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` | `_seed_default_renderers`, `register_renderer`, `handle_render` | 38-60, 63-73, 101-151 | format registry (`html`, `adaptive`, `xml`, `pdf`, `audio`); `handle_render` forwards only `locale` | F011 |
| 9 | `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | `POST {tp}/forms/{form_uid}/data` | 398-401 | the existing payload endpoint the Submit must reach | F010 |
| 10 | same | `POST {tp}/forms/{form_uid}/fields/{field_uid}/file-upload`, `GET …/thumbnail` | 424-433 | only image/file intake path (multipart → `FileEnvelope`) | F010, F019 |
| 11 | `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | `FormAPIHandler.submit_data` | 1464-1530 | legacy JSON contract `{field_id: value}` + optional `visit_context`; validate → persist → forward → 200 composite | F017 |
| 12 | `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | `MSTeamsAgentWrapper._handle_card_submission` | 359-491 | the Bot Framework receptor of every `Action.Submit` (`activity.value`); branches: `a2ui_token`, `a2ui_action`, `command`, `_action`; no dialog → "wasn't expecting it" | F009 |
| 13 | `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py` | `AdaptiveCardsRenderer._render_Button`, `_encode_binding_id` | 608-650, 112-136 | shipped precedent: routing envelope in `Action.Submit.data` + `Action.OpenUrl` | F013 |
| 14 | `packages/ai-parrot/src/parrot/outputs/cards/inputs.py`, `actions.py`, `attachment.py` | `InputText…InputChoiceSet`, `ActionSubmit`, `ActionOpenUrl`, `build_attachment` | 17-75, 17-39, 10-24 | typed AC 1.5 models — the "input tools as adaptive cards" code | F008 |
| 15 | `packages/ai-parrot-integrations/src/parrot/integrations/msteams/hitl_cards.py` | `TeamsCardRenderer` | 1-36 | second precedent: every Submit `data` carries `interaction_id` for correlation | F008 |
| 16 | `packages/ai-parrot-integrations/src/parrot/integrations/msteams/dialogs/presets/base.py` | `_get_card_renderer`, submitted-value merge | 160-176 | in-dialog consumer of `AdaptiveCardRenderer`; drops `_`-prefixed keys | F021 |
| 17 | `packages/ai-parrot-integrations/src/parrot/integrations/msteams/dialogs/orchestrator.py` | `RequestFormTool` / `ToolExtractor` imports | 17-19 | the bot's only FormDesigner usage is in-process; no REST client / base URL | F023 |
| 18 | `packages/parrot-formdesigner/tests/unit/test_renderers.py` | `TestAdaptiveCardRenderer` et al. | 357-490, 787-823 | coverage baseline; nothing asserts the Submit payload shape | F015 |

### 2.2 Constraints Discovered

- **Teams `Action.Submit` is bot-mediated, never an HTTP POST.** The Bot Framework delivers inputs + `data` as `activity.value` to the bot; Incoming Webhooks do not support `Action.Submit` at all. "Button pointing to the endpoint" must be an envelope the bot forwards. *Evidence*: F009, F020
- **No in-card file/image upload in Teams.** Microsoft: "Adaptive Cards within Teams don't provide support for file or image uploads." No `Input.File`/file-consent code exists in the repo. *Evidence*: F020, F014
- **Fixed renderer signature.** Per-target config (public base URL) must come via constructor/subclass; `handle_render` forwards only `locale`. *Evidence*: F005, F011
- **Dialog presets consume `AdaptiveCardRenderer`.** They rely on `_action` and drop `_`-prefixed keys; the default `adaptive` output must stay byte-identical → new subclass + key `teams`. *Evidence*: F021
- **Legacy `/data` contract is `{field_id: value}`.** Card inputs are keyed by `field_id`, so `activity.value` minus control keys is already the body. FEAT-544's A2UI dual-wire on `/data` is **not** implemented yet (`api/a2ui_wire.py` absent). *Evidence*: F017, F004, F016
- **Bot has no route to FormDesigner's REST API.** No `FormRegistry`, aiohttp `ClientSession` or base-URL config in wrapper/orchestrator/models → the envelope must carry an absolute `submit_url`. *Evidence*: F023
- **Teams card ceiling v1.6; positive/destructive styling and `Action.Submit.isEnabled` ignored.** Default version here is `ADAPTIVE_CARD_VERSION or "1.4"` — compatible. *Evidence*: F020, F004
- **FILE/IMAGE degrade silently today** (in `UPLOAD_FIELD_TYPES` but not `_AC_FALLBACK_TYPES`). *Evidence*: F004, F007
- **Teams returns `Input.Toggle` as `"true"/"false"` strings and multi-select `Input.ChoiceSet` as a comma-separated string** — the bot branch must coerce before POST (low-confidence; verify in spec). *Evidence*: F009, F017

### 2.3 Recent History (Relevant)

| Commit | When | Message | Touched |
|--------|------|---------|---------|
| `48227a5fd` | 2026-08-25 | feat(raw-upload-field-types): TASK-2449 — Other Renderers Update (html5/pdf/adaptive_card) | `renderers/adaptive_card.py` |
| `ca5e3dbc3` | 2026-08-22 | feat(field-type-catalog): TASK-2337 — renderer posture for the twelve new types | `renderers/adaptive_card.py` |
| `0ad7d9c3a` | 2026-08-29 | feat(a2ui-v1-dialect): TASK-2545 — Adaptive Cards native inputs, `Action.Submit{a2ui_action}`, Teams wrapper routes `a2ui_action` | `a2ui_renderers/adaptive_cards.py`, `msteams/wrapper.py` |
| `a5ac3cdbf` | 2026-07-21 | refactor: migrate A2UI, forms, and HITL card renderers to shared `parrot.outputs.cards` builder | `outputs/cards/*`, msteams |
| `9428e08b1` | 2026-07-23 | fix(msteams): unify adaptive card version | msteams |

Both areas are active but stable; no in-flight work touches the Submit payload. *Evidence*: F018

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`TeamsFormRenderer(AdaptiveCardRenderer)`** — new module `parrot_formdesigner/renderers/teams.py`; constructor takes a public base URL (settings/env, e.g. `FORMDESIGNER_PUBLIC_URL`) and optional upload-page URL template. Overrides `_build_form_actions` / `_build_wizard_actions` so the Submit action's `data` is:
  ```json
  {"_action": "submit",
   "_formdesigner": {"v": 1, "form_uid": "<uuid>", "tenant": "<tenant>",
                     "form_version": <n>, "submit_url": "https://…/api/v1/<tenant>/forms/<uuid>/data",
                     "wire": "legacy"}}
  ```
  Underscore-prefixed so the in-dialog presets keep ignoring it. Overrides the upload branch: `RenderWarning` + `Action.OpenUrl` to the web upload page for FILE/IMAGE/IMAGE_DROPZONE/MULTI_UPLOAD (two-step; the answer carries the returned `FileEnvelope` reference). `RenderedForm.metadata` records `{"channel": "msteams", "submit_url": …, "envelope_version": 1}`. Optionally builds elements via the typed `parrot.outputs.cards` models. *Evidence*: F004, F005, F013, F020
- **Format key `teams`** — `register_renderer("teams", TeamsFormRenderer(...))` in `api/render.py::_seed_default_renderers`, so `GET …/forms/{uid}/render/teams` returns the card JSON (`application/vnd.microsoft.card.adaptive`). *Evidence*: F011
- **Bot receiver branch** — `_formdesigner` branch in `MSTeamsAgentWrapper._handle_card_submission`, inserted after the `a2ui_action` branch and before `command`: strip `_`-prefixed keys, coerce Teams string values (toggle → bool, multi-select → list, number → int/float) against the envelope, `POST submit_url` with the legacy JSON body via aiohttp, then reply with a confirmation card (200) or `render_error`-style card (422 field errors). Never falls through to `dialog_context.continue_dialog()`. *Evidence*: F009, F017, F023
- **Tests** — renderer: envelope shape, `adaptive` output unchanged, upload-field posture and warnings, Teams v1.6 ceiling; wrapper: `activity.value` with `_formdesigner` → POST body/URL, coercion, 422 → error card, no fall-through (same harness as `tests/msteams/test_a2ui_submit.py`). *Evidence*: F015, F013
- **Docs** — `docs/formdesigner-msteams-renderer.md` (envelope contract, upload limitation, bot setup).

### What Changes

- **`renderers/__init__.py`** — export `TeamsFormRenderer`. *Evidence*: F006
- **`api/render.py::_seed_default_renderers`** — register `teams` (config-driven base URL; skip/log if unset). *Evidence*: F011
- **`msteams/wrapper.py::_handle_card_submission`** — new branch (additive). *Evidence*: F009
- **`renderers/adaptive_card.py`** — at most: make the upload branch and action builders overridable hooks (no output change for `adaptive`). *Evidence*: F004, F021

### What's Untouched (Non-Goals)

- `AdaptiveCardRenderer` output under `adaptive` — byte-identical (dialog presets depend on it). *Evidence*: F021
- `submit_data` / `validate` handlers, persistence, forwarding, lifecycle events — unchanged; the bot is just another legacy JSON client. *Evidence*: F017
- A2UI wire on `/data` (FEAT-544 TASK-3074/3075) — the envelope is versioned (`wire: "legacy"`) so an A2UI variant can be added later; no dependency now. *Evidence*: F016
- In-card image upload — impossible on Teams; bot-side "send the photo as a chat attachment" intake is a **follow-up feature**, not this one. *Evidence*: F020, F022
- Proactive delivery of the card to users/channels (Graph / ProactiveMessenger) — the renderer only returns JSON; posting it is the caller's job.
- Wizard (`render_section`) multi-step flow over the standalone path — v1 covers the single complete-form card; wizard keeps working only inside dialogs.

### Patterns to Follow

- Envelope-in-`Action.Submit.data` + wrapper branch that unwraps it — `a2ui_renderers/adaptive_cards.py::_render_Button` and `wrapper.py` L413-443. *Evidence*: F013, F009
- Correlation key in every Submit `data` — `hitl_cards.py::TeamsCardRenderer` (`interaction_id`). *Evidence*: F008
- Table-driven FieldType mapping + explicit degraded set with `RenderWarning` — `adaptive_card.py` L70-118. *Evidence*: F004
- Format registration — `api/render.py::register_renderer`. *Evidence*: F011
- Typed AC models — `parrot.outputs.cards` (`InputText`, `ActionSubmit`, `ActionOpenUrl`, `build_attachment`). *Evidence*: F008

### Integration Risks

- **Teams value coercion**: toggles/multi-select arrive as strings; wrong coercion → 422 from the validator. *Mitigation*: coerce by field type using the form schema fetched from `GET …/forms/{uid}/schema` or a type map embedded in the envelope; test against recorded `activity.value` samples. *Evidence*: F009, F017 (low confidence — verify)
- **Auth on `POST …/data`**: private forms require tenant membership; the bot has no user token. *Mitigation*: v1 targets public forms, or the bot carries a service credential/header; decide in spec. *Evidence*: F017
- **Absolute URL correctness**: the renderer needs a reachable public base URL at render time. *Mitigation*: settings-driven; `render/teams` returns 503 with a clear error when unset. *Evidence*: F011, F023
- **Card size / Teams v1.6 ceiling**: long forms may exceed Teams card limits. *Mitigation*: reuse the size guard in `parrot.outputs.cards.renderer` or emit a warning. *Evidence*: F008, F020
- **Two-step upload UX**: `Action.OpenUrl` leaves Teams; the user must come back and submit. *Mitigation*: explicit helper text on the card; bot-attachment intake as follow-up. *Evidence*: F020

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | An `AdaptiveCardRenderer` for FormSchema exists and is served at `GET …/render/adaptive` | F004, F011 | high | direct read |
| C2 | Its Submit carries no form identity/endpoint; a standalone card has no receiver in the bot | F004, F009 | high | direct read of both sides |
| C3 | Teams `Action.Submit` cannot target an HTTP URL; payload returns to the bot | F020, F009 | high | Microsoft docs + wrapper code |
| C4 | Adaptive Cards in Teams cannot upload files/images; repo has no in-card upload code | F020, F014 | high | verbatim doc statement + grep absence |
| C5 | TASK-2545's `a2ui_action` envelope + wrapper branch is the pattern to mirror | F013, F009 | high | shipped, tested code |
| C6 | `activity.value` minus control keys maps 1:1 onto the legacy `/data` body | F017, F004 | medium | ids match; value coercion unverified |
| C7 | A Teams variant must be a subclass/format key, not a change to `adaptive` | F021, F011 | high | presets consume the default renderer (user confirmed) |
| C8 | The bot cannot reach FormDesigner's REST API today (no client/base URL) | F023 | high | grep absence across wrapper/orchestrator/models |
| C9 | Teams input value coercion (toggle/multiselect strings) is needed at the receiver | F009 | low | platform behaviour, not verified in repo |

Distribution: **7** high, **1** medium, **1** low. Overall **high** — the single low claim (C9) affects implementation detail, not the design.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Is the Teams-side receiver in scope?** — *Resolved*: yes — "ai-parrot-integrations have MS bot framework integration to start a 'bot' used as receptor of Action.Submit buttons, use that approach for answering forms via MS Teams." The existing `MSTeamsAgentWrapper` gets a `_formdesigner` branch. *Resolves*: H1, H2
- [x] **How does the bot learn the absolute `POST …/data` URL?** — *Resolved*: a) absolute `submit_url` in the envelope; the renderer is configured with a public base URL. *Resolves*: C8
- [x] **Separate renderer or extend `adaptive`?** — *Resolved*: a) new subclass + format key `teams`; `adaptive` unchanged. *Resolves*: C7
- [x] **Posture for image/file fields?** — *Resolved*: a) `RenderWarning` + `Action.OpenUrl` per upload field to the web form/upload page (two-step). *Resolves*: C4
- [x] **Wire shape the bot POSTs?** — *Resolved*: a) legacy JSON `{field_id: value}` now, with a versioned `_formdesigner` envelope so an A2UI variant can be added when FEAT-544 lands. *Resolves*: C6

### Unresolved (defer to spec / implementation)

- [ ] **How does the bot authenticate `POST …/data` for private (non-public) forms?** — *Owner*: spec. *Blocks*: none of the design; affects v1 scope (public forms only vs service credential). *Plausible*: a) public forms only in v1 · b) bot-level service token header · c) tenant membership check bypass for the bot identity.
- [ ] **Exact Teams coercion rules per FieldType** (toggle, multi-select, number, date). — *Owner*: spec/implementation. *Blocks*: C9. *Plausible*: a) coerce from the envelope's field-type map · b) fetch `GET …/forms/{uid}/schema` in the bot · c) let the validator accept strings.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-551`** — *Rationale*: localization is high-confidence, all five design unknowns are resolved, and the design is an extension of shipped code (one renderer subclass, one format registration, one bot branch). The spec can be written directly; the two remaining questions are implementation-level.

### Alternatives

- **`/sdd-brainstorm FEAT-551`** — only if the auth question should be explored against a broader "bot ↔ FormDesigner API" credential design.
- **Manual review** — not needed; research completed within budget.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-551/state.json` |
| Source (raw) | `sdd/state/FEAT-551/source.md` |
| Research plan | `sdd/state/FEAT-551/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-551/findings/F001-*.md` … `F023-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-551/synthesis.json` |

**Budget consumed** (profile `default`):
- Files read: 22 / 40
- Grep calls: 13 / 25
- Git calls: 2 / 10
- Wiki calls: 5 (free) · Web fetch: 1 (Microsoft Learn cards-reference; WebSearch tool errored — single primary source)
- Truncated: **no**

**Mode determination**: `auto` → `enrichment` (wiki surfaced an existing `AdaptiveCardRenderer` and Teams submit routing; no negation/bug verbs in the source).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (jlara@trocglobal.com) via Claude Code |

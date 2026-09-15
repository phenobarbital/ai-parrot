<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
FormDesigner already ships an `AdaptiveCardRenderer` (`renderers/adaptive_card.py`) registered under the `adaptive` format key and served by `GET …/forms/{form_uid}/render/adaptive`; it emits native `Input.*` elements keyed by `field_id`, wizard/summary/error cards and i18n. What the request adds is (1) a **Submit that knows where the answers go** — today `Action.Submit.data` is only `{"_action": "submit"}`, which works solely inside a live Teams bot dialog; a standalone card has no receiver, and in Teams an `Action.Submit` can never POST to an HTTP URL (the payload always returns to the bot as `activity.value`). The design is therefore a Teams-targeted renderer subclass that embeds a versioned `_formdesigner` submit envelope (absolute `submit_url`, `form_uid`, `tenant`, form version) in the Submit action, plus a new branch in the existing Bot Framework receiver `MSTeamsAgentWrapper._handle_card_submission` (mirroring the TASK-2545 `a2ui_action` branch) that strips control keys, coerces Teams string values and POSTs the legacy JSON body to `POST …/forms/{form_uid}/data`. (2) **Pictures**: Microsoft's Teams documentation states verbatim that "Adaptive Cards within Teams don't provide support for file or image uploads", and the repo has no in-card upload path; upload fields will degrade explicitly (RenderWarning + `Action.OpenUrl` to the web upload flow) instead of today's silent `Input.Text` fallback. The renderer returns JSON only; the bot does the sending.

Original request: Using the ability of FormDesigner to export a Form or survey in a format using a renderer to build a renderer to export a Form as an interactive Adaptive Card compatible with MS Teams and button for answer question will pointing to the existing endpoint for sending form's payload. for this spec we need to cover the basics of a form in Adaptive Card (in ai-parrot-integrations there are code for rendering input tools as adaptive cards, can we use that code as example we are looking for here), but check if we can upload pictures in a form exposed as an Adaptive Card, the Renderer will be responsible for export a Form Definition as a Adaptive Card but not responsible for sending, only returning the JSON of Form.

User correction: ai-parrot-integrations have MS bot framework integration to start a "bot" used as receptor of Action.Submit buttons, use that approach for answering forms via MS Teams.

### Constraints and goals
- **Teams `Action.Submit` is bot-mediated, never an HTTP POST.** The Bot Framework delivers inputs + `data` as `activity.value` to the bot; Incoming Webhooks do not support `Action.Submit` at all. "Button pointing to the endpoint" must be an envelope the bot forwards. *Evidence*: F009, F020
- **No in-card file/image upload in Teams.** Microsoft: "Adaptive Cards within Teams don't provide support for file or image uploads." No `Input.File`/file-consent code exists in the repo. *Evidence*: F020, F014
- **Fixed renderer signature.** Per-target config (public base URL) must come via constructor/subclass; `handle_render` forwards only `locale`. *Evidence*: F005, F011
- **Dialog presets consume `AdaptiveCardRenderer`.** They rely on `_action` and drop `_`-prefixed keys; the default `adaptive` output must stay byte-identical → new subclass + key `teams`. *Evidence*: F021
- **Legacy `/data` contract is `{field_id: value}`.** Card inputs are keyed by `field_id`, so `activity.value` minus control keys is already the body. FEAT-544's A2UI dual-wire on `/data` is **not** implemented yet (`api/a2ui_wire.py` absent). *Evidence*: F017, F004, F016
- **Bot has no route to FormDesigner's REST API.** No `FormRegistry`, aiohttp `ClientSession` or base-URL config in wrapper/orchestrator/models → the envelope must carry an absolute `submit_url`. *Evidence*: F023
- **Teams card ceiling v1.6; positive/destructive styling and `Action.Submit.isEnabled` ignored.** Default version here is `ADAPTIVE_CARD_VERSION or "1.4"` — compatible. *Evidence*: F020, F004
- **FILE/IMAGE degrade silently today** (in `UPLOAD_FIELD_TYPES` but not `_AC_FALLBACK_TYPES`). *Evidence*: F004, F007
- **Teams returns `Input.Toggle` as `"true"/"false"` strings and multi-select `Input.ChoiceSet` as a comma-separated string** — the bot branch must coerce before POST (low-confidence; verify in spec). *Evidence*: F009, F017

### Recommended option / probable scope
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

### Verified code anchors (paths only — open them yourself)
packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py
packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py
packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
packages/parrot-formdesigner/src/parrot_formdesigner/renderers/__init__.py
packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py
packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py
packages/ai-parrot/src/parrot/outputs/cards/inputs.py
packages/ai-parrot-integrations/src/parrot/integrations/msteams/hitl_cards.py
packages/ai-parrot-integrations/src/parrot/integrations/msteams/dialogs/presets/base.py
packages/ai-parrot-integrations/src/parrot/integrations/msteams/dialogs/orchestrator.py
packages/parrot-formdesigner/tests/unit/test_renderers.py

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: MS Teams FormDesigner Renderer (Adaptive Card + submit envelope via the Teams bot)

**Feature ID**: FEAT-551
**Date**: 2026-09-11
**Author**: Jesus Lara
**Status**: approved
**Target version**: parrot-formdesigner 1.1.0 · ai-parrot-integrations (msteams) next minor
**Proposal**: `sdd/proposals/msteams-formdesigner-renderer.proposal.md` (accepted; drafted under provisional FEAT-564, re-id'd to the ledger-reserved FEAT-551)
**Research audit**: `sdd/state/FEAT-551/` (23 findings, synthesis, design research)

---

## 1. Motivation & Business Requirements

### Problem Statement

FormDesigner already ships an `AdaptiveCardRenderer` (`renderers/adaptive_card.py`) registered
under the `adaptive` format key and served by `GET …/forms/{form_uid}/render/adaptive`. It emits
native `Input.*` elements keyed by `field_id`, wizard/summary/error cards and i18n. Two things are
missing for a Form or Survey to be **answered from MS Teams as a standalone card**:

1. **The Submit button does not know where the answers go.** Today `Action.Submit.data` is only
   `{"_action": "submit"}`, which works solely inside a live Teams bot dialog. A card posted on its
   own has no receiver: the bot's `_handle_card_submission` finds no active dialog and replies
   *"I received your submission but wasn't expecting it"*. In Teams an `Action.Submit` can never
   POST to an HTTP URL — the payload always returns to the bot as `activity.value` — so *"a button
   pointing to the existing endpoint"* has to be an **envelope the bot forwards** to
   `POST …/forms/{form_uid}/data`.
2. **Pictures cannot be uploaded from a card.** Microsoft's Teams documentation states verbatim
   *"Adaptive Cards within Teams don't provide support for file or image uploads"*, and the repo
   has no in-card upload path. Upload fields currently degrade to a silent `Input.Text`.

The original request (verbatim) is preserved in the proposal §0. The user's review-gate correction:
*"ai-parrot-integrations have MS bot framework integration to start a 'bot' used as receptor of
Action.Submit buttons, use that approach for answering forms via MS Teams."*

### Goals

- G1. A new renderer, **`TeamsFormRenderer(AdaptiveCardRenderer)`**, exports a `FormSchema` as an
  MS Teams-compatible Adaptive Card whose terminal Submit carries a versioned **`_formdesigner`
  envelope** (absolute `submit_url`, `form_uid`, `tenant`, `form_version`, `is_public`, optional
  `sig`). The renderer **returns JSON only; it never sends.**
- G2. The renderer is reachable over HTTP under its own format key **`teams`**
  (`GET …/forms/{form_uid}/render/teams`), registered only when a public base URL is configured.
- G3. The **existing Bot Framework bot** (`MSTeamsAgentWrapper._handle_card_submission`) receives
  the card's `Action.Submit`, validates the envelope, and POSTs the answers as the **legacy JSON
  body** (`{field_id: value}`) to `submit_url`, replying to the user with a confirmation or an
  error card. Public forms work unauthenticated; an optional bearer token unlocks private forms.
- G4. Upload fields (FILE / IMAGE / IMAGE_DROPZONE / MULTI_UPLOAD) degrade **explicitly**:
  a `RenderWarning` plus an `Action.OpenUrl` to the existing web form page, never a silent text box.
- G5. The default `adaptive` renderer's serialized output stays **byte-identical** (the Teams dialog
  presets depend on it).
- G6. The envelope is **versioned** (`v: 1`, `wire: "legacy"`) so an A2UI wire variant can be added
  when FEAT-544's dual-wire `/data` lands, without breaking bots that only know `legacy`.

### Non-Goals (explicitly out of scope)

- Changing `submit_data` / `validate` handlers, persistence, forwarding, lifecycle events, or any
  legacy status code. The bot is just another legacy JSON client.
- The A2UI wire on `/data` (FEAT-544 TASK-3074/3075). No dependency; only the `wire` discriminator
  is reserved.
- In-card image upload (impossible on Teams). Bot-side "send the photo as a chat attachment"
  intake is a follow-up feature.
- Proactive delivery of the card to users/channels (Graph / `ProactiveMessenger`). Posting the JSON
  is the caller's job.
- Standalone multi-step wizard over Teams. v1 renders the single complete-form card;
  `render_section` keeps its dialog semantics (non-terminal actions unchanged).
- Server-side idempotency key on `/data` (bot-side best-effort dedupe only, see §7).
- Refactoring the module-level `_RENDERERS` registry into app state (S1 partial — injection point
  only).
- Changing the dialog presets' `startswith('_')` submit filter (`presets/base.py:160-167`).

---

## 2. Architectural Design

### Overview

Two additive pieces, one on each side of the Teams boundary:

**Renderer side (parrot-formdesigner).** `TeamsFormRenderer` subclasses `AdaptiveCardRenderer` and
overrides three hooks introduced into the base class (with byte-identical default behaviour):
`_submit_action_data(form, *, terminal)` (the Submit `data` dict), `_build_upload_element(field,
value, locale)` (the upload-field element), and a new class attribute `accepts_tenant`. The
subclass is constructed with a **public base URL** (constructor arg, env fallback
`FORMDESIGNER_PUBLIC_URL`), the API base path (default `/api/v1`), the UI base path (default `""`)
and an optional signing secret. From those plus the route-declared tenant it builds:

```json
{"_action": "submit",
 "_formdesigner": {"v": 1, "wire": "legacy",
                   "form_uid": "<uuid>", "tenant": "<tenant>", "form_version": "<published_version or version>",
                   "is_public": true,
                   "submit_url": "https://forms.example.com/api/v1/<tenant>/forms/<uuid>/data",
                   "form_url":   "https://forms.example.com/<tenant>/forms/<uuid>",
                   "sig": "<hmac-sha256 hex or null>"}}
```

`RenderedForm.metadata` records `{"channel": "msteams", "envelope": <same dict>, "envelope_version": 1}`.
Upload fields render a label, an instruction `TextBlock` ("Attachments can't be uploaded from
Teams — open the web form"), an `Action.OpenUrl` to `form_url`, and a `RenderWarning`
(`renderer="teams"`). Registration: `setup_form_api(..., public_base_url=..., teams_renderer=...)`
calls `register_renderer("teams", …)`; when neither is given and the env var is unset, `teams` is
simply absent from `supported_formats()` and the dispatcher's existing 415 path answers.
`handle_render` gains two small, backward-compatible behaviours: it passes `tenant=<declared
tenant>` to renderers that set `accepts_tenant = True`, and `?with_meta=true` returns
`{"content", "content_type", "warnings", "metadata"}` instead of the bare content.

**Bot side (ai-parrot-integrations).** `MSTeamsAgentWrapper._handle_card_submission` gains a
`_formdesigner` branch, inserted after the `a2ui_action` branch and before the `command` branch,
mirroring TASK-2545's pattern. It (1) parses the envelope with the shared Pydantic model
`TeamsSubmitEnvelope` (imported from `parrot_formdesigner.renderers.teams` — the integrations
package already depends on parrot-formdesigner); (2) **verifies before trusting**: https scheme,
host ∈ `config.formdesigner_allowed_hosts` (branch disabled with a user-facing message when the
list is empty), URL path `== f"{api_base}/{tenant}/forms/{form_uid}/data"` for the envelope's own
tenant/form_uid, and HMAC `sig` when `config.formdesigner_submit_secret` is set; (3) dedupes on
`activity.id` (in-process TTL cache); (4) builds the body as `activity.value` minus exactly
`{"_action", "_formdesigner"}` — **raw values, no coercion** (`FormValidator._coerce_value`
already maps `"true"`, numeric strings and comma-separated lists); (5) POSTs through one lazily
created shared `aiohttp.ClientSession` (15 s timeout, 1 MiB response cap, `allow_redirects=False`),
adding `Authorization: Bearer <config.formdesigner_submit_token>` when configured; (6) replies with
a confirmation card (200: `submission_id`), a field-error card (422: per-field messages),
a "private form / bot not authorised" card (401/403), or a deterministic network-error text. The
branch **always returns** — it never falls through to `dialog_context.continue_dialog()`.

Authentication decision (resolved in Q&A): v1 works unauthenticated for public forms
(`FormSchema.is_public`), which `enforce_membership_unless_public` already exempts; the optional
bearer token is the only private-form path in v1.

### Component Diagram

```
 FormDesigner API (aiohttp)                                  MS Teams client
 ┌──────────────────────────────────────────────┐            ┌──────────────┐
 │ GET {api}/{tenant}/forms/{uid}/render/teams  │  card JSON │ renders card │
 │   handle_render ──► TeamsFormRenderer.render ├──────────► │ user answers │
 │   (tenant=…, ?with_meta=true)                │  (caller   │ taps Submit  │
 │                                              │   posts it)└──────┬───────┘
 │ POST {api}/{tenant}/forms/{uid}/data         │                   │ activity.value =
 │   submit_data (unchanged, legacy JSON)  ◄────┼──────┐            │ {inputs…, _action, _formdesigner}
 │ GET  {ui}/{tenant}/forms/{uid}  (web form,   │      │            ▼
 │      upload path for FILE/IMAGE fields)      │      │   Bot Framework → MSTeamsAgentWrapper
 └──────────────────────────────────────────────┘      │   _handle_card_submission
                                                       │     ├─ a2ui_token / a2ui_action (existing)
   TeamsSubmitEnvelope (Pydantic, shared model)        │     ├─ _formdesigner  ◄── NEW branch
   parrot_formdesigner.renderers.teams                 └─────┤    parse → verify(url, sig) → dedupe
                                                             │    → POST legacy body (bearer opt.)
                                                             │    → reply card (200/422/401/net)
                                                             ├─ command (existing)
                                                             └─ _action → dialog (existing)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AdaptiveCardRenderer` (`renderers/adaptive_card.py:121`) | extends (subclass) + adds 2 overridable hooks | default output byte-identical; hooks default to current behaviour |
| `AbstractFormRenderer.render` (`renderers/base.py:68-76`) | signature unchanged; new optional class attr `accepts_tenant` | dispatcher passes `tenant=` only when the attr is true |
| `api/render.py::handle_render` (101-151) | modifies | `tenant=` pass-through, `?with_meta=true`, `ValueError` → 400 |
| `api/render.py::register_renderer` (63-73) | uses | registers `teams` |
| `api/routes.py::setup_form_api` (191-212) | modifies (2 new kwargs) | `public_base_url: str \| None`, `teams_renderer: AbstractFormRenderer \| None` |
| `ui/routes.py::setup_form_ui` (147-193) | uses (URL only) | `form_url` targets the served web form page |
| `POST {tp}/forms/{form_uid}/data` (`routes.py:398-401`, `handlers.py:1464`) | uses (HTTP client) | untouched; legacy body |
| `MSTeamsAgentWrapper._handle_card_submission` (`wrapper.py:359-491`) | modifies (new branch) | inserted after `a2ui_action`, before `command` |
| `MSTeamsAgentConfig` (`models.py:14-53`, `from_dict` 114) | modifies (4 new fields) | `formdesigner_allowed_hosts`, `formdesigner_submit_token`, `formdesigner_submit_secret`, `formdesigner_submit_timeout` |
| `GraphClient` session pattern (`graph.py:116-136`) | pattern reuse | lazy shared `ClientSession` + `close()` |
| `parrot.outputs.cards` (`ActionSubmit`, `ActionOpenUrl`, `TextSection`, `render`) | uses (bot reply cards) | wrapper already imports this package (wrapper.py:37-47) |
| `FormValidator._coerce_value` (`validators.py:586`) | relies on | server-side coercion of Teams string values |
| Dialog presets (`presets/base.py:174-176`) | unaffected | keep instantiating `AdaptiveCardRenderer()` |

### Data Models

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py  (new)
from typing import Literal
import uuid
from pydantic import BaseModel, Field, HttpUrl

RESERVED_CONTROL_KEYS: frozenset[str] = frozenset({"_action", "_formdesigner"})
ENVELOPE_KEY: str = "_formdesigner"

class TeamsSubmitEnvelope(BaseModel):
    """Routing envelope carried in ``Action.Submit.data["_formdesigner"]``.

    Shared by the renderer (producer) and the Teams bot (consumer). ``sig`` is
    an HMAC-SHA256 hex digest over the canonical JSON of every other field
    (sorted keys, no whitespace); ``None`` when the renderer has no secret.
    """
    v: Literal[1] = 1
    wire: Literal["legacy"] = "legacy"
    form_uid: uuid.UUID
    tenant: str = Field(min_length=1)
    form_version: str
    is_public: bool
    submit_url: HttpUrl
    form_url: HttpUrl
    sig: str | None = None

    def canonical_payload(self) -> bytes:
        """Bytes signed by ``sign``/verified by ``verify`` (all fields but ``sig``)."""

    def sign(self, secret: str) -> "TeamsSubmitEnvelope":
        """Return a copy with ``sig`` set (HMAC-SHA256, hex)."""

    def verify(self, secret: str) -> bool:
        """Constant-time HMAC check; ``False`` when ``sig`` is ``None``."""
```

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py  (modifies MSTeamsAgentConfig, line 14)
formdesigner_allowed_hosts: Optional[List[str]] = None   # hostnames the bot may POST to; None/[] disables the branch
formdesigner_submit_token: Optional[str] = None           # sent as Authorization: Bearer … (private forms)
formdesigner_submit_secret: Optional[str] = None          # HMAC secret; when set, envelopes without a valid sig are rejected
formdesigner_submit_timeout: float = 15.0                 # aiohttp ClientTimeout(total=…)
```

### New Public Interfaces

```python
# parrot_formdesigner.renderers.teams
class TeamsFormRenderer(AdaptiveCardRenderer):
    RENDERER_NAME = "teams"
    accepts_tenant = True
    def __init__(self, public_base_url: str | None = None, *, api_base_path: str = "/api/v1",
                 ui_base_path: str = "", signing_secret: str | None = None,
                 version: str | None = None) -> None: ...
    async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None,
                     tenant: str | None = None) -> RenderedForm: ...
    def build_envelope(self, form: FormSchema, tenant: str) -> TeamsSubmitEnvelope: ...

# parrot_formdesigner.api.routes.setup_form_api  — two new keyword arguments
setup_form_api(app, registry, *, ..., public_base_url: str | None = None,
               teams_renderer: AbstractFormRenderer | None = None) -> None

# GET {api}/{tenant}/forms/{form_uid}/render/teams[?locale=..][&with_meta=true]

# parrot.integrations.msteams.wrapper.MSTeamsAgentWrapper
async def _handle_formdesigner_submit(self, turn_context, submitted_data: dict) -> None
async def close_formdesigner_client(self) -> None
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Base hooks + `TeamsFormRenderer` + envelope | yes | hook names/signatures fixed below; envelope schema fixed; golden fixture guards `adaptive` | — |
| M2: Upload-field posture | yes | element shape, warning text, `form_url` target fixed below | — |
| M3: Registration + `handle_render` extensions | yes | kwargs, env var, `with_meta` JSON shape, 400/415 behaviour fixed | — |
| M4: Bot receiver branch | yes | insertion point, verification order, reserved keys, HTTP client bounds, reply-card mapping fixed | — |
| M5: Documentation | yes | file name and sections fixed | — |

### Module 1: Overridable hooks in `AdaptiveCardRenderer` + `TeamsFormRenderer` + `TeamsSubmitEnvelope`
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py` (modify),
  `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py` (new),
  `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/__init__.py` (modify — export)
- **Responsibility**: add two hooks to the base renderer with byte-identical defaults; implement the
  Teams subclass that fills the terminal Submit `data` with the envelope, records metadata, and
  resolves the tenant; define the shared envelope model.
- **Depends on**: existing `AdaptiveCardRenderer`, `FormSchema`, `RenderedForm`, `RenderWarning`.
- **Interface Skeleton**:
  ```python
  # renderers/adaptive_card.py  (modifies adaptive_card.py:1079-1113 and :1115-1189)
  class AdaptiveCardRenderer(AbstractFormRenderer):            # verified: adaptive_card.py:121
      RENDERER_NAME: str = "adaptive_card"   # new; used for RenderWarning.renderer (currently the literal at :262)
      accepts_tenant: bool = False           # new; read by api/render.py::handle_render

      def _submit_action_data(self, form: FormSchema | None, *, terminal: bool) -> dict[str, Any]:
          """Return the ``data`` dict of the Submit action. Default: ``{"_action": "submit"}``
          (byte-identical to today). Subclasses add routing keys; must keep ``_action``."""

      def _build_upload_element(self, field: FormField, value: Any, locale: str) -> dict[str, Any] | None:
          """Element for FILE/IMAGE/IMAGE_DROPZONE/MULTI_UPLOAD. Default: the current
          Input.Text filename fallback (moved verbatim from :1033-1044)."""

      def _build_form_actions(self, show_cancel: bool = True, submit_label: str = "Submit",
                              cancel_label: str = "Cancel", *, form: FormSchema | None = None) -> list[dict[str, Any]]:
          """Unchanged output; Submit ``data`` now comes from ``_submit_action_data(form, terminal=True)``."""

      def _build_wizard_actions(self, is_first: bool, is_last: bool, show_back: bool = True,
                                show_cancel: bool = True, show_skip: bool = False,
                                cancel_label: str = "Cancel", *, form: FormSchema | None = None) -> list[dict[str, Any]]:
          """Unchanged output; ONLY the ``is_last`` Submit calls ``_submit_action_data(form, terminal=True)``;
          Back/Skip/Cancel/Next keep their literal ``{"_action": ...}``."""
      # render() (:182-273) and render_section() (:275-345) pass ``form=form`` to the builders.

  # renderers/teams.py  (new)
  class TeamsSubmitEnvelope(BaseModel): ...                     # see §2 Data Models

  class TeamsRenderConfigError(ValueError):
      """Raised when the renderer cannot build absolute URLs (no public_base_url / no tenant)."""

  class TeamsFormRenderer(AdaptiveCardRenderer):               # AdaptiveCardRenderer verified: adaptive_card.py:121
      """FormSchema -> MS Teams Adaptive Card whose Submit carries a TeamsSubmitEnvelope.

      Returns JSON only; never sends. Teams constraints honoured: schema version <= 1.6
      (default DEFAULT_ADAPTIVE_CARD_VERSION, verified parrot/outputs/cards/spec.py:12), no
      reliance on positive/destructive styling, input ids = field_id (no '/' encoding needed).
      """
      RENDERER_NAME = "teams"
      accepts_tenant = True

      def __init__(self, public_base_url: str | None = None, *, api_base_path: str = "/api/v1",
                   ui_base_path: str = "", signing_secret: str | None = None,
                   version: str | None = None) -> None:
          """``public_base_url`` falls back to env ``FORMDESIGNER_PUBLIC_URL``; if still unset,
          ``render`` raises TeamsRenderConfigError. Trailing slashes are stripped."""

      def build_envelope(self, form: FormSchema, tenant: str) -> TeamsSubmitEnvelope:
          """form_version = form.published_version or form.version (verified schema.py:469,455);
          submit_url = f"{public_base_url}{api_base_path}/{tenant}/forms/{form.form_uid}/data";
          form_url   = f"{public_base_url}{ui_base_path}/{tenant}/forms/{form.form_uid}";
          signed when ``signing_secret`` is set."""

      async def render(self, form: FormSchema, style: StyleSchema | None = None, *, locale: str = "en",
                       prefilled: dict[str, Any] | None = None, errors: dict[str, str] | None = None,
                       tenant: str | None = None) -> RenderedForm:
          """tenant := tenant or form.tenant (verified schema.py:463); raises TeamsRenderConfigError if None.
          Delegates to super().render(); then sets RenderedForm.metadata =
          {"channel": "msteams", "envelope": <dict>, "envelope_version": 1}. Warnings from
          upload fields use renderer="teams"."""

      def _submit_action_data(self, form: FormSchema | None, *, terminal: bool) -> dict[str, Any]:
          """{"_action": "submit", "_formdesigner": envelope.model_dump(mode="json")} when terminal
          and form is not None; otherwise the base default."""
  ```
  Tenant plumbing inside `render`: the base `render()` calls the builders synchronously, so the
  subclass stores the resolved tenant on `self._current_tenant` for the duration of the call
  (renderer instances are created per request by `_seed`/`setup_form_api` and by the presets, never
  shared across concurrent renders with different tenants; documented in §7).

### Module 2: Upload-field posture for Teams
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py` (same file as M1),
  `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py` (uses the M1 hook)
- **Responsibility**: for `field.field_type in UPLOAD_FIELD_TYPES` render an explicit degraded block
  and emit a `RenderWarning`; never a silent `Input.Text`.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # renderers/teams.py
  UPLOAD_NOTICE_TEXT: dict[str, str] = {"en": "Attachments can't be uploaded from Teams. Open the web form to add files.",
                                        "es": "No se pueden adjuntar archivos desde Teams. Abre el formulario web para agregarlos."}

  class TeamsFormRenderer(AdaptiveCardRenderer):
      def _build_upload_element(self, field: FormField, value: Any, locale: str) -> dict[str, Any] | None:
          """Return a Container: [TextBlock(UPLOAD_NOTICE_TEXT[lang], isSubtle, wrap),
          ActionSet[Action.OpenUrl(title=_resolve(field.label, locale) or 'Open web form', url=<form_url>)]].
          No Input.* element is emitted for the field (no value can be captured in Teams).
          UPLOAD_FIELD_TYPES verified: core/file_envelope.py:44-51."""

      def _upload_warnings(self, form: FormSchema) -> list[RenderWarning]:
          """One RenderWarning(field_id, field_uid, field_type.value, renderer="teams",
          reason="file/image upload unsupported in Teams cards — web form link rendered")
          per upload field, walking sections AND subsections (verified: _build_section_body :595-643)."""
  ```
  `_AC_FALLBACK_TYPES` (adaptive_card.py:95-118) is NOT changed (FILE/IMAGE stay out of it so the
  `adaptive` output/warnings remain identical); the Teams subclass adds its own warnings.

### Module 3: Registration, `setup_form_api` injection, `handle_render` extensions
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` (modify),
  `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` (modify)
- **Responsibility**: register `teams` only when configured; pass the route tenant to renderers
  that accept it; opt-in metadata envelope; map configuration errors to 400.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # api/render.py  (modifies render.py:38-60 and :101-151)
  TEAMS_PUBLIC_URL_ENV: str = "FORMDESIGNER_PUBLIC_URL"

  def register_teams_renderer(*, public_base_url: str | None = None, api_base_path: str = "/api/v1",
                              ui_base_path: str = "", signing_secret: str | None = None,
                              renderer: AbstractFormRenderer | None = None) -> bool:
      """Register ``renderer`` (or a TeamsFormRenderer built from the args / env) under "teams".
      Returns False (and logs INFO) when no public base URL is resolvable — nothing registered."""

  async def handle_render(request: web.Request) -> web.Response:   # verified: render.py:101
      """Unchanged contract plus:
      - kwargs["tenant"] = tenant  when getattr(renderer, "accepts_tenant", False)   (tenant from declared_tenant, :131)
      - ``?with_meta=true`` -> JSON {"content", "content_type", "warnings": [RenderWarning.model_dump()],
        "metadata"} with Content-Type application/json; default path byte-identical to today (:148-151)
      - TeamsRenderConfigError / ValueError from render -> 400 {"error": str(exc)}"""

  # api/routes.py  (modifies setup_form_api signature routes.py:191-212)
  def setup_form_api(app, registry, *, ..., alias_registry=None,
                     public_base_url: str | None = None,
                     teams_renderer: AbstractFormRenderer | None = None) -> None:
      """After _seed_default_renderers(): register_teams_renderer(public_base_url=public_base_url,
      api_base_path=base_path, renderer=teams_renderer). ui_base_path is read from
      app.get("_form_prefix", "") (set by setup_form_ui, verified ui/routes.py:169) when available."""
  ```

### Module 4: Bot receiver branch in `MSTeamsAgentWrapper`
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` (modify),
  `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` (modify),
  `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py` (new — pure helpers, no botbuilder import, so they are unit-testable without the `msteams` extra)
- **Responsibility**: receive the card submit, verify, dedupe, POST legacy JSON, reply.
- **Depends on**: M1 (`TeamsSubmitEnvelope`, `RESERVED_CONTROL_KEYS`).
- **Interface Skeleton**:
  ```python
  # msteams/formdesigner_submit.py  (new; imports only pydantic/aiohttp/stdlib + parrot_formdesigner.renderers.teams)
  class EnvelopeRejected(Exception):
      """User-facing reason why a submission was refused (bad envelope, host not allowed, bad sig, tenant/uid mismatch)."""

  def parse_envelope(submitted_data: dict[str, Any]) -> TeamsSubmitEnvelope:
      """model_validate(submitted_data["_formdesigner"]); raises EnvelopeRejected on ValidationError/missing key."""

  def verify_envelope(env: TeamsSubmitEnvelope, *, allowed_hosts: list[str], secret: str | None,
                      api_base_path: str = "/api/v1") -> None:
      """Order: scheme == https -> host in allowed_hosts (case-insensitive, exact) ->
      urlparse(submit_url).path == f"{api_base_path}/{env.tenant}/forms/{env.form_uid}/data" ->
      (secret is not None) => env.verify(secret) must be True. Raises EnvelopeRejected."""

  def extract_answers(submitted_data: dict[str, Any]) -> dict[str, Any]:
      """{k: v for k, v in submitted_data.items() if k not in RESERVED_CONTROL_KEYS} — raw values, no coercion
      (server-side FormValidator._coerce_value handles Teams strings, verified validators.py:586)."""

  class SubmitOutcome(BaseModel):
      status: int; body: dict[str, Any] | None; error: str | None

  async def post_submission(session: aiohttp.ClientSession, env: TeamsSubmitEnvelope, answers: dict[str, Any], *,
                            bearer_token: str | None, timeout: float, max_response_bytes: int = 1_048_576) -> SubmitOutcome:
      """POST env.submit_url json=answers, allow_redirects=False, ClientTimeout(total=timeout),
      Authorization: Bearer when bearer_token; body read capped; aiohttp/timeout errors -> SubmitOutcome(status=0, error=...)."""

  def build_reply_card(outcome: SubmitOutcome, env: TeamsSubmitEnvelope) -> dict[str, Any]:
      """200 -> confirmation (title, submission_id); 422 -> per-field errors from body["errors"] (dict[str, list[str]]),
      plus body["errors"]["__unknown__"] if present; 401/403 -> 'This form is private and the bot is not authorised';
      404 -> 'Form not found'; 0/5xx -> deterministic 'could not reach FormDesigner' text. Built with parrot.outputs.cards
      (CardSpec/TextSection/render, verified wrapper.py:37-47 imports)."""

  class RecentActivityCache:
      def __init__(self, ttl_seconds: float = 300.0, max_items: int = 2048) -> None: ...
      def seen(self, activity_id: str) -> bool:
          """True if already recorded (duplicate); records otherwise. Best-effort, in-process."""

  # msteams/models.py  (modifies MSTeamsAgentConfig :14-53 and from_dict :114)
  #   + the four fields in §2 Data Models; from_dict reads the same snake_case keys.

  # msteams/wrapper.py
  class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):     # verified: wrapper.py:79
      _formdesigner_session: aiohttp.ClientSession | None            # new attr, init None in __init__ (:106)
      _formdesigner_recent: RecentActivityCache                      # new attr

      async def _handle_card_submission(self, turn_context, dialog_context):   # verified: wrapper.py:359
          """NEW branch inserted after the a2ui_action `return` (:443) and BEFORE `command = submitted_data.get("command")` (:451):
              if ENVELOPE_KEY in submitted_data:
                  await self._handle_formdesigner_submit(turn_context, submitted_data); return"""

      async def _handle_formdesigner_submit(self, turn_context, submitted_data: dict[str, Any]) -> None:
          """parse -> (allowed_hosts empty => send_text('Form submissions are not enabled for this bot'); return)
          -> verify -> dedupe(turn_context.activity.id) -> answers -> post -> self.send_card(build_reply_card(...))
          (send_card verified handler.py:60). Any EnvelopeRejected -> send_text(reason). Never raises; never continues the dialog."""

      async def _get_formdesigner_session(self) -> aiohttp.ClientSession:
          """Lazy shared session (pattern: graph.py:120-128)."""

      async def close_formdesigner_client(self) -> None:
          """Close the shared session (pattern: close_voice_transcriber wrapper.py:976)."""
  ```

### Module 5: Documentation
- **Path**: `docs/formdesigner-msteams-renderer.md` (new); `docs/msteams.md` (modify — one section
  pointing to the new doc); `packages/parrot-formdesigner/README.md` renderer list (modify if the
  list exists).
- **Responsibility**: envelope contract (JSON example, signing), configuration (`FORMDESIGNER_PUBLIC_URL`,
  `setup_form_api` kwargs, bot config fields), the Teams limitations (no uploads, v1.6 ceiling,
  styling ignored), security model (allowlist, sig, bearer), duplicate-submission caveat, and the
  end-to-end walkthrough (render → post card → submit → reply).
- **Depends on**: M1–M4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_adaptive_default_output_golden` | M1 | `AdaptiveCardRenderer().render(sample_form)` JSON equals a committed golden fixture (`tests/unit/fixtures/adaptive_card_golden.json`) — proves byte-identical `adaptive` |
| `test_submit_action_data_default` | M1 | base hook returns `{"_action": "submit"}` for terminal and non-terminal |
| `test_wizard_non_terminal_actions_unchanged` | M1 | `render_section` non-last steps carry no `_formdesigner`; last step does (Teams subclass) |
| `test_teams_envelope_shape` | M1 | envelope keys/types, `form_version` = published_version or version, `submit_url`/`form_url` composition, `is_public` |
| `test_teams_envelope_sign_verify_roundtrip` | M1 | `sign` then `verify` true; tampered field false; `sig=None` false |
| `test_teams_render_requires_tenant_and_base_url` | M1 | `TeamsRenderConfigError` when neither tenant nor `form.tenant`; when no public URL (env unset) |
| `test_teams_render_metadata` | M1 | `RenderedForm.metadata["channel"] == "msteams"`, envelope echoed |
| `test_teams_upload_fields_openurl_and_warning` | M2 | FILE/IMAGE/IMAGE_DROPZONE/MULTI_UPLOAD → no `Input.*`, one `Action.OpenUrl` to `form_url`, one `RenderWarning(renderer="teams")` each — including a field nested in a subsection |
| `test_adaptive_upload_fallback_unchanged` | M2 | default renderer still emits the `Input.Text` filename fallback and no new warnings for FILE/IMAGE |
| `test_register_teams_renderer_noop_without_url` | M3 | env unset + no args → returns False, `"teams" not in supported_formats()` |
| `test_dispatcher_teams_415_when_unregistered` | M3 | `GET …/render/teams` → 415 with `supported` list |
| `test_dispatcher_teams_passes_tenant` | M3 | fake renderer with `accepts_tenant=True` receives `tenant="navigator"`; one without does not get the kwarg |
| `test_dispatcher_with_meta_envelope` | M3 | `?with_meta=true` → JSON `{content, content_type, warnings, metadata}`; default path unchanged |
| `test_dispatcher_render_config_error_400` | M3 | renderer raising `TeamsRenderConfigError` → 400 |
| `test_parse_envelope_rejects_malformed` | M4 | missing key / wrong types → `EnvelopeRejected` |
| `test_verify_envelope_rules` | M4 | http scheme, host not allowed, path/tenant mismatch, path/form_uid mismatch, bad sig (secret set), valid → pass |
| `test_extract_answers_keeps_underscore_field_ids` | M4 | `_department` preserved; `_action`/`_formdesigner` stripped |
| `test_post_submission_outcomes` | M4 | aiohttp test server: 200 body, 422 errors, 403, timeout → status 0; `allow_redirects=False`; bearer header present iff token |
| `test_build_reply_card_mapping` | M4 | each outcome → expected card text |
| `test_recent_activity_cache` | M4 | duplicate `activity.id` within TTL → seen |
| `test_teams_wrapper_routes_formdesigner_submit` | M4 | `_wrapper()` harness (test_a2ui_submit.py:36-62): value with `_formdesigner` → POST helper called once, `send_card` called, `dialog_context.continue_dialog` NOT called (`pytest.importorskip("botbuilder")`) |
| `test_teams_wrapper_formdesigner_disabled_without_allowlist` | M4 | empty allowlist → `send_text` with disabled message, no POST |
| `test_teams_wrapper_formdesigner_returns_before_command_router` | M4 | value with both `_formdesigner` and `command` → command router not called |
| `test_config_from_dict_formdesigner_fields` | M4 | `MSTeamsAgentConfig.from_dict` reads the four new keys with defaults |

### Integration Tests

| Test | Description |
|---|---|
| `test_teams_card_roundtrip_public_form` | aiohttp app with `setup_form_api(..., public_base_url="https://forms.test")` + a public `sample_form`: `GET …/render/teams?with_meta=true` → envelope; feed `{inputs…, _action, _formdesigner}` through `_handle_formdesigner_submit` with the test server as host allowlist → `POST …/data` returns 200 and a submission is stored |
| `test_teams_card_roundtrip_private_form_403_then_bearer` | private form: POST without token → 403 card; with a `token_validator` accepting the configured bearer → 200 |
| `test_teams_card_validation_errors_422` | missing required field → 422 → error card lists the field |

### Test Data / Fixtures

```python
# packages/parrot-formdesigner/tests/unit/conftest.py — reuse `sample_form` (verified conftest.py:51)
@pytest.fixture
def teams_renderer() -> TeamsFormRenderer:
    return TeamsFormRenderer("https://forms.test", api_base_path="/api/v1", ui_base_path="", signing_secret="s3cr3t")

@pytest.fixture
def upload_form(sample_form) -> FormSchema:
    """sample_form + one IMAGE field at top level and one FILE field inside a subsection."""

# packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py — reuse `_wrapper()` / `_turn_context()`
# helpers (copied from test_a2ui_submit.py:36-62) and add `wrapper.config.formdesigner_allowed_hosts = ["forms.test"]`.
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `pytest packages/parrot-formdesigner/tests/unit -v` and `pytest packages/ai-parrot-integrations/tests/msteams -v` pass (botbuilder-dependent tests may `importorskip` locally; they run in CI).
- [ ] `AdaptiveCardRenderer().render(sample_form).content` is byte-identical to the committed golden fixture (G5).
- [ ] `GET …/forms/{uid}/render/teams` returns `application/vnd.microsoft.card.adaptive` JSON whose last action is `Action.Submit` with `data._action == "submit"` and a `data._formdesigner` that validates as `TeamsSubmitEnvelope` (G1, G2).
- [ ] The renderer performs no network I/O (no aiohttp client import in `renderers/teams.py`) (G1).
- [ ] `teams` is absent from `supported_formats()` when no public base URL is configured, and the dispatcher answers 415 (G2).
- [ ] `?with_meta=true` exposes `warnings` and `metadata`; the default response is unchanged.
- [ ] Every upload-type field renders an `Action.OpenUrl` to the web form and a `RenderWarning(renderer="teams")`; no `Input.*` is emitted for it (G4).
- [ ] The bot branch returns before `command` routing and never calls `dialog_context.continue_dialog()` when `_formdesigner` is present (G3).
- [ ] The bot refuses: non-https `submit_url`, host not in `formdesigner_allowed_hosts`, path/tenant/form_uid mismatch, invalid or missing `sig` when a secret is configured; and is disabled with a user message when the allowlist is empty (S3).
- [ ] The POST body equals `activity.value` minus exactly `{"_action", "_formdesigner"}`; values are forwarded raw (S5, S6).
- [ ] Public form → 200 → confirmation card; private form without token → 403 card; with configured bearer → 200 (Q&A auth decision).
- [ ] 422 responses render a per-field error card; network failure renders a deterministic message; duplicate `activity.id` within TTL is not re-posted (S9).
- [ ] One shared `aiohttp.ClientSession` per wrapper, closed by `close_formdesigner_client()`; `allow_redirects=False`; total timeout from config (S10).
- [ ] `MSTeamsAgentConfig.from_dict` accepts the four new keys with backward-compatible defaults.
- [ ] `docs/formdesigner-msteams-renderer.md` exists and `docs/msteams.md` links to it (M5).
- [ ] `ruff check` clean on all touched files; Google-style docstrings and type hints on every new symbol.
- [ ] No change to any legacy status code or payload of `submit_data` / `validate`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor** — verified against `dev` @ `85e38344b` (2026-09-11).

### Verified Imports
```python
# parrot-formdesigner
from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer, _resolve, _FIELD_TYPE_MAPPING, _AC_FALLBACK_TYPES  # adaptive_card.py:121, :45, :70, :95
from parrot_formdesigner.renderers.base import AbstractFormRenderer, FieldRenderer, FallbackRenderer   # base.py:57, :15, :34
from parrot_formdesigner.renderers import AdaptiveCardRenderer, HTML5Renderer, JsonSchemaRenderer     # renderers/__init__.py:14-17 (TelegramRenderer lazy :19-21)
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection, RenderedForm, RenderWarning, SubmitAction  # schema.py:65, :401, :229, :195, :671, :650, :300
from parrot_formdesigner.core.style import StyleSchema                                               # style.py:52
from parrot_formdesigner.core.types import FieldType, LocalizedString                                # types.py:16
from parrot_formdesigner.core.file_envelope import UPLOAD_FIELD_TYPES                                # file_envelope.py:44-51
from parrot_formdesigner.core.options import FieldOption                                             # options.py:14
from parrot_formdesigner.api.render import register_renderer, get_renderer, supported_formats, handle_render, _seed_default_renderers, _coerce_body  # render.py:63, :76, :81, :101, :38, :86
from parrot_formdesigner.api.handlers import extract_form_uid                                        # handlers.py:38 (imported by render.py:27)
from parrot_formdesigner.api.tenant import declared_tenant, enforce_membership_unless_public          # tenant.py:166, :189
from parrot_formdesigner.services.registry import FormRegistry                                       # registry.py:240
from parrot_formdesigner.services.validators import FormValidator                                    # validators.py (class); _coerce_value :586
from parrot.outputs.cards.spec import DEFAULT_ADAPTIVE_CARD_VERSION                                  # spec.py:12 (= config.get("ADAPTIVE_CARD_VERSION") or "1.4"); already imported at adaptive_card.py:23

# ai-parrot-integrations (msteams)
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper                                  # wrapper.py:79 (class MSTeamsAgentWrapper(ActivityHandler, MessageHandler))
from parrot.integrations.msteams.models import MSTeamsAgentConfig                                    # models.py:14
from parrot.integrations.msteams.handler import MessageHandler                                       # handler.py:12 (send_text :35, send_card :60)
from parrot.outputs.cards import CardSpec, TextSection, ActionSubmit, ActionOpenUrl, render, build_attachment, DEFAULT_ADAPTIVE_CARD_VERSION  # cards/__init__.py:8-12, :16, :31-36, :41, :59
from parrot_formdesigner.renderers import AdaptiveCardRenderer                                       # already imported by presets/base.py:13 → integrations depends on parrot-formdesigner (pyproject.toml:55, :174)
import aiohttp                                                                                        # already a dependency (graph.py:116-136 uses aiohttp.ClientSession)
```

### Existing Class Signatures
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py
class AbstractFormRenderer(ABC):                                                        # line 57
    async def render(self, form: FormSchema, style: StyleSchema | None = None, *,
                     locale: str = "en", prefilled: dict[str, Any] | None = None,
                     errors: dict[str, str] | None = None) -> RenderedForm: ...         # lines 68-76 (abstract)

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py
_FIELD_TYPE_MAPPING: dict[FieldType, str]                                               # 70-91 (FILE/IMAGE -> None)
_AC_FALLBACK_TYPES: frozenset[FieldType]                                                # 95-118 (IMAGE_DROPZONE, MULTI_UPLOAD in; FILE, IMAGE out)
class AdaptiveCardRenderer(AbstractFormRenderer):                                       # 121
    SCHEMA_URL = "http://adaptivecards.io/schemas/adaptive-card.json"                   # 142
    DEFAULT_VERSION = DEFAULT_ADAPTIVE_CARD_VERSION                                     # 143
    CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"                            # 144
    def __init__(self, version: str | None = None) -> None                              # 146
    async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None) -> RenderedForm   # 182-273 (actions built :239-244; warnings :249-267 with renderer="adaptive_card" literal :262)
    async def render_section(self, form, section_index, style=None, *, locale="en", prefilled=None, errors=None, show_back=False, show_skip=False) -> RenderedForm  # 275-345
    async def render_summary(self, form, form_data, *, locale="en", summary_text=None) -> RenderedForm       # 347-435
    async def render_error(self, title, errors, *, locale="en", retry_action=True) -> RenderedForm          # 437-492
    def _wrap_card(self, body, actions=None) -> dict[str, Any]                          # 498-520
    def _build_section_body(self, section, prefilled, errors, locale) -> list[dict]     # 595-643 (walks fields + subsections)
    def _build_subsection(self, subsection, prefilled, errors, locale) -> list[dict]    # 645-687
    def _build_field(self, field, prefilled, errors, locale) -> list[dict]              # 689-756
    def _build_input_element(self, field, value, locale) -> dict | None                 # 758-1053 (base {"id": field.field_id, "isRequired": field.required} :774-777; upload branch :1033-1044)
    def _build_choices(self, field, locale) -> list[dict[str, str]]                     # 1055-1077
    def _build_form_actions(self, show_cancel=True, submit_label="Submit", cancel_label="Cancel") -> list[dict]   # 1079-1113 (Submit data {"_action": "submit"} :1096-1101)
    def _build_wizard_actions(self, is_first, is_last, show_back=True, show_cancel=True, show_skip=False, cancel_label="Cancel") -> list[dict]  # 1115-1189 (is_last Submit :1172-1178)

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormField(BaseModel):                                                             # 65
    field_uid: uuid.UUID; field_id: str; field_type: FieldType; label: LocalizedString  # 123-126
    description; placeholder; required: bool = False; default: Any = None               # 127-131
    options: list[FieldOption] | None; options_source; depends_on; post_depends         # 134-137
class SubmitAction(BaseModel):                                                          # 300
    action_type: Literal["tool_call", "endpoint", "event", "callback"]; action_ref: str; method: str = "POST"  # 310-312
class FormSchema(BaseModel):                                                            # 401
    form_uid: uuid.UUID; form_id: str; version: str = "1.0"; title; description; sections: list[FormSection]  # 453-458
    submit: SubmitAction | None = None; cancel_allowed: bool = True                     # 459-460
    tenant: str | None = None                                                           # 463
    published_version: str | None = None                                                # 469
    is_public: bool = False                                                             # 471
class RenderWarning(BaseModel):                                                         # 650
    field_id: str; field_uid: uuid.UUID | None = None; field_type: str; renderer: str; reason: str   # 664-668
class RenderedForm(BaseModel):                                                          # 671
    content: Any; content_type: str; style_output: Any | None = None; metadata: dict[str, Any] | None = None; warnings: list[RenderWarning] = []  # 684-688

# packages/parrot-formdesigner/src/parrot_formdesigner/core/style.py
class StyleSchema(BaseModel):                                                           # 52
    layout: LayoutType = LayoutType.SINGLE_COLUMN; submit_label: LocalizedString = "Submit"; cancel_label: LocalizedString = "Cancel"  # 68, 71, 72

# packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py
_RENDERERS: dict[str, AbstractFormRenderer] = {}                                        # 35
def _seed_default_renderers() -> None                                                   # 38-60 (html, adaptive, xml, pdf, audio via setdefault)
def register_renderer(format_key: str, renderer: AbstractFormRenderer) -> None          # 63-73
def get_renderer(format_key: str) -> AbstractFormRenderer | None                        # 76-78
def supported_formats() -> list[str]                                                    # 81-83
def _coerce_body(content: Any) -> bytes | str                                           # 86-98
async def handle_render(request: web.Request) -> web.Response                           # 101-151 (415 :117-122; registry :124-129; tenant :131-143; locale :145; render call :146; response :148-151)

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
def setup_form_api(app, registry, *, client=None, submission_storage=None, forwarder=None, base_path="/api/v1", blob_storage=None, resolver=None, partial_store=None, synthesizer=None, transcriber=None, token_validator=None, org_graph_service=None, project_service=None, rbac_service=None, workday_adapter=None, venue_service=None, rbac_enforcing=False, alias_registry=None) -> None  # 191-212
# bp = base_path.rstrip("/") :344 ; tp = f"{bp}/{{tenant}}" :352
# GET  {tp}/forms/{form_uid}/render/{format}   :388-392
# POST {tp}/forms/{form_uid}/validate          :394-397
# POST {tp}/forms/{form_uid}/data              :398-401
# POST {tp}/forms/{form_uid}/fields/{field_uid}/file-upload :424-427 ; GET .../thumbnail :430-433

# packages/parrot-formdesigner/src/parrot_formdesigner/ui/routes.py
def setup_form_ui(app, registry, *, base_path: str = "", protect_pages: bool = True) -> None   # 147-151 ; app.setdefault("_form_prefix", base_path.rstrip("/")) :169 ; tp :180
# GET {tp}/forms/{form_uid}  -> page.render_form   :191-193   (the browser form page = upload path)

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
class FormAPIHandler:                                                                   # 109
    async def validate(self, request) -> web.Response                                   # 1003
    async def submit_data(self, request) -> web.Response                                # 1464 (docstring 1465-1497; enforce_membership_unless_public :1519; body = await request.json() :1522-1525; _extract_visit_context :1530)

# packages/parrot-formdesigner/src/parrot_formdesigner/api/tenant.py
def declared_tenant(request: web.Request) -> str                                        # 166
def enforce_membership_unless_public(request, form, tenant) -> None                     # 189 (exempts form.is_public)

# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
class FormValidator: def _coerce_value(self, value: Any, field: FormField) -> Any       # 586 (BOOLEAN: str(value).lower() in ("true","1","yes","on"); NUMBER/INTEGER from str; MULTI_SELECT/TRANSFER_LIST/TAGS: "a,b" -> list)

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):                             # 79
    def __init__(self, ...)                                                             # 106 (self.config = config :117; self.form_orchestrator :148; self.adapter :155)
    def _is_authorized(self, conversation_id: str, user_id: str) -> bool                # 285
    @staticmethod def _decode_a2ui_input_id(encoded: str) -> str                        # 312
    async def _handle_card_submission(self, turn_context, dialog_context)               # 359 (submitted_data = turn_context.activity.value :365; a2ui_token :384-411; a2ui_action :413-443; command :451-455; action = submitted_data.get("_action", "submit") :458; continue_dialog :470; Empty -> "wasn't expecting it" :489-491)
    async def close_voice_transcriber(self) -> None                                     # 976 (lifecycle precedent)
    async def _send_parsed_response(self, parsed, turn_context) -> None                 # 1264
# imports: from aiohttp import web :15 ; from botbuilder.schema import Activity, ActivityTypes, ChannelAccount, Attachment :24 ; from .models import MSTeamsAgentConfig :26 ; from parrot.outputs.cards import (...) :37-47

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/handler.py
class MessageHandler:                                                                   # 12
    async def send_text(self, text: str, turn_context: TurnContext)                     # 35
    async def send_card(self, card_data: Dict[str, Any], turn_context: TurnContext) -> None   # 60

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py
class MSTeamsAgentConfig:  # dataclass-style                                            # 14
    name: str; chatbot_id: str; client_id; client_secret; app_type = "MultiTenant"; app_tenantid; kind = "msteams"  # 29-35
    allowed_conversation_ids: Optional[List[str]] = None; allowed_user_ids: Optional[List[str]] = None  # 43-44
    adaptive_card_version: str = DEFAULT_ADAPTIVE_CARD_VERSION                          # 46
    jira_client_id / jira_client_secret / jira_redirect_uri                              # 51-53 (precedent for feature-scoped optional fields)
    @classmethod def from_dict(cls, name: str, data: Dict[str, Any]) -> 'MSTeamsAgentConfig'   # 114-150

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/graph.py
class GraphClient: self._session: Optional[aiohttp.ClientSession] = None  # 116 ; async def _get_session(self) :120-128 ; async def close(self) :130-136

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/dialogs/presets/base.py
from parrot_formdesigner.renderers import AdaptiveCardRenderer                          # 13
# submitted-value merge drops keys starting with '_'                                    # 160-167
def _get_card_renderer(self) -> AdaptiveCardRenderer: return AdaptiveCardRenderer()     # 174-176

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py  (pattern only)
def _render_Button(self, node, state) -> None   # 608-650: ActionSubmit(title, data={"a2ui_action": ..., "surfaceId": ...}); ActionOpenUrl(title, url)

# tests
packages/parrot-formdesigner/tests/unit/conftest.py: def sample_form() -> FormSchema    # 51
packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py                    # 76-212 (registry + aiohttp_client harness; `_tenant_wrapped_render`)
packages/parrot-formdesigner/tests/unit/test_renderers.py                                # AdaptiveCard tests 357-393, 472-490, 787-823
packages/ai-parrot-integrations/tests/msteams/test_a2ui_submit.py: def _wrapper(...) :36 ; def _turn_context(value) :56 ; pytest.importorskip("botbuilder") :30
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `TeamsFormRenderer.render` | `AdaptiveCardRenderer.render` | `super().render(...)` | `adaptive_card.py:182` |
| `TeamsFormRenderer._submit_action_data` | `_build_form_actions` / `_build_wizard_actions` | new `form=` kwarg + hook call (M1) | `adaptive_card.py:1079, 1115` |
| `TeamsFormRenderer._build_upload_element` | `_build_input_element` upload branch | hook extracted from the `elif ft in UPLOAD_FIELD_TYPES` block | `adaptive_card.py:1033-1044` |
| `register_teams_renderer` | `register_renderer("teams", …)` | function call in `setup_form_api` | `render.py:63`, `routes.py:191` |
| `handle_render` | `TeamsFormRenderer.accepts_tenant` | `getattr(renderer, "accepts_tenant", False)` → `render(..., tenant=tenant)` | `render.py:146` (tenant from `:131`) |
| `_handle_formdesigner_submit` | `_handle_card_submission` | `if ENVELOPE_KEY in submitted_data:` after the `a2ui_action` return | `wrapper.py:443-451` |
| `_handle_formdesigner_submit` | `MessageHandler.send_card` / `send_text` | reply | `handler.py:60`, `:35` |
| `post_submission` | `POST {tp}/forms/{form_uid}/data` | aiohttp, legacy JSON body | `routes.py:398`, `handlers.py:1464` |
| `verify_envelope` | `MSTeamsAgentConfig.formdesigner_*` | config read on `self.config` | `wrapper.py:117`, `models.py:14` |
| `build_envelope.form_url` | web form page | URL only | `ui/routes.py:191-193` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot_formdesigner.renderers.teams`~~ / ~~`TeamsFormRenderer`~~ / ~~`TeamsSubmitEnvelope`~~ — created by this feature (M1).
- ~~`AdaptiveCardRenderer._submit_action_data`~~, ~~`_build_upload_element`~~, ~~`accepts_tenant`~~, ~~`RENDERER_NAME`~~ — created by M1; today the Submit data is a literal at `adaptive_card.py:1096-1101` and the warning renderer name a literal at `:262`.
- ~~`_build_form_actions(..., form=)`~~ / ~~`_build_wizard_actions(..., form=)`~~ — kwargs added by M1; current signatures at `:1079`, `:1115` take no form.
- ~~`handle_render` passing `style`, `prefilled`, `tenant` or query params~~ — today only `locale` (`render.py:145-146`); `tenant=` pass-through and `with_meta` are M3.
- ~~`register_teams_renderer`~~, ~~`setup_form_api(public_base_url=…, teams_renderer=…)`~~, ~~`FORMDESIGNER_PUBLIC_URL`~~ — M3.
- ~~`parrot_formdesigner.api.a2ui_wire`~~ — does not exist (FEAT-544 TASK-3074 creates it); `/data` is legacy-JSON only today.
- ~~`FormSchema.form_version`~~ — the fields are `version: str` (`schema.py:455`) and `published_version: str | None` (`:469`).
- ~~`Input.File`~~, ~~`Action.Http`~~ in Teams Adaptive Cards — no such element/action is supported by Teams; no code references exist.
- ~~`MSTeamsAgentWrapper._handle_formdesigner_submit`~~, ~~`_get_formdesigner_session`~~, ~~`close_formdesigner_client`~~, ~~`_formdesigner_session`~~ — M4. The wrapper has NO `aiohttp.ClientSession`, no `FormRegistry`, no FormDesigner base-URL today.
- ~~`MSTeamsAgentConfig.formdesigner_allowed_hosts` / `formdesigner_submit_token` / `formdesigner_submit_secret` / `formdesigner_submit_timeout`~~ — M4.
- ~~`MSTeamsAgentWrapper.close()`~~ — no generic close; only `close_voice_transcriber` (`wrapper.py:976`).
- ~~`parrot/integrations/msteams/dialogs/card_builder.py`~~ — removed by TASK-524.
- ~~`wrapper.send_text` defined in wrapper.py~~ — it is inherited from `MessageHandler` (`handler.py:35`).
- ~~a web "upload page" separate from the form page~~ — the upload path IS the served form page `GET {ui}/{tenant}/forms/{form_uid}` (`ui/routes.py:191-193`), which drives `POST …/fields/{field_uid}/file-upload`.
- ~~`Teams returns Input.Toggle as bool`~~ — treat as string; server-side `_coerce_value` normalises (`validators.py:586`).
- ~~server-side idempotency key on `/data`~~ — none; dedupe is bot-side (M4).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Envelope-in-`Action.Submit.data` + wrapper branch that unwraps it** — `a2ui_renderers/adaptive_cards.py:608-650` and `wrapper.py:413-443` (TASK-2545). Same insertion style, same "return early, never fall through".
- **Correlation payload in every Submit** — `hitl_cards.py` (`interaction_id`).
- **Table-driven FieldType mapping + explicit degraded set with `RenderWarning`** — `adaptive_card.py:70-118`.
- **Lazy shared aiohttp session + `close()`** — `graph.py:116-136`; lifecycle hook naming after `close_voice_transcriber` (`wrapper.py:976`).
- **Feature-scoped optional config fields with `from_dict` defaults** — Jira OAuth fields `models.py:51-53`, `:146-149`.
- **Dispatcher tests** — `tests/unit/api/test_render_dispatcher.py:76-212` (fake renderer + `aiohttp_client`).
- **Wrapper routing tests without a full bot** — `tests/msteams/test_a2ui_submit.py:36-62` (`__new__` + attribute stubs, `importorskip("botbuilder")`).
- Async-first, Pydantic v2 models, Google docstrings, `self.logger`/`logging.getLogger(__name__)`; `uv` + `source .venv/bin/activate`.

### Known Risks / Gotchas
- **SSRF via `activity.value` (S3)** — never POST to an unverified URL. Verification order is fixed (scheme → allowlist → path/tenant/uid → sig). `allowed_hosts` empty ⇒ feature disabled with a user message, not a silent no-op. `allow_redirects=False`.
- **Byte-identical `adaptive` (G5)** — the golden fixture is the guard. Hook defaults must reproduce the exact dicts (key order included) at `adaptive_card.py:1096-1101`, `:1172-1178`, `:1033-1044`. Teams dialog presets keep working unchanged.
- **Tenant plumbing inside `render`** — the base `render()` calls the builders synchronously; the subclass stores the resolved tenant on the instance for the call's duration. Renderer instances registered in `_RENDERERS` are shared across requests: the value is set at the start of `render` and only read within the same synchronous section (no `await` between set and use), so concurrent renders on one event loop cannot interleave. Document this; do not introduce awaits between the two points.
- **`_RENDERERS` is module-global (S1)** — `register_teams_renderer` overwrites `teams` on every `setup_form_api` call; last configuration wins (logged at INFO by `register_renderer`, `render.py:71-72`). Multi-app processes with different public URLs are out of scope.
- **Teams platform constraints (F020)** — schema ≤ 1.6 (default 1.4), `style: positive/destructive` and `Action.Submit.isEnabled` ignored; images must be public HTTPS ≤ 1024²; card size limits — keep long forms on the web page (`form_url`) and let `RenderedForm.warnings` say so.
- **Teams string values** — toggles arrive as `"true"/"false"`, multi-select as `"a,b"`; forward raw; `_coerce_value` handles them. Do not add a bot-side type map (S5).
- **Underscore field ids (S6)** — strip only `RESERVED_CONTROL_KEYS`. The presets' `startswith('_')` filter is a different code path and stays.
- **Duplicate submissions (S9)** — Teams retries/double taps can POST twice; bot-side TTL dedupe on `activity.id` is best-effort (per process). Document as accepted limitation; server-side idempotency is a follow-up.
- **Private forms** — without `formdesigner_submit_token` the server answers 403 (`enforce_membership_unless_public`, `tenant.py:189`); the reply card says so. How navigator-auth validates a bearer token for a bot identity is configured on the FormDesigner side (`token_validator` kwarg of `setup_form_api`) and is not changed here.
- **`botbuilder` not in the dev venv** — wrapper tests `importorskip`; put all verification/HTTP/reply logic in `formdesigner_submit.py` (no botbuilder import) so it is fully tested locally.
- **`with_meta` and `_coerce_body`** — `with_meta=true` must serialise `RenderWarning` via `model_dump()` and never alter the default `_coerce_body` path.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aiohttp` | already required (`parrot-formdesigner` pyproject:35; integrations via botbuilder/graph) | bot → FormDesigner POST |
| `pydantic` | v2 (already) | `TeamsSubmitEnvelope` |
| `botbuilder-core` / `botbuilder-schema` | already (msteams extra) | `TurnContext`, `activity.value`, `activity.id` |
| stdlib `hmac`, `hashlib`, `urllib.parse` | — | envelope signing / URL verification |

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — one worktree `feat-FEAT-551-msteams-formdesigner-renderer` from `dev`.
- **Order**: M1 → M2 → M3 (renderer side, sequential: M2/M3 depend on M1's hooks and model) → M4 (bot side; depends on M1's `TeamsSubmitEnvelope` import) → M5 (docs).
- **Parallelizable**: M4's pure helpers module (`formdesigner_submit.py`) and its unit tests can be written in parallel with M2/M3 once M1 has landed, because they only import `TeamsSubmitEnvelope`/`RESERVED_CONTROL_KEYS`. Everything else is sequential.
- **Cross-feature dependencies**: none blocking. FEAT-544 (A2UI form renderer, in progress in `feat-FEAT-544-a2ui-form-output-renderer`) touches `api/handlers.py::submit_data` and `api/render.py` (registration of `a2ui`); this spec touches `render.py::handle_render` and `_seed`/`setup_form_api` — expect a small merge in `render.py`. Coordinate merge order; no semantic conflict.

---

## 8. Open Questions

> Carried from the proposal (all five design unknowns were resolved there) plus the spec Q&A.

- [x] **Is the Teams-side receiver in scope?** — *Resolved in proposal*: yes — "ai-parrot-integrations have MS bot framework integration to start a 'bot' used as receptor of Action.Submit buttons, use that approach for answering forms via MS Teams." → M4.
- [x] **How does the bot learn the absolute `POST …/data` URL?** — *Resolved in proposal*: a) absolute `submit_url` in the envelope; the renderer is configured with a public base URL. Tightened by S3: the bot validates the URL (https, allowlist, path/tenant/uid, optional sig) before use.
- [x] **Separate renderer or extend `adaptive`?** — *Resolved in proposal*: a) new subclass + format key `teams`; `adaptive` unchanged (golden-fixture guarded).
- [x] **Posture for image/file fields?** — *Resolved in proposal*: a) `RenderWarning` + `Action.OpenUrl` to the web form page (two-step). S8 pins the target to the existing `GET {ui}/{tenant}/forms/{form_uid}` page.
- [x] **Wire shape the bot POSTs?** — *Resolved in proposal*: a) legacy JSON `{field_id: value}` now, versioned envelope (`v: 1`, `wire: "legacy"`) for a later A2UI variant.
- [x] **Bot authentication for private forms (v1 scope)?** — *Resolved in spec Q&A*: "Public forms + optional bearer" — unauthenticated for `is_public` forms; `Authorization: Bearer <formdesigner_submit_token>` when configured; 401/403 → explicit card message.
- [x] **Teams value coercion rules?** — *Resolved by design research S5 (verified)*: none in the bot; `FormValidator._coerce_value` (`validators.py:586`) already normalises booleans, numbers and comma-separated lists.
- [ ] **Server-side idempotency for `/data`** — *Owner: tbd (follow-up feature)*. v1 ships bot-side best-effort dedupe only (S9).
- [ ] **Bot-side photo intake via chat attachments** — *Owner: tbd (follow-up feature)*. Would let a user attach an image in the Teams chat that the bot uploads to `…/fields/{field_uid}/file-upload`; explicitly out of v1.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted proposal** (never over this spec).
> Model: `gpt-5.6-luna` (codex-cli 0.154.0, reasoning effort high) · Status: **completed** (3 m 44 s)
> · Transcript: `sdd/state/FEAT-551/design_research/` (`brief.md`, `suggestions.json`, `triage.md`, `codex.log`, `run.json`)
> All 16 cited paths passed repository-containment and `test -e`; every factual claim used was re-verified by reading the cited code.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make Teams renderer configuration app-scoped, not module-global (architecture) | CONFIRM | Registration moves into `setup_form_api(public_base_url=…, teams_renderer=…)` with env fallback; unset ⇒ not registered ⇒ 415. Registry refactor itself out of scope. | §2 Overview, §3 M3 |
| S2 | Pass render context explicitly to action builders (api) | CONFIRM | `form=` kwarg + `_submit_action_data(form, terminal=…)` hook; only the terminal Submit gets the envelope. | §3 M1 |
| S3 | Never trust `submit_url` from `activity.value` (risk) | CONFIRM | SSRF guard: https, host allowlist, path/tenant/uid equality, `allow_redirects=False`, optional HMAC `sig`. Tightens (does not overturn) the U2 decision. | §3 M4, §7 |
| S4 | Resolve private-form authentication before implementation (risk) | CONFIRM | Resolved in Q&A: public + optional bearer; 401/403 card; both tested. | §2, §5, §8 |
| S5 | Avoid duplicating value coercion in the Teams wrapper (alternative) | CONFIRM | Verified `_coerce_value` (validators.py:586) handles Teams strings; bot forwards raw values. | §3 M4, §7, §8 |
| S6 | Strip an explicit control-key set, not every underscore key (risk) | CONFIRM | `field_id` has no underscore rule (schema.py:124); strip exactly `{"_action","_formdesigner"}`; regression test. | §3 M4, §4 |
| S7 | Expose or define the warning/metadata transport (api) | CONFIRM | Opt-in `?with_meta=true` JSON envelope; default unchanged. | §3 M3, §4 |
| S8 | Use the existing upload API as the integration target, not an unspecified upload page (alternative) | CONFIRM (modified) | A served form page exists (`ui/routes.py:191-193`); `Action.OpenUrl` targets it; no new page. | §3 M2, §7 |
| S9 | Add replay protection or idempotency (risk) | CONFIRM (best-effort) | Bot-side TTL dedupe on `activity.id`; server-side key deferred and documented. | §3 M4, §7, §8 |
| S10 | One reusable bounded aiohttp submit client with lifecycle ownership (architecture) | CONFIRM | Shared session per `graph.py:116-136`, timeout, 1 MiB cap, `close_formdesigner_client()`. | §3 M4 |
| S11 | Exact default-card compatibility and route-level contract tests (testing) | CONFIRM | Golden fixture, `teams` 415/registration, envelope/meta, nested upload warning, wrapper no-fall-through tests. | §4 |
| S12 | Define version and tenant identity precisely in the envelope (api) | CONFIRM | `form_version: str = published_version or version`; route tenant passed via `accepts_tenant`; bot rejects mismatches. | §3 M1/M3/M4 |

Summary: **12** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-11 | Jesus Lara (via Claude Code) | Initial draft from accepted proposal FEAT-551 (ex provisional FEAT-564) + codex design research |

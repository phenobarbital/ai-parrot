---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot-integrations, parrot-formdesigner, ai-parrot]
tags: [msteams, formdesigner, adaptive-card, mixin, toolkit, tenant]
---

# Feature Specification: Serve FormDesigner forms from a Teams agent (`/getform` mixin + toolkit)

**Feature ID**: FEAT-734
**Date**: 2026-10-23
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.3.0

> **Inputs**: `sdd/proposals/formdesigner-serve-forms.brainstorm.md` (Recommended
> Option A), whose eight resolved questions are carried forward verbatim into this
> spec (§8). Every code reference below was verified at commit `87341f43c`.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-551 (`msteams-formdesigner-renderer`, 7/7 tasks done) built **half** of the
Teams form loop: FormDesigner exports any `FormSchema` as an Adaptive Card
(`GET …/forms/{uid}/render/teams`), the terminal `Action.Submit` carries a signed
`TeamsSubmitEnvelope`, and `MSTeamsAgentWrapper` verifies that envelope and
forwards the answers to `POST …/forms/{uid}/data`.

The agent side of the loop is missing:

1. **Nobody can ask for a form.** There is no `/getform` command and no code path
   that *fetches* a form. The only FormDesigner HTTP traffic the bot makes is the
   submit-only POST at `wrapper.py:1214`; there is no FormDesigner read client
   anywhere in the repository, and no `formdesigner_list_forms` /
   `formdesigner_get_form` tool for an LLM to call.
2. **The card has to be posted by hand.** FEAT-551's documentation ends with
   *"post the returned Adaptive Card JSON to a Teams conversation (however your
   integration delivers proactive/interactive cards)"* — serving the card is left
   to the operator, so every form-serving deployment re-writes wrapper glue.
3. **The submission is not the user's.** The forward is authenticated with one
   process-wide service token (`formdesigner_submit_token`), so every submission
   reaches FormDesigner as the same principal — which FEAT-732's validation audit
   trail would record as the bot rather than the person.

### Goals

- A single composable unit — `class MyAgent(TeamsFormDesignerMixin, Agent)` — that
  gives a Teams-exposed agent: the `/getform` and `/listforms` commands, a
  tenant-scoped picker card, the rendered form card, and the submission path.
- A FormDesigner **read** client (`list_forms`, `get_form`, `render_teams`) over
  `aiohttp`, working against a remote FormDesigner **or** an embedded one.
- A toolkit (`formdesigner_list_forms`, `formdesigner_get_form`) so the LLM reaches
  the same capability without a slash command.
- Submissions authenticated as the **speaking user** (FEAT-729's
  `MSTeamsUserSession.nav_session_token`), with the signed `TeamsSubmitEnvelope`
  retained as defence in depth.
- Multi-section forms served as a card wizard over the existing
  `render_section()`, with per-conversation state.
- Agents **without** the mixin keep FEAT-551's behavior byte-for-byte.

### Non-Goals (explicitly out of scope)

- A service-token interim for the bearer. Rejected in brainstorm Round 1: a
  submission attributed to the bot instead of the person is worse than no feature.
- A channel-agnostic core mixin with per-channel adapters (brainstorm Option C) —
  deferred until a second channel is actually requested.
- Serving forms in channel/group conversations. v1 is 1:1 only, because whose
  bearer authenticates a group submission is unresolved (§8).
- File/image upload inside the card. Teams does not support upload inputs;
  `TeamsFormRenderer` already degrades those fields and this feature only surfaces
  the warnings.
- Reusing the Bot Framework dialog lane (`WizardFormDialog`,
  `FormOrchestrator`) for the wizard — see §2 Overview for why, and §7 Known Risks.
- Implementing FEAT-729 or FEAT-733. Both are prerequisites, not deliverables.

---

## 2. Architectural Design

### Overview

A mixin in `ai-parrot-integrations` owns the whole agent-side loop and the wrapper
asks it first.

**Four contributions, one unit.** `TeamsFormDesignerMixin` contributes (1) the
`/getform` and `/listforms` commands, (2) a `FormDesignerToolkit` through the
agent's `agent_tools()` seam, (3) the picker / login / error / form cards, and (4)
**one** card-submission handler that covers both the picker action and the real
form submission.

**Additive wrapper seams.** At the existing `if ENVELOPE_KEY in
submitted_data:` branch (`wrapper.py:576`) the wrapper asks the agent first via
`handle_formdesigner_card(turn_context, submitted_data) -> bool`; only a `False`
or a missing attribute runs `_handle_formdesigner_submit`. A second hook lets the
agent contribute commands that receive the `TurnContext` — the existing
`config.commands` mechanism cannot be reused, because `_make_custom_handler`
(`agent_commands.py:449`) calls `method(**kwargs)` with text-parsed kwargs and
never passes the `TurnContext`, so a handler registered that way can neither send
a card nor read the Teams identity. Normal agent turns additionally bind a
request-local toolkit context and flush its pending cards (§3 Delivery contracts).
All seams are `getattr`-guarded.

**Dual render.** `mode="remote"` fetches
`GET {base}{api}/{tenant}/forms/{uid}/render/teams?with_meta=true` (with
`section_index=<zero-based index>` for a wizard step) and uses the
envelope the *server* signed. `mode="local"` resolves the form through the
in-process `FormRegistry` and renders with `TeamsFormRenderer`, which the agent
must then configure with `public_base_url` **and** `signing_secret` — FEAT-733's
`require_signature` (default `True`) will refuse an unsigned envelope, so the
secret is a requirement in local mode, not a nicety.

The optional section query is a **new server contract**, implemented by M9 below;
the existing endpoint renders only whole forms. Local registry access requires
M2's host-supplied membership authorizer before any lookup or listing. A tenant
map selects a namespace; it never grants the speaking user membership.

**Tenant precedence is fixed, and only ever maps GUIDs.** FEAT-729's session does
carry a `tenant_id`, but `MSTeamsSessionStore.get_or_create` fills it from
`channel_data["tenant"]["id"]` (`auth.py:159-164`): it is the **same AAD GUID** the
activity asserts, never a FormDesigner tenant slug, and no `set_authenticated`
caller stores one. There is therefore no session *tenant* to rank against the
asserted one. The precedence is:

1. the activity's asserted AAD GUID, mapped through FEAT-733's `formdesigner_tenant_map`;
2. the session's **cached** AAD GUID through that same map — this tier exists only
   to cover an activity that carries no `channel_data.tenant.id`;
3. the bot's static config value, which is already a FormDesigner slug.

The map is the single GUID→slug conversion point, so an unmapped GUID can never
leak into a tenant-scoped URL, and this stays consistent with FEAT-733's
`resolve_submit_tenant` (mapped GUID wins; a miss falls back) — which likewise has
no session tier.

**The wizard is mixin-owned, not dialog-owned.** `WizardFormDialog`
(`dialogs/presets/wizard.py:36`) already walks `FormSchema` sections, but it
renders with a plain `AdaptiveCardRenderer()` (`presets/base.py` `_get_card_renderer`,
per finding F021), merges submitted values while skipping `_`-prefixed keys, and
completes through `FormOrchestrator` — not through `post_submission()`. Routing
this feature through it would contradict the resolved decision that the mixin owns
one handler, and would bypass the envelope entirely. The mixin therefore keeps its
own per-conversation wizard state and calls `TeamsFormRenderer.render_section()`,
which already puts the envelope only on the terminal step's Submit
(`_submit_action_data(..., terminal=True)`, `renderers/teams.py:185`).

**The toolkit reads, the mixin sends.** `formdesigner_get_form` returns metadata
plus a card-pending marker; the mixin sends the card. The tool therefore stays
channel-agnostic, testable without Bot Framework, and never pushes card JSON into
conversation history where FEAT-525 compaction would prune it unpredictably.

### Component Diagram

```
 /getform <slug>            picker Submit               form / section Submit
       │                          │                              │
       ▼                          ▼                              ▼
MSTeamsCommandRouter      _handle_card_submission (wrapper.py:482)
  try_dispatch :74          ① a2ui_token  ② a2ui_action
       │                    ③ NEW agent-first seam ──► handle_formdesigner_card()
       │                    ④ ENVELOPE_KEY :576 (fallback, FEAT-551/733)
       │                    ⑤ command  ⑥ dialogs
       ▼                          │
            TeamsFormDesignerMixin (M4)
                 │
     ┌───────────┼───────────────┬──────────────┬───────────────┐
     ▼           ▼               ▼              ▼               ▼
 identity(M2) client(M1)    cards(M3)      wizard(M5)      toolkit(M6)
 tenant +     list_forms    picker /       section state   list_forms /
 bearer       get_form      login /        per convo       get_form
              render_teams  error cards                    (metadata only)
     │           │
     │           └── mode=remote → GET …/render/teams?with_meta=true  (server signs)
     │               mode=local  → FormRegistry.get()/get_by_slug()
     │                             + TeamsFormRenderer.render()/render_section()
     ▼
 MessageHandler.send_card(card_data, turn_context)   # handler.py:60
     │
     ▼  inbound
 parse_envelope → verify_envelope(..., require_signature) → RecentActivityCache.seen()
 → extract_answers → post_submission(session, env, answers, bearer_token=<user's>)
 → build_reply_card → send_card
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `MSTeamsAgentWrapper._handle_card_submission` | modifies | new agent-first branch immediately before `wrapper.py:576` |
| `MSTeamsAgentWrapper.__init__` (command wiring) | modifies | agent command-contribution hook after `agent_commands.register` (`wrapper.py:191`) |
| `MSTeamsCommandRouter.register()` | uses | `/getform`, `/listforms` registered like any built-in command |
| `MessageHandler.send_card()` | uses | card first, `turn_context` second (`handler.py:60`) |
| `TeamsFormRenderer.render()` / `.render_section()` | uses | local mode; `tenant=` is mandatory |
| `parse_envelope` / `verify_envelope` / `extract_answers` / `post_submission` / `build_reply_card` / `RecentActivityCache` | uses | reused unchanged from `formdesigner_submit.py` |
| `FormRegistry.get()` / `.get_by_slug()` / `.list_forms()` | uses | local mode only |
| `GET {tp}/forms`, `GET …/{uid}`, `…/render/{format}`, `POST …/data` | calls | remote mode; `GET /forms` is `tenant="required"`, so a bearer is mandatory |
| `MSTeamsAgentConfig` | modifies | new `formdesigner_*` read/render fields + `{NAME}_FORMDESIGNER_*` env fallbacks |
| `IntegrationManager.shutdown()` | modifies | add the agent's `aclose()` to the EXISTING per-bot close loop (`manager.py:1067`); the FEAT-551 session is **already** closed there and ledger `a9514c9232ad` is closed (`resolved_by task:TASK-4059`) |
| `Agent.agent_tools()` | extends | toolkit contribution (`agent.py:469`) |
| FEAT-729 `MSTeamsUserSession` / `MSTeamsSessionStore` | **depends on** (landed 2026-10-23) | `nav_session_token` is the bearer; `tenant_id` is an AAD GUID, not a slug; consumed through M2's Protocols |
| FEAT-733 `resolve_submit_tenant` / `formdesigner_tenant_map` / `require_signature` | **depends on** | tenant precedence and mandatory signature |
| `WizardFormDialog` / `FormOrchestrator` | **not used** | deliberately bypassed — see §2 Overview and §7 |

### Data Models

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_client.py (new)
class FormDescriptor(BaseModel):
    """One row of GET {tp}/forms (handlers.py:851) — the picker's choice source."""
    form_uid: uuid.UUID
    form_id: str                      # the slug
    title: str
    description: str | None = None
    version: str | None = None
    source: str | None = None         # "memory" | "db"
    created_at: datetime | None = None

class RenderedCard(BaseModel):
    """?with_meta=true envelope (render.py:215-236), or the local render's equivalent."""
    content: dict[str, Any]
    content_type: str
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)   # carries {"envelope": …}


# packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_identity.py (new)
class TenantResolution(BaseModel):
    """Which tenant won, and why — logged on every fetch."""
    tenant: str
    source: Literal["aad_map", "session_aad_map", "config"]


# packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_wizard.py (new)
@dataclass
class WizardState:
    """One in-flight sectioned form for one conversation."""
    form_uid: uuid.UUID
    tenant: str
    section_index: int
    total_sections: int
    wizard_id: uuid.UUID             # new random ID on every start/restart
    owner_user_id: str               # authenticated Navigator principal
    form_version: str               # reject a changed schema mid-wizard
    answers: dict[str, Any] = field(default_factory=dict)
    updated_at: float = 0.0
```

### New Public Interfaces

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_mixin.py (new)
PICKER_ACTION_KEY: str = "_formdesigner_action"   # NEVER "_formdesigner" — see §7

class TeamsFormDesignerMixin:
    """Serves FormDesigner forms as Adaptive Cards from a Teams-exposed agent."""

    formdesigner_mode: Literal["remote", "local"] = "remote"

    def teams_commands(self) -> dict[str, Callable[["TurnContext"], Awaitable[None]]]:
        """{"getform": …, "listforms": …} — handlers that DO receive the TurnContext."""

    def bind_teams_identity(self, store: "TeamsSessionStoreLike") -> None:
        """Receive the wrapper's single MSTeamsSessionStore (M7 wiring seam).

        The wrapper owns that instance and its process-local cache
        (`wrapper.py:223`), so the mixin must never construct its own: two stores
        over one backing store would diverge. getattr-guarded on the wrapper side.
        """

    async def handle_formdesigner_card(
        self, turn_context: "TurnContext", submitted_data: dict[str, Any]
    ) -> bool:
        """Handle a picker action, a wizard step or a terminal submit.

        Returns True when this mixin fully handled the activity; False to let the
        wrapper fall back to its own FEAT-551 branch.
        """

    def agent_tools(self) -> list["AbstractTool"]:
        """super().agent_tools() + FormDesignerToolkit(...).get_tools()."""

    async def aclose(self) -> None:
        """Close the FormDesigner client session."""
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: FormDesigner read client | yes | endpoints, `FormDescriptor`/`RenderedCard` shapes, `allow_redirects=False`, bounded body, bearer header, lazy session + `close()` | — |
| M2: Tenant + bearer resolution | yes | precedence `aad_map > session_aad_map > config` (both GUID tiers through the one map); `TenantResolution`; Protocol-based session access | — |
| M3: Card builders | yes | picker uses `Input.ChoiceSet` + one Submit carrying `PICKER_ACTION_KEY`; login/error/empty card texts fixed | — |
| M5: Wizard state store | yes | `WizardState` fields, TTL eviction, key `(conversation_id, form_uid)` | — |
| M6: Toolkit | yes | two tools, metadata-only returns, docstrings are the LLM contract | — |
| M4: The mixin | **no** | — | orchestration order (picker vs wizard vs terminal), login/degradation branching, and the toolkit↔card handoff are design calls |
| M7: Wrapper + config seams | **no** | — | shares `wrapper.py` / `models.py` with FEAT-733 and FEAT-729; seam placement relative to branches ③/④ is a design call |
| M8: Tests + docs | partial | unit tests for M1/M2/M3/M5/M6 are mechanical; the round-trip integration test is not | — |
| M9: Server section render | yes | optional section_index query, validation, existing authorization, section metadata and signed terminal envelope | — |

### Module 1: FormDesigner read client
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_client.py` (new)
- **Responsibility**: every FormDesigner **read** over HTTP. Owns one lazily
  created `aiohttp.ClientSession`. Never raises into a Teams handler: failures come
  back as a typed error result.
- **Depends on**: nothing in this spec (`aiohttp`, `parrot_formdesigner.core` models).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_client.py  (new)
  MAX_RESPONSE_BYTES: int = 1_048_576   # mirrors formdesigner_submit.py's bound

  class FormDesignerError(Exception):
      """Read failed: HTTP status, timeout or malformed body. Carries `status`."""

  class FormDesignerClient:
      """Async read client for the FormDesigner REST surface."""

      def __init__(
          self,
          base_url: str,
          *,
          api_base_path: str = "/api/v1",
          timeout: float = 15.0,
          session: aiohttp.ClientSession | None = None,
      ) -> None:
          """`base_url` is the public FormDesigner origin; trailing slashes stripped."""

      async def list_forms(self, *, tenant: str, bearer_token: str | None) -> list[FormDescriptor]:
          """GET {api}/{tenant}/forms -> {"forms": [...]} (handlers.py:851).

          Raises FormDesignerError on a non-200; an empty list is not an error.
          """

      async def get_form(
          self, *, tenant: str, form_uid: uuid.UUID, bearer_token: str | None
      ) -> FormSchema:
          """GET {api}/{tenant}/forms/{form_uid} (routes.py:393)."""

      async def get_form_by_slug(
          self, *, tenant: str, slug: str, bearer_token: str | None
      ) -> FormDescriptor | None:
          """GET {api}/{tenant}/forms?slug=<slug>; None when the filter is empty."""

      async def render_teams(
          self, *, tenant: str, form_uid: uuid.UUID, bearer_token: str | None,
          section_index: int | None = None,
      ) -> RenderedCard:
          """GET {api}/{tenant}/forms/{form_uid}/render/teams?with_meta=true.

          Add section_index only when supplied; requires the M9 server extension.
          Validate returned section_index, total_sections and form_version metadata
          against the requested schema. An old server ignoring the query is an
          error, never a whole-form fallback within a wizard.

          Raises FormDesignerError(status=415) when the server never registered
          the `teams` format (no public base URL configured there).
          """

      async def close(self) -> None:
          """Close the session when this client owns it."""
  ```

### Module 2: Tenant and bearer resolution
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_identity.py` (new)
- **Responsibility**: pure resolution of *which tenant* and *whose bearer*, with no
  Bot Framework or HTTP work, so both are unit-testable with plain data.
- **Depends on**: nothing in this spec. Reads FEAT-729's (landed) session and
  session store through `Protocol`s, so this module stays unit-testable with plain
  fakes and never imports `auth.py`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_identity.py  (new)
  class UserSessionLike(Protocol):
      """The subset of FEAT-729's MSTeamsUserSession (auth.py:45) this feature consumes."""
      authenticated: bool
      nav_session_token: str | None      # the bearer (auth.py:54)
      nav_user_id: str | None            # auth.py:53
      tenant_id: str | None              # AAD GUID (auth.py:51) — NEVER a FormDesigner slug

  class LocalFormAuthorizer(Protocol):
      """Host adapter to the embedded application's authoritative membership policy.

      This is a NEW injection contract, not an existing Navigator API. The host
      must validate the bearer and its principal against its trusted membership
      service, including the same administrator rules as the HTTP API.
      Missing adapter, rejection or lookup failure denies access. Neither the
      AAD map nor client-supplied tenant/session metadata proves membership.
      """
      async def require_membership(
          self, *, tenant: str, bearer_token: str, user_id: str
      ) -> None:
          """Return only for an authorized principal; otherwise raise PermissionError."""

  class TeamsSessionStoreLike(Protocol):
      """The subset of FEAT-729's MSTeamsSessionStore (auth.py:102) this feature consumes.

      `get_or_create` is the ONLY accessor this feature may call: it is read-only and
      never triggers a token exchange — the same pattern `MSTeamsAgentWrapper
      ._effective_user_id` (`wrapper.py:345`) already uses. It never returns None, so
      "no session" means `not session.authenticated` or `is_expired(session)`.

      NEVER call `MSTeamsAuthStrategy.ensure_authenticated()` (auth.py:301): it may
      send a sign-in card as a side effect, pre-empting M3's login card.
      """
      async def get_or_create(self, turn_context: "TurnContext") -> UserSessionLike: ...
      def is_expired(self, session: UserSessionLike) -> bool: ...

  def resolve_form_tenant(
      *,
      asserted_tenant_id: str | None,     # activity.channel_data["tenant"]["id"] (AAD GUID)
      session_tenant_id: str | None,      # session.tenant_id — ALSO an AAD GUID, cached
      tenant_map: dict[str, str] | None,  # FEAT-733 formdesigner_tenant_map: GUID -> slug
      config_tenant: str | None,          # already a FormDesigner slug
  ) -> TenantResolution:
      """Precedence: mapped activity GUID > mapped session GUID > bot config slug.

      BOTH GUID tiers go through `tenant_map` — the only GUID->slug conversion point,
      so an unmapped GUID is never returned as a tenant. The session tier exists only
      to supply the GUID when the activity carries no `channel_data.tenant.id`; it can
      never supply a slug (see §2 and §7).

      Raises TenantUnresolved when no tier yields a slug — never guesses a tenant.
      """

  def resolve_bearer(session: UserSessionLike | None, *, expired: bool = False) -> str | None:
      """session.nav_session_token when authenticated and not `expired`, else None.

      `expired` is the caller's `TeamsSessionStoreLike.is_expired(session)` result,
      passed as a plain bool so M2 keeps no store dependency and stays testable with
      plain data. None -> the login card.
      """
  ```

### Module 3: Card builders
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_cards.py` (new)
- **Responsibility**: every card this feature sends except the form itself: the
  picker, the login prompt, the empty state, the error card, and the
  `RenderWarning` note appended to a form card.
- **Depends on**: M1 (`FormDescriptor`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_cards.py  (new)
  def build_picker_card(
      forms: Sequence[FormDescriptor], *, tenant: str, locale: str = "en",
      version: str = DEFAULT_ADAPTIVE_CARD_VERSION,   # verified: models.py:51
  ) -> dict[str, Any]:
      """Input.ChoiceSet of `forms` + one Submit carrying
      {PICKER_ACTION_KEY: "get_form", "tenant": tenant, "form_uid": <chosen>}.
      """

  def build_login_required_card(*, locale: str = "en") -> dict[str, Any]:
      """Explains that /login is required; fetches nothing."""

  def build_empty_forms_card(*, tenant: str, locale: str = "en") -> dict[str, Any]: ...

  def build_error_card(message: str, *, locale: str = "en") -> dict[str, Any]:
      """Operator-facing reason; never leaks a verification failure reason."""

  def append_render_warnings(
      card: dict[str, Any], warnings: Sequence[dict[str, Any]], *, locale: str = "en"
  ) -> dict[str, Any]:
      """Adds a visible note for upload degradation (UPLOAD_WARNING_REASON)."""
  ```

### Module 4: The mixin
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_mixin.py` (new)
- **Responsibility**: configuration, the two commands, the single card handler, the
  dual render decision, the toolkit contribution, and lifecycle.
- **Depends on**: M1, M2, M3, M5, M6.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_mixin.py  (new)
  PICKER_ACTION_KEY: str = "_formdesigner_action"

  class TeamsFormDesignerMixin:
      """Adds FormDesigner form serving to a Teams-exposed Agent.

      Usage:  class MyAgent(TeamsFormDesignerMixin, Agent)
      """

      def __init__(
          self,
          *args: Any,
          formdesigner_mode: Literal["remote", "local"] = "remote",
          formdesigner_base_url: str | None = None,
          formdesigner_api_base_path: str = "/api/v1",
          formdesigner_public_url: str | None = None,
          formdesigner_signing_secret: str | None = None,
          formdesigner_tenant: str | None = None,
          formdesigner_registry: Any | None = None,       # FormRegistry, local mode
          formdesigner_authorizer: LocalFormAuthorizer | None = None,
          formdesigner_session_store: Any | None = None,  # TeamsSessionStoreLike; TEST seam only —
                                                          #   M7 injects the wrapper's real instance
          **kwargs: Any,
      ) -> None:
          """Cooperative __init__ — forwards *args/**kwargs to the next class in the MRO."""

      def teams_commands(self) -> dict[str, Callable[["TurnContext"], Awaitable[None]]]:
          """{"getform": self.handle_getform, "listforms": self.handle_listforms}."""

      def bind_teams_identity(self, store: "TeamsSessionStoreLike") -> None:
          """Receive the wrapper's single MSTeamsSessionStore instance (M7 seam)."""

      async def handle_getform(self, turn_context: "TurnContext") -> None:
          """`/getform [slug-or-uid]`; with no argument sends the picker."""

      async def handle_listforms(self, turn_context: "TurnContext") -> None:
          """Sends the tenant's picker card (or the empty-state card)."""

      async def handle_formdesigner_card(
          self, turn_context: "TurnContext", submitted_data: dict[str, Any]
      ) -> bool:
          """Route: PICKER_ACTION_KEY -> serve form; wizard step -> next section;
          terminal ENVELOPE_KEY -> verify + post as the user. False = not ours.
          """

      def agent_tools(self) -> list["AbstractTool"]:
          """super().agent_tools() + the FormDesignerToolkit's tools."""

      async def serve_form(
          self, turn_context: "TurnContext", *, form_ref: str | uuid.UUID
      ) -> None:
          """Resolve tenant/bearer, render (remote or local), send the card."""

      async def aclose(self) -> None:
          """Close the FormDesigner client."""
  ```

### Module 5: Section wizard state
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_wizard.py` (new)
- **Responsibility**: in-process, TTL-bounded state for multi-section forms:
  which section a conversation is on and the answers collected so far. Mirrors
  `RecentActivityCache`'s shape (process-local, bounded, best-effort) rather than
  introducing a new persistence dependency.
- **Depends on**: nothing in this spec.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_wizard.py  (new)
  class WizardStore:
      """Process-local wizard state, keyed by (conversation_id, form_uid)."""

      def __init__(self, ttl_seconds: float = 3600.0, max_items: int = 512) -> None: ...

      def start(
          self, *, conversation_id: str, form_uid: uuid.UUID, tenant: str,
          total_sections: int, owner_user_id: str, form_version: str,
      ) -> WizardState: ...

      def get(self, *, conversation_id: str, form_uid: uuid.UUID) -> WizardState | None:
          """None when absent or expired — the caller then restarts the form."""

      def advance(
          self, state: WizardState, answers: dict[str, Any]
      ) -> WizardState:
          """Merge this step's answers and move to the next section."""

      def finish(self, *, conversation_id: str, form_uid: uuid.UUID) -> dict[str, Any]:
          """Pop the state and return the accumulated answers."""
  ```

### Module 6: FormDesigner toolkit
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/tools/formdesigner.py` (new)
- **Responsibility**: the two LLM-callable tools. **Metadata only** — the tools
  never render or send a card; `formdesigner_get_form` returns a marker the mixin
  acts on in the same turn.
- **Depends on**: M1, M2.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/msteams/tools/formdesigner.py  (new)
  class FormDesignerToolkit(AbstractToolkit):   # verified: parrot/tools/toolkit.py:225
      """Lists and resolves FormDesigner forms for the current tenant."""

      def __init__(
          self,
          client: FormReader,
          *,
          tenant_resolver: Callable[[], str | None],
          bearer_resolver: Callable[[], str | None],
          enqueue_card: Callable[[uuid.UUID], None],
          **kwargs: Any,
      ) -> None:
          """Resolvers and enqueue callback use M4's request-local turn context.

          Missing/closed context returns a structured unavailable result without
          HTTP, registry access or card_pending=true. Successful get_form enqueues
          its resolved UID before returning metadata; no model-output parsing.
          """

      async def formdesigner_list_forms(self) -> dict[str, Any]:
          """List the forms available in the caller's tenant.

          Returns {"tenant": str, "forms": [{"form_uid", "form_id", "title",
          "description"}]}. Use it to find a form before asking for it by slug.
          """

      async def formdesigner_get_form(self, form: str) -> dict[str, Any]:
          """Resolve ONE form by slug or form_uid and queue its card for sending.

          `form` is a slug (e.g. "store-visit") or a form_uid. Returns
          {"form_uid", "form_id", "title", "sections", "field_count",
          "card_pending": true}; the Adaptive Card is sent by the channel, so do
          not describe the form's fields back to the user.
          """
  ```

### Module 7: Wrapper, config and shutdown seams
- **Path**: `…/msteams/wrapper.py`, `…/msteams/models.py`, `…/integrations/manager.py` (all MODIFY)
- **Responsibility**: command/card hooks, identity injection, the normal-turn
  context and flush seam specified below, the new config fields with their
  `{NAME}_FORMDESIGNER_*` env fallbacks, and closing the client on shutdown.
- **Depends on**: M4.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:576
  # (new branch immediately BEFORE the existing `if ENVELOPE_KEY in submitted_data:`)
  handler = getattr(self.agent, "handle_formdesigner_card", None)
  if handler is not None and (ENVELOPE_KEY in submitted_data or PICKER_ACTION_KEY in submitted_data):
      if await handler(turn_context, submitted_data):
          return
  # falls through to the FEAT-551/733 branch unchanged

  # modifies packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:191
  # (after `agent_cmd_handler.register(self._command_router)`)
  def _register_agent_commands(self) -> None:
      """Register TurnContext-carrying commands the agent contributes via
      `teams_commands()`; silently skipped for an agent without it.
      """

  # modifies packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py:66
  @dataclass
  class MSTeamsAgentConfig:
      formdesigner_mode: str = "remote"                      # NEW — "remote" | "local"
      formdesigner_base_url: Optional[str] = None            # NEW — read/render origin
      formdesigner_tenant: Optional[str] = None              # NEW — last-resort tenant
      formdesigner_public_url: Optional[str] = None          # NEW — local-mode envelope URLs
      formdesigner_render_timeout: float = 15.0              # NEW
      # env fallbacks resolved in __post_init__ beside models.py:101, same
      # {NAME}_FORMDESIGNER_* convention as the FEAT-551 fields.

  # modifies packages/ai-parrot-integrations/src/parrot/integrations/manager.py:1067
  async def shutdown(self) -> None:
      """Add `await agent.aclose()` to the EXISTING per-bot close loop.

      That loop already awaits wrapper.close_formdesigner_client() and
      close_voice_transcriber(), each in its own try (manager.py:1067), and
      ledger a9514c9232ad is closed (resolved_by task:TASK-4059). So this
      feature adds ONLY the agent's own aclose() beside them, still before
      msteams_bots.clear() (manager.py:1139). Do not re-fix the FEAT-551 leak.
      """
  ```

### Module 8: Tests and documentation
- **Path**: `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_serve.py`,
  `…/tests/msteams/test_formdesigner_mixin_roundtrip.py`,
  `…/tests/integrations/msteams/test_msteams_models.py` (MODIFY),
  `docs/formdesigner-serve-forms.md` (new)
- **Responsibility**: §4's tests plus the operator-facing guide (config matrix,
  the two modes, the FEAT-729/733 prerequisites).
- **Depends on**: M1–M7 and M9.
- **Interface Skeleton**: n/a (tests and prose).

---

### Module 9: Remote section render dispatcher

- **Paths (MODIFY)**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py`,
  `packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py`.
- **Depends on**: existing `TeamsFormRenderer.render_section`; M1 consumes this
  wire contract. No new route or renderer public method is needed.
- `GET …/render/teams?with_meta=true&section_index=N` runs the same form lookup,
  authentication and `enforce_membership_unless_public` check as whole-form rendering,
  then calls `render_section(form, N, locale=locale, tenant=tenant)` with Back and
  Skip disabled. Parse an integer and reject negative, malformed or out-of-range
  values with HTTP 400. A section query for another format also returns 400.
- With the query absent, preserve existing output and behavior. For a section,
  add `section_index`, `total_sections`, and `form_version` to response metadata;
  preserve renderer warnings and all existing metadata. The terminal action must
  contain the server-signed envelope; intermediate actions must not contain it.
  Server tests verify signature, section isolation, authorization, query errors,
  and unchanged whole-form rendering. M1 requires matching section metadata so an
  older server that ignores the query cannot silently masquerade as a section server.

### Delivery contracts (M2–M7)

**Wizard routing and state.** M4 decorates every wizard `Action.Submit`, including
Cancel and terminal Submit, after remote or local rendering. Add a single control
object under `PICKER_ACTION_KEY`:

```json
{"_formdesigner_action": {"kind": "wizard", "action": "next", "form_uid": "<uuid>", "wizard_id": "<uuid>", "section_index": 0}}
```

`action` is `next`, `cancel`, or `submit`; Back and Skip are disabled in v1.
The original `_action` and signed terminal `_formdesigner` object remain unchanged.
Picker actions keep their existing string value `get_form`; the handler distinguishes
that string from the wizard object. Consequently the existing proposed wrapper
condition catches every wizard action, including intermediate Next, without
intercepting generic dialog `_action` traffic.

State remains keyed by `(conversation_id, form_uid)` within the owning mixin.
Every start generates a new `wizard_id` and records tenant, authenticated user,
schema version and current index. Before merging answers or posting, compare the
control object with that state and re-resolve the current authenticated identity.
Reject mismatched owner, tenant, wizard ID, index, action or form version; never
trust the submitted tenant. Use a per-state async lock for validate/advance/post
and check activity deduplication inside it, so concurrent deliveries cannot skip
sections or post twice. Repeated clicks from an older index are stale even when
their activity IDs differ. Expired/missing state produces a restart instruction,
never a partial POST or fallback to the legacy submission handler.

Only accept answer IDs belonging to the current schema section. Remove the entire
`PICKER_ACTION_KEY` control object before `extract_answers`; that existing helper
does not reserve the new key. Verify the terminal envelope and match its tenant,
form UID and version to state before combining earlier answers. Mark the terminal
state consumed before the one POST; remove it after the outcome is handled.
Cancel removes state without posting. All recognized wizard actions, including
invalid ones, return True and cannot fall through to the service-token lane.

**Normal-turn toolkit lifecycle.** M4 provides these NEW public hooks:

```python
def formdesigner_turn(self, turn_context: "TurnContext") -> AsyncContextManager[None]:
    """Bind a fresh request-local identity and pending UID queue; always clean up."""

async def flush_formdesigner_cards(self, turn_context: "TurnContext") -> None:
    """Drain this turn's distinct queued UIDs through serve_form, in request order."""
```

M7 wraps every wrapper-owned `form_orchestrator.process_message` entry that can
invoke tools (ordinary text, transcribed voice and card-to-agent continuations)
in `formdesigner_turn`, using `getattr` guards. Bind the wrapper's shared session
store first; entering reads it, checks expiry and resolves tenant/bearer. A
`ContextVar` holds a fresh per-turn object; its queue is shared with awaited tool
tasks but never with another turn. Tools expose no tenant/bearer arguments to the
LLM. Enqueue is a callback, not inference from final model text or tool history.
Deduplicate queued UIDs in first-request order.

After a successful process_message result, flush before sending the normal model
response and before leaving the context. On an error result, exception or
cancellation, discard the queue. In all cases mark the context closed, clear its
bearer and queue, and reset the ContextVar token in finally. Detached late tool
tasks see a closed context and cannot enqueue. Flush rechecks session expiry and
authorization via serve_form; failed delivery returns an error/login card and
does not leak queued cards into the next turn. Tools called without a usable
context fail closed with a structured unavailable/login-required result and no
reads. Normal chat without a form tool still follows the ordinary response path.

**Local authorization and toolkit parity.** In local mode, M4 requires
`formdesigner_authorizer` before any registry read, including listing, slug
resolution and toolkit metadata lookup. Call `require_membership` with the
current bearer, Navigator user ID and resolved tenant on every operation, and
again for each wizard step. No adapter or failed authorization yields an access
error card/result and zero registry calls. This local mode deliberately requires
membership even for public forms; deployments needing anonymous/public reads
use the remote API, subject to this feature's authenticated-session requirement.
This conservative rule permits authorization before revealing even existence or
schema metadata. The host adapter is a constructor injection, never a YAML
callable or an inferred claim from the AAD GUID mapping.

M6's `client` accepts a structural `FormReader` protocol defined in M1 with
`list_forms`, `get_form`, and `get_form_by_slug` matching the HTTP client's
signatures. M4 supplies either that HTTP client or a local adapter invoking the
authorizer before the registry; both use the same request-local identity. The
toolkit therefore cannot bypass local authorization or require an HTTP server
in embedded mode. These are new contracts to implement, not existing symbols.

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_client_list_forms_parses_descriptors` | M1 | `{"forms": [...]}` → `FormDescriptor`s; empty list is not an error |
| `test_client_list_forms_sends_bearer` | M1 | `Authorization: Bearer …` present when a token is given, absent when `None` |
| `test_client_render_teams_with_meta` | M1 | `?with_meta=true` envelope → `RenderedCard` incl. `metadata["envelope"]` |
| `test_client_render_teams_415_raises` | M1 | server without the `teams` format → `FormDesignerError(status=415)` |
| `test_client_no_redirects_and_bounded_body` | M1 | `allow_redirects=False`; an oversized body is refused |
| `test_tenant_precedence_aad_map_wins` | M2 | mapped activity GUID beats a differently-mapped session GUID |
| `test_tenant_precedence_session_guid_when_activity_absent` | M2 | no activity GUID → mapped session GUID, `source="session_aad_map"` |
| `test_tenant_precedence_unmapped_guid_never_leaks` | M2 | both GUIDs unmapped → config slug; the raw GUID is never returned as a tenant |
| `test_tenant_precedence_config_last` | M2 | no GUID at all → config, `source="config"` |
| `test_tenant_unresolved_raises` | M2 | no tier yields a slug → `TenantUnresolved` |
| `test_resolve_bearer_requires_authenticated` | M2 | `authenticated=False` → `None` |
| `test_resolve_bearer_rejects_expired` | M2 | `expired=True` → `None` even when `authenticated` |
| `test_mixin_never_calls_ensure_authenticated` | M4 | a store fake asserts only `get_or_create`/`is_expired` are used |
| `test_picker_card_choiceset_and_action_key` | M3 | one `Input.ChoiceSet`, one Submit, `PICKER_ACTION_KEY` present, `ENVELOPE_KEY` absent |
| `test_login_and_empty_cards` | M3 | login/empty-state cards render with no network call |
| `test_append_render_warnings_adds_note` | M3 | upload warning becomes a visible note |
| `test_wizard_advance_accumulates_answers` | M5 | answers merge across sections; index advances |
| `test_wizard_expiry_returns_none` | M5 | past TTL → `get()` is `None` |
| `test_wizard_eviction_bounded` | M5 | `max_items` respected |
| `test_toolkit_get_form_returns_metadata_not_card` | M6 | result has `card_pending`, carries no Adaptive Card JSON |
| `test_toolkit_list_forms_scoped_to_tenant` | M6 | the tenant resolver's value is the one queried |
| `test_config_env_fallbacks` | M7 | `{NAME}_FORMDESIGNER_BASE_URL` / `_TENANT` / `_MODE` resolve in `__post_init__` |

### Integration Tests

| Test | Description |
|---|---|
| `test_getform_slug_sends_card_remote` | `/getform store-visit` in remote mode → one `send_card` with the server-signed envelope |
| `test_getform_no_arg_sends_picker` | `/getform` with no argument → picker card for the resolved tenant |
| `test_picker_submit_serves_form` | picker Submit (`PICKER_ACTION_KEY`) → the chosen form's card |
| `test_local_mode_renders_with_teams_renderer` | local mode + `FormRegistry` → card whose envelope is signed with the agent's secret |
| `test_local_mode_without_secret_refuses` | local mode, no `signing_secret` → error card, no unsigned card sent |
| `test_wizard_walks_sections_then_submits` | multi-section form: each step advances; only the terminal Submit posts |
| `test_submit_uses_user_bearer_not_service_token` | the POST carries the session's `nav_session_token`, never `formdesigner_submit_token` |
| `test_no_session_sends_login_card_and_fetches_nothing` | unauthenticated → login card; the client makes zero requests |
| `test_duplicate_activity_not_double_posted` | same `activity.id` twice → one POST |
| `test_wrapper_falls_back_without_mixin` | agent without the mixin → `_handle_formdesigner_submit` runs exactly as in FEAT-551 |
| `test_mixin_declines_unknown_envelope_falls_back` | handler returning `False` → the FEAT-551 branch still runs |
| `test_shutdown_closes_client_sessions` | `IntegrationManager.shutdown()` leaves no unclosed session |
| `test_wizard_generated_actions_route_to_mixin` | Parameterize local/remote rendering; feed actual Next/Cancel/Submit payloads through the wrapper; only terminal submits and no control object reaches POST |
| `test_remote_wizard_section_contract` | Walk three sections via the real HTTP dispatcher; each card contains only that section; verify terminal server signature and accumulated answers |
| `test_remote_wizard_rejects_old_server` | Missing/mismatched section metadata is an error, not a whole-form card |
| `test_wizard_rejects_stale_foreign_and_concurrent_actions` | Wrong owner/tenant/wizard/index/version, expired state, duplicate delivery and concurrent Next/Submit never advance twice or post partial data |
| `test_toolkit_normal_chat_delivers_card` | Natural-language tool invocation without prior slash command queues and sends exactly one card; model history contains metadata only |
| `test_toolkit_turn_isolation_and_cleanup` | Concurrent users have separate bearer/tenant/queues; repeated UID deduplicates; error/cancellation and late tasks cannot leak cards or credentials |
| `test_toolkit_voice_and_card_continuations` | All wrapper process_message entries bind/flush context; no-mixin behavior is unchanged |
| `test_local_membership_denied_before_registry` | Authenticated nonmember of mapped/config tenant, absent authorizer and authority outage all deny before any registry call, including toolkit and wizard paths |
| `test_local_membership_authorized` | Authorized user can list/resolve/render through commands and tools; local public forms also require membership |

### Validation Contract

tests:
- packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py
- packages/ai-parrot-integrations/tests/msteams/test_formdesigner_serve.py
- packages/ai-parrot-integrations/tests/msteams/test_formdesigner_client.py
- packages/ai-parrot-integrations/tests/msteams/test_formdesigner_identity.py
- packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wizard.py
- packages/ai-parrot-integrations/tests/msteams/test_formdesigner_turn.py
- packages/ai-parrot-integrations/tests/msteams/test_formdesigner_cards.py
- packages/ai-parrot-integrations/tests/msteams/test_formdesigner_toolkit.py
- packages/ai-parrot-integrations/tests/msteams/test_formdesigner_local.py
- packages/ai-parrot-integrations/tests/msteams/test_formdesigner_mixin_roundtrip.py
- packages/ai-parrot-integrations/tests/msteams/test_formdesigner_roundtrip.py
- packages/ai-parrot-integrations/tests/msteams/test_formdesigner_wrapper.py
- packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_models.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_manager_shutdown.py
markers: none

### Test Data / Fixtures

```python
# packages/ai-parrot-integrations/tests/msteams/conftest.py (extend)
@pytest.fixture
def fake_session():
    """Stands in for FEAT-729's MSTeamsUserSession (UserSessionLike Protocol).

    `tenant_id` is an AAD GUID, exactly as MSTeamsSessionStore fills it (auth.py:159-164).
    """
    return SimpleNamespace(
        authenticated=True, nav_session_token="nav-tok", nav_user_id="u1",
        tenant_id="11111111-2222-3333-4444-555555555555",
    )

@pytest.fixture
def fake_session_store(fake_session):
    """Stands in for MSTeamsSessionStore (TeamsSessionStoreLike Protocol).

    Records every attribute touched so a test can assert `ensure_authenticated`
    was never called.
    """

@pytest.fixture
def teams_activity_value():
    """Factory for an Action.Submit activity.value, with channel_data.tenant.id."""

@pytest.fixture
def sectioned_form():
    """A FormSchema with 3 sections and one upload field, for wizard + degradation."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `class MyAgent(TeamsFormDesignerMixin, Agent)` yields a working `/getform`
      and `/listforms` with no wrapper edits in the consuming project.
- [ ] `/getform <slug>` and `/getform <form_uid>` both serve the right form; a slug
      that matches nothing produces a "no form found" card, not an error.
- [ ] `/getform` with no argument and `/listforms` both send the picker card, whose
      Submit serves the selected form.
- [ ] Remote mode uses the server-signed envelope from
      `GET …/render/teams?with_meta=true`; local mode signs with the agent's
      `signing_secret` and refuses to send an unsigned card.
- [ ] Every submission POSTs with the authenticated user's bearer; no code path
      substitutes `formdesigner_submit_token` as a fallback.
- [ ] Tenant precedence is exactly `mapped activity GUID > mapped session GUID >
      bot config slug`, with the winning source logged; an unmapped AAD GUID is
      never used as a tenant slug; no tier yielding a slug → error card.
- [ ] No authenticated session → login card, and the FormDesigner client issues
      zero requests.
- [ ] Multi-section forms walk section by section; only the terminal Submit posts
      answers, and the accumulated answers of earlier sections are included.
- [ ] Actual renderer-produced wizard actions reach the mixin with validated
      state identity; stale, foreign, expired and concurrent actions cannot skip
      sections or leak controls into submitted answers.
- [ ] Remote section rendering implements M9's query/metadata contract and keeps
      terminal server signatures intact; old servers fail explicitly.
- [ ] Local commands, tools and wizard steps authorize membership before registry
      access; missing/failed authorization denies without revealing form metadata.
- [ ] Upload fields keep `TeamsFormRenderer`'s notice + `Action.OpenUrl` behavior,
      and their `RenderWarning`s are visible in the card.
- [ ] `formdesigner_get_form` returns metadata with `card_pending` and never
      Adaptive Card JSON; the card is sent by the mixin.
- [ ] Normal text, voice and card continuations bind isolated toolkit contexts,
      flush queued cards on success, and clear state on every exit; no previous
      slash command or model-output marker parsing is required.
- [ ] An agent **without** the mixin behaves exactly as FEAT-551 does today
      (`test_formdesigner_roundtrip.py` unchanged and passing).
- [ ] A duplicate `activity.id` delivery posts once.
- [ ] `IntegrationManager.shutdown()` also closes the mixin's own client; the
      FEAT-551 session is already closed in that same loop (`manager.py:1067`).
- [ ] Every test in §4's Validation Contract passes with
      `PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src:packages/parrot-formdesigner/src`.
- [ ] `ruff check` clean on every touched file; no `requests`/`httpx` import.
- [ ] `docs/formdesigner-serve-forms.md` documents both modes, the config matrix and
      the FEAT-729/FEAT-733 prerequisites.
- [ ] No breaking change to `MSTeamsAgentConfig` (every new field has a default) or
      to any FEAT-551 public name.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified at commit `87341f43c`. Implementation agents MUST NOT reference imports,
> attributes or methods not listed here without verifying them first.

### Verified Imports

```python
from parrot_formdesigner.renderers.teams import (        # verified: wrapper.py:38 imports ENVELOPE_KEY from here
    ENVELOPE_KEY,                                        # renderers/teams.py:36
    TeamsFormRenderer,                                   # renderers/teams.py:88
    TeamsRenderConfigError,                              # renderers/teams.py:84
    TeamsSubmitEnvelope,                                 # renderers/teams.py:52
)
from .formdesigner_submit import (                       # verified: wrapper.py:29-37
    EnvelopeRejected,                                    # formdesigner_submit.py:28
    RecentActivityCache,                                 # formdesigner_submit.py:201
    build_reply_card,                                    # formdesigner_submit.py:122
    extract_answers,                                     # formdesigner_submit.py:60
    parse_envelope,                                      # formdesigner_submit.py:32
    post_submission,                                     # formdesigner_submit.py:73
    verify_envelope,                                     # formdesigner_submit.py:44
)
from .commands import MSTeamsCommandRouter               # verified: wrapper.py:44
from .models import MSTeamsAgentConfig                   # verified: wrapper.py:28
from parrot.forms import FormSchema                      # verified: wrapper.py:51 (shim → parrot_formdesigner.core)
from parrot.tools.toolkit import AbstractToolkit         # verified: parrot/tools/toolkit.py:225
from parrot_formdesigner.services.registry import FormRegistry   # verified: services/registry.py:240
from .auth import (                                      # verified: FEAT-729, landed 2026-10-23
    MSTeamsSessionStore,                                 # auth.py:102
    MSTeamsUserSession,                                  # auth.py:45
)
#   M2 must NOT import these — it consumes them structurally through its own
#   Protocols. Only M7 (wiring) and the tests may reference the concrete names.
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py
ENVELOPE_KEY: str = "_formdesigner"                                      # line 36
RESERVED_CONTROL_KEYS: frozenset[str] = frozenset({"_action", ENVELOPE_KEY})  # line 37
PUBLIC_URL_ENV: str = "FORMDESIGNER_PUBLIC_URL"                          # line 38
UPLOAD_WARNING_REASON: str                                               # line ~45

class TeamsSubmitEnvelope(BaseModel):                                    # line 52
    v: Literal[1] = 1
    wire: Literal["legacy"] = "legacy"
    form_uid: uuid.UUID
    tenant: str = Field(min_length=1)
    form_version: str
    is_public: bool
    submit_url: HttpUrl
    form_url: HttpUrl
    sig: str | None = None
    def canonical_payload(self) -> bytes: ...                            # line 65
    def sign(self, secret: str) -> "TeamsSubmitEnvelope": ...            # line 71
    def verify(self, secret: str) -> bool: ...                           # line 76

class TeamsRenderConfigError(ValueError): ...                            # line 84

class TeamsFormRenderer(AdaptiveCardRenderer):                           # line 88
    RENDERER_NAME = "teams"                                              # line 91
    accepts_tenant = True                                                # line 92
    def __init__(                                                        # line 94
        self, public_base_url: str | None = None, *, api_base_path: str = "/api/v1",
        ui_base_path: str = "", signing_secret: str | None = None,
        version: str | None = None,
    ) -> None: ...
    def build_envelope(self, form: FormSchema, tenant: str) -> TeamsSubmitEnvelope: ...  # line 112
    async def render(                                                    # line 126
        self, form: FormSchema, style: StyleSchema | None = None, *, locale: str = "en",
        prefilled: dict[str, Any] | None = None, errors: dict[str, str] | None = None,
        tenant: str | None = None,
    ) -> RenderedForm: ...
    async def render_section(                                            # line 150
        self, form: FormSchema, section_index: int, style: StyleSchema | None = None, *,
        locale: str = "en", prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None, show_back: bool = False,
        show_skip: bool = False, tenant: str | None = None,
    ) -> RenderedForm: ...
    def _submit_action_data(self, form: FormSchema | None, *, terminal: bool) -> dict[str, Any]: ...  # line 185
```

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py
class EnvelopeRejected(Exception): ...                                   # line 28
def parse_envelope(submitted_data: dict[str, Any]) -> TeamsSubmitEnvelope: ...   # line 32
def verify_envelope(                                                     # line 44
    env: TeamsSubmitEnvelope, *, allowed_hosts: list[str], secret: str | None,
    api_base_path: str = "/api/v1",
) -> None: ...
#   FEAT-733 TASK-4654 adds `require_signature: bool = True` to this signature.
def extract_answers(submitted_data: dict[str, Any]) -> dict[str, Any]: ...  # line 60
class SubmitOutcome(BaseModel):                                          # line 65
    status: int; body: dict[str, Any] | None = None; error: str | None = None
async def post_submission(                                               # line 73
    session: aiohttp.ClientSession, env: TeamsSubmitEnvelope, answers: dict[str, Any], *,
    bearer_token: str | None, timeout: float, max_response_bytes: int = MAX_RESPONSE_BYTES,
) -> SubmitOutcome: ...
def build_reply_card(outcome: SubmitOutcome, env: TeamsSubmitEnvelope) -> dict[str, Any]: ...  # line 122
class RecentActivityCache:                                               # line 201
    def __init__(self, ttl_seconds: float = 300.0, max_items: int = 2048) -> None: ...  # line 204
    def seen(self, activity_id: str) -> bool: ...                        # line 209
```

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py  (FEAT-729, LANDED 2026-10-23)
@dataclass
class MSTeamsUserSession:                                                # line 45
    user_key: str                                                        # line 48
    teams_user_id: str                                                   # line 49
    aad_object_id: Optional[str] = None                                  # line 50
    tenant_id: Optional[str] = None       # AAD tenant GUID — NOT a FormDesigner slug  # line 51
    display_name: Optional[str] = None                                   # line 52
    nav_user_id: Optional[str] = None                                    # line 53
    nav_session_token: Optional[str] = None   # the bearer this feature sends  # line 54
    nav_email: Optional[str] = None                                      # line 55
    authenticated: bool = False                                          # line 56
    authenticated_at: Optional[datetime] = None
    external_expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)   # free-form; holds NO tenant slug
    @property
    def user_id(self) -> str: ...                                        # line 65
    def set_authenticated(self, nav_user_id, session_token, display_name=None,
                          email=None, external_expires_at=None, **extra_meta) -> None: ...  # line 71

class MSTeamsSessionStore:                                               # line 102
    def is_expired(self, session: MSTeamsUserSession) -> bool: ...       # line 130
    async def get_or_create(self, turn_context: TurnContext) -> MSTeamsUserSession: ...  # line 134
    #   read-only, never exchanges; fills tenant_id from channel_data["tenant"]["id"]  # lines 159-164
    async def save(self, session: MSTeamsUserSession) -> None: ...       # line 170

class MSTeamsAuthStrategy:                                               # line 256
    async def ensure_authenticated(self, turn_context) -> MSTeamsUserSession: ...  # line 301
    #   SIDE EFFECT: may send a sign-in card. This feature must NOT call it.

#   The wrapper owns the single instances M7 injects:
#     self._session_store = MSTeamsSessionStore(...)                     # wrapper.py:223
#     self._auth = MSTeamsAuthStrategy(..., store=self._session_store)   # wrapper.py:229
#   read-only session-read precedent: _effective_user_id()               # wrapper.py:345
```

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py
class MSTeamsCommandRouter:                                              # line 30
    def register(self, command: str, handler: Callable) -> None: ...     # line 56
    async def try_dispatch(self, text: str, turn_context: "TurnContext") -> bool: ...  # line 74
    def registered_commands(self) -> list[str]: ...                      # line 153

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/agent_commands.py
class AgentCommandHandler:                                               # line 26
    def __init__(self, agent: Any, wrapper: Any) -> None: ...            # line 43
    def register(self, router: "MSTeamsCommandRouter") -> None: ...      # line 48
    def _register_custom_commands(self, router: "MSTeamsCommandRouter") -> None: ...  # line 449
    #   its closure calls `method(**kwargs)` — NO TurnContext is passed (see §2)

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/handler.py
async def send_card(                                                     # line 60
    self, card_data: Dict[str, Any], turn_context: TurnContext,
) -> None: ...                                                           # card FIRST, context SECOND
```

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):              # line 98
    self._formdesigner_session: Optional[aiohttp.ClientSession] = None   # line 172
    self._formdesigner_recent = RecentActivityCache()                    # line 173
    self._command_router: MSTeamsCommandRouter = MSTeamsCommandRouter()  # line 189
    agent_cmd_handler.register(self._command_router)                     # line 191
    self._session_store = MSTeamsSessionStore(...)                       # line 223 (FEAT-729)
    self._auth = MSTeamsAuthStrategy(..., store=self._session_store)     # line 229 (FEAT-729)
    async def _effective_user_id(self, turn_context, fallback) -> str: ...  # line 345
    #   read-only session precedent: get_or_create + is_expired, never an exchange
    async def _handle_card_submission(self, turn_context, dialog_context): ...  # line 482
    #   dispatch order: _is_authorized → a2ui_token (:508) → a2ui_action (:546)
    #                   → ENVELOPE_KEY (:576) → command (:586) → _action/dialogs
        if ENVELOPE_KEY in submitted_data:                               # line 576
            await self._handle_formdesigner_submit(turn_context, submitted_data)  # line 577
    async def on_message_activity(self, turn_context: TurnContext): ...  # line 657
        dispatched = await self._command_router.try_dispatch(clean_text, turn_context)  # line 700
    async def _handle_formdesigner_submit(self, turn_context, submitted_data) -> None: ...  # line 1180
    async def _get_formdesigner_session(self) -> aiohttp.ClientSession: ...  # line 1214
    async def close_formdesigner_client(self) -> None: ...               # line 1220
FORMDESIGNER_API_BASE_PATH: str = "/api/v1"                              # line 75 (fallback only)
```

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py
@dataclass
class MSTeamsAgentConfig:                                                # line 16
    name: str                                                            # line 32
    chatbot_id: str                                                      # line 33
    app_tenantid: Optional[str] = None     # Azure AD GUID — NOT a FormDesigner tenant  # line 37
    commands: Dict[str, str] = field(default_factory=dict)               # line 40
    adaptive_card_version: str = DEFAULT_ADAPTIVE_CARD_VERSION           # line 51
    formdesigner_allowed_hosts: Optional[List[str]] = None               # line 62
    formdesigner_submit_token: Optional[str] = None                      # line 63
    formdesigner_submit_secret: Optional[str] = None                     # line 64
    formdesigner_submit_timeout: float = 15.0                            # line 65
    formdesigner_api_base_path: str = "/api/v1"                          # line 66
    def __post_init__(self): ...                                         # line 68
        if self.formdesigner_api_base_path == "/api/v1":                 # line 96 — env-fallback block
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py   (tp = tenant-prefixed base path)
def _wrap_auth(handler: _Handler, *, tenant: str = "required") -> _Handler: ...               # line 85
app.router.add_get(f"{tp}/forms", _wrap_auth(handler.list_forms))                             # line 383 (tenant="required")
app.router.add_get(f"{tp}/forms/{{form_uid}}", _wrap_auth(handler.get_form, tenant="public")) # lines 393-396
app.router.add_get(f"{tp}/forms/{{form_uid}}/render/{{format}}", ... tenant="public")          # lines 416-418
app.router.add_post(f"{tp}/forms/{{form_uid}}/data", ... tenant="public")                      # lines 431-433

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
def _get_tenant(self, request: web.Request) -> str: ...                  # line 397
async def list_forms(self, request: web.Request) -> web.Response: ...    # line 851
#   → {"forms": [{form_uid, form_id, title, description, version, source, created_at}]}
#   → supports ?slug=<form_id> (FEAT-389) via FormRegistry.get_by_slug()

# packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py
def supported_formats() -> list[str]: ...                                # line 109
async def handle_render(request: web.Request) -> web.Response: ...       # line 165
#   ?with_meta=true → {"content", "content_type", "warnings", "metadata"}   # lines 215-236

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:                                                      # line 240
    async def get(self, form_uid: uuid.UUID, *, tenant: str | None = None) -> FormSchema | None: ...  # line 976
    async def get_by_slug(self, ...) -> FormSchema | None: ...           # line 1004
    async def list_forms(self, *, tenant: str | None = None) -> list[FormSchema]: ...   # line 1102
    async def list_form_ids(self, *, tenant: str | None = None) -> list[str]: ...       # line 1118

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py
async def render_section(...)                                            # line 281

# packages/ai-parrot/src/parrot/bots/agent.py
def agent_tools(self) -> List[AbstractTool]: ...                         # line 469 (returns [])

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ServerManagedToolkit, ABC):                        # line 225
    def __init__(self, **kwargs): ...                                    # line 357
    def get_tools(self, permission_context=None, resolver=None) -> list[AbstractTool]: ...  # line 522

# packages/ai-parrot-integrations/src/parrot/integrations/manager.py
async def shutdown(self) -> None: ...                                    # line 988
        self.msteams_bots.clear()                                        # line 1109 (no session close today)

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/dialogs/presets/wizard.py
class WizardFormDialog(BaseFormDialog):                                  # line 36 — NOT used by this feature
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| wrapper agent-first branch | `TeamsFormDesignerMixin.handle_formdesigner_card()` | `getattr(self.agent, …)` + await | `wrapper.py:576` |
| wrapper fallback | `MSTeamsAgentWrapper._handle_formdesigner_submit()` | unchanged call | `wrapper.py:577` |
| `_register_agent_commands` | `MSTeamsCommandRouter.register()` | method call | `commands/__init__.py:56` |
| `TeamsFormDesignerMixin.serve_form` | `MessageHandler.send_card()` | `send_card(card, turn_context)` | `handler.py:60` |
| `TeamsFormDesignerMixin` (local) | `TeamsFormRenderer.render()` / `.render_section()` | `tenant=` kwarg required | `renderers/teams.py:126`, `:150` |
| `TeamsFormDesignerMixin` (local) | `FormRegistry.get()` / `.get_by_slug()` | await | `services/registry.py:976`, `:1004` |
| `TeamsFormDesignerMixin` (inbound) | `parse_envelope` → `verify_envelope` → `post_submission` → `build_reply_card` | sequential calls | `formdesigner_submit.py:32`, `:44`, `:73`, `:122` |
| `FormDesignerClient.list_forms` | `GET {tp}/forms` | aiohttp + Bearer | `routes.py:383` |
| `FormDesignerClient.render_teams` | `GET …/render/teams?with_meta=true` | aiohttp + Bearer | `routes.py:416`, `render.py:218` |
| Remote section rendering (M9) | `handle_render` → `TeamsFormRenderer.render_section` | NEW optional section_index query, with unchanged membership checks | `api/render.py:199-210`, `renderers/teams.py:150` |
| Normal-turn toolkit delivery (M4/M7) | all wrapper `form_orchestrator.process_message` calls | NEW formdesigner_turn context and flush_formdesigner_cards hook | `wrapper.py:514`, `:557`, `:794`, `:1144` |
| Local membership authorization (M2/M4) | host LocalFormAuthorizer adapter | NEW required injection before registry operations | Registry does not authorize; HTTP policy precedent `api/render.py:199-202` |
| `FormDesignerToolkit` | `Agent.agent_tools()` | `super().agent_tools() + get_tools()` | `agent.py:469`, `toolkit.py:522` |
| `resolve_form_tenant` | FEAT-733 `formdesigner_tenant_map` | dict lookup on BOTH AAD GUID tiers | spec `msteams-submit-envelope-fail-closed.spec.md` M6 |
| `resolve_bearer` | `MSTeamsUserSession.nav_session_token` | `UserSessionLike` Protocol attribute | `auth.py:54` |
| `resolve_form_tenant` (session tier) | `MSTeamsUserSession.tenant_id` | `UserSessionLike` Protocol attribute (AAD GUID) | `auth.py:51`, filled `auth.py:159-164` |
| mixin session reads | `MSTeamsSessionStore.get_or_create()` / `.is_expired()` | `TeamsSessionStoreLike` Protocol | `auth.py:134`, `:130` |
| `bind_teams_identity` | `MSTeamsAgentWrapper._session_store` | `getattr(self.agent, "bind_teams_identity")` at wiring | `wrapper.py:223` |
| `IntegrationManager.shutdown` | `agent.aclose()` appended to the existing per-bot close loop | `close_formdesigner_client()` is ALREADY awaited there; await before `clear()` | `manager.py:1067`, `:1139` |

### Does NOT Exist (Anti-Hallucination)

- ~~`TeamsIdentityProvider`~~ and ~~a `current_session()` accessor~~ — these were
  an earlier draft's invention and have **0 source hits anywhere**. FEAT-729 exposes
  `MSTeamsSessionStore.get_or_create()` and `MSTeamsAuthStrategy
  .ensure_authenticated()` instead. Do NOT reintroduce either name.
- ~~`UserSessionLike`~~, ~~`TeamsSessionStoreLike`~~ — M2 **defines** these
  Protocols; 0 hits before this feature.
- `MSTeamsUserSession`, `MSTeamsSessionStore`, `MSTeamsAuthStrategy`, `/login`,
  `/logout`, `/whoami` and `parrot.auth.token_exchange.TokenExchangeClient` all
  **DO exist now** — FEAT-729 landed 2026-10-23 (`auth.py`, `commands/auth_commands.py:94-96`,
  `token_exchange.py:39`). They are listed under Existing Class Signatures above.
- ~~`parrot.auth.token_exchange.TokenExchangeResult`~~ — the real result type is
  **`ExchangeResult`** (`token_exchange.py:25`). This feature uses neither: it only
  reads an already-authenticated session.
- ~~A FormDesigner tenant slug anywhere on the session~~ — `MSTeamsUserSession` has
  only `tenant_id` (an AAD GUID, `auth.py:51`) and a free-form `metadata` dict that
  no `set_authenticated` caller populates with a slug.
- ~~`resolve_submit_tenant()`~~, ~~`MSTeamsAgentConfig.formdesigner_tenant_map`~~,
  ~~`require_signature`~~ — FEAT-733, 6 tasks still pending; 0 source hits.
- ~~`MSTeamsAgentConfig.tenant`~~ — no FormDesigner tenant field exists. Only
  `app_tenantid` (an AAD GUID, `models.py:37`), a different namespace from
  FormDesigner's tenant slug.
- ~~`FormDesignerToolkit`~~, ~~`formdesigner_list_forms`~~,
  ~~`formdesigner_get_form`~~ — 0 hits anywhere under `packages/`.
- ~~A FormDesigner **read** client~~ — the only FormDesigner HTTP code is
  `post_submission()` and the submit-only session at `wrapper.py:1214`.
- ~~`MSTeamsAgentWrapper.send_card`~~ — `send_card` is defined on `MessageHandler`
  (`handler.py:60`) and on `dialogs/presets/base.py:182`; the wrapper inherits it.
- ~~An agent→wrapper command seam carrying the `TurnContext`~~ — only
  `config.commands` → `_make_custom_handler` exists, and it passes kwargs only.
- ~~A card-submission hook on the agent~~ — `_handle_card_submission` consults A2UI,
  the envelope, the command router and dialogs; it never asks the agent.
- ~~`parrot_tools.formdesigner`~~ — no such module (this feature deliberately keeps
  the toolkit in `ai-parrot-integrations`).
- ~~`dialogs/card_builder.py`~~ — removed by TASK-524 (finding F021).
- ~~`TeamsFormRenderer` inside the dialog presets~~ — `presets/base.py`
  instantiates a plain `AdaptiveCardRenderer()`, so the dialog lane produces no
  envelope.

### Edit Sites (Blueprint Anchors)

Verified against: `87341f43c`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | `        if ENVELOPE_KEY in submitted_data:` | `wrapper.py:576` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | `        agent_cmd_handler.register(self._command_router)` | `wrapper.py:191` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | `    async def close_formdesigner_client(self) -> None:` | `wrapper.py:1220` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` | MODIFY | `    formdesigner_api_base_path: str = "/api/v1"  # must match setup_form_api(base_path=...) on the FormDesigner side` | `models.py:66` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` | MODIFY | `        if self.formdesigner_api_base_path == "/api/v1":` | `models.py:101` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | `                await wrapper.close_formdesigner_client()` | `manager.py:1067` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_client.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_identity.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_cards.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_wizard.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_mixin.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/tools/formdesigner.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_serve.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_mixin_roundtrip.py` | CREATE | — | — | — |
| `docs/formdesigner-serve-forms.md` | CREATE | — | — | — |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` | MODIFY | `        rendered = await renderer.render(form, **render_kwargs)` | `render.py:210` | 1 |
| `packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py` | MODIFY | existing dispatcher tests; extend with M9 contract cases | current test module | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `aiohttp` only — never `requests`/`httpx` (TID251 fails the merge gate).
- Pydantic v2 for the client's models; `MSTeamsAgentConfig` is a **dataclass**, so
  new fields follow its style and resolve env fallbacks in `__post_init__` with the
  `{NAME}_FORMDESIGNER_*` convention (`models.py:101`).
- Mixin style follows `SkillRegistryMixin` (`parrot/skills/mixin.py:47`): a
  cooperative `__init__(*args, **kwargs)`, lazy configuration, and tool
  contribution through `agent_tools()`.
- All wrapper seams are `getattr`-guarded and additive — an agent without the
  mixin must take byte-identical paths to today.
- Logging through `self.logger`; log the tenant source on every fetch, never the
  bearer, never an envelope verification reason to the user.
- Reuse `post_submission()` rather than writing a POST: it already pins
  `allow_redirects=False`, bounds the body, and converts errors to
  `SubmitOutcome(status=0, error=…)`.

### Known Risks / Gotchas

- **The picker key must never be `_formdesigner`.** `wrapper.py:576` routes on that
  key alone, and `extract_answers` treats everything outside
  `RESERVED_CONTROL_KEYS` as an answer. A picker card using `ENVELOPE_KEY` would be
  parsed as a submission with garbage answers. Use `PICKER_ACTION_KEY`
  (`_formdesigner_action`) and add it to the seam's condition. Underscore-prefixed
  additive keys are safe for the dialog lane too (finding F021).
- **Dispatch order.** The two A2UI branches (`wrapper.py:508`, `:546`) run before
  the envelope branch. A picker card must not carry `a2ui_token` or `a2ui_action`.
- **The dialog lane is a trap.** `WizardFormDialog` renders with a plain
  `AdaptiveCardRenderer` and completes via `FormOrchestrator`, so a form served
  through it carries no envelope and would never reach `post_submission`. Do not
  "simplify" M5 by delegating to it.
- **FEAT-733 will change `verify_envelope`'s signature** (`require_signature`,
  default `True`) and add `resolve_submit_tenant`. Call `verify_envelope` with
  keywords only, and treat the signature as mandatory from day one; in local mode a
  missing `signing_secret` must fail loudly rather than emit an unsigned card.
- **The session's `tenant_id` is an AAD GUID, not a FormDesigner tenant.**
  `MSTeamsSessionStore.get_or_create` fills it from `channel_data["tenant"]["id"]`
  (`auth.py:159-164`), the same namespace the activity asserts. Passing it anywhere
  a tenant slug belongs gives a wrong-tenant fetch or a 403. Every GUID tier goes
  through `formdesigner_tenant_map`; only `config_tenant` is already a slug.
- **Never call `ensure_authenticated()` from this feature.** It may send a sign-in
  card (`auth.py:301`), pre-empting M3's login card and double-prompting the user.
  Read sessions with `get_or_create` + `is_expired` — the read-only pattern
  `_effective_user_id` (`wrapper.py:345`) already uses, whose docstring states it
  "Never triggers an exchange".
- **FEAT-733 is the remaining hard blocker.** FEAT-729 **landed 2026-10-23**, so
  `MSTeamsUserSession` / `MSTeamsSessionStore` / `MSTeamsAuthStrategy` are real and
  M2 consumes them through Protocols purely to stay unit-testable. Its TASK-4664 and
  TASK-4665 closed `done-with-issues`: identity *persistence* is unproven (no
  Postgres in that run), while the `/login → exchange → /whoami` bearer path this
  feature depends on is tested (9 passed).
- **Shared-file contention.** `wrapper.py` and `models.py` are edited by FEAT-733
  (TASK-4653/4655) and FEAT-729. M7 should land last and rebase onto whichever
  merges first.
- **The FEAT-551 session leak is ALREADY FIXED — do not re-fix it.**
  `IntegrationManager.shutdown()` closes the FormDesigner client and the voice
  transcriber in a per-bot loop, each in its own `try` (`manager.py:1067`), and
  ledger `a9514c9232ad` is closed (`resolved_by task:TASK-4059`). M7 adds only the
  agent's own `aclose()` there.
- **Teams caps Adaptive Cards at schema 1.6** and supports no upload inputs. The
  card payload byte cap is unconfirmed (§8), so the wizard is the mitigation for
  large forms, with the web-form link as the floor.
- **`GET {tp}/forms` is `tenant="required"`** (`routes.py:383`), unlike `get_form`
  and `render` which are `tenant="public"`. Listing therefore always needs a
  bearer; a login card is the only correct answer for an unauthenticated
  `/listforms`.
- **Wizard state is process-local.** With several gunicorn workers a user's next
  section may hit a different worker and find no state; the card must then restart
  the form rather than submit partial answers. Redis-backed state is a follow-up.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiohttp` | existing | the only permitted HTTP client; already a dependency |
| `parrot-formdesigner` | workspace | `FormSchema`, `TeamsFormRenderer`, `TeamsSubmitEnvelope`, `FormRegistry` — already declared (`pyproject.toml:61`, `:184`) |
| `botbuilder-core` / `botbuilder-schema` | existing | `TurnContext`, `Activity` |
| `pydantic` | v2, existing | client and state models |

No new third-party dependency.

---

## 8. Open Questions

- [x] Flow type and base branch — *Resolved in brainstorm*: `type: feature`,
  `base_branch: dev`.
- [x] How does the mixin obtain the card — HTTP or in-process? — *Resolved in
  brainstorm*: **dual** — HTTP `GET …/render/teams` when FormDesigner is remote,
  in-process `TeamsFormRenderer` when embedded. (§2 Overview, M1, M4)
- [x] What do we assume about the per-user bearer? — *Resolved in brainstorm*:
  depend on FEAT-729, blocking; no service-token interim. (§1 Non-Goals, M2, §7)
- [x] Where does the code live? — Agent-side code lives in
  `ai-parrot-integrations` under `parrot/integrations/msteams/`; M9 additionally
  extends `parrot-formdesigner/api/render.py` and its dispatcher tests. (§3)
- [x] How do the picker and the submit route back? — *Resolved in brainstorm*: the
  mixin owns a single handler; the wrapper's FEAT-551 branch is the fallback.
  (§2 Overview, M4, M7)
- [x] What travels in the card's `Action.Submit`? — *Resolved in brainstorm*: the
  signed `TeamsSubmitEnvelope` + `verify_envelope()` as defence in depth, with the
  per-user bearer on the POST. (§2 Overview, M4, §5)
- [x] Where does the tenant come from? — *Resolved in brainstorm*: the
  authenticated user, with the bot's static value as fallback. Refined in this
  spec's §3 round: **mapped AAD GUID > session > config**. (M2, §5)
- [x] Behavior with no session / unrenderable fields? — *Resolved in brainstorm*:
  login card; FEAT-551-style upload degradation. (M3, §5)
- [x] Precedence between the session tenant and FEAT-733's AAD map — *Resolved
  2026-10-23; **revised 2026-10-24** once FEAT-729 landed*: there is no session
  *tenant* to rank. `session.tenant_id` is the same AAD GUID the activity asserts
  (`auth.py:159-164`), and nothing on the session holds a FormDesigner slug. The
  chain is `mapped activity GUID > mapped session GUID > config slug`, with
  `formdesigner_tenant_map` as the only conversion point; the session tier survives
  solely as a GUID cache for activities without `channel_data.tenant.id`. This also
  matches FEAT-733's `resolve_submit_tenant`, which has no session tier either.
- [x] Does the toolkit send the card or return metadata? — *Resolved 2026-10-23*:
  metadata plus a `card_pending` marker; the mixin sends the card.
- [x] Single card or section wizard in v1? — *Resolved 2026-10-23*: both — single
  card plus a `render_section()` wizard with per-conversation state (M5).
- [ ] Is a static `formdesigner_tenant` on `MSTeamsAgentConfig` still worth having
  once FEAT-733's `formdesigner_tenant_map` exists? Both encode "which tenant", and
  three fallback levels may be one too many. — *Owner: Jesus Lara*
- [ ] What is the real Adaptive Card payload byte cap in Teams, and at how many
  fields should `/getform` stop rendering and hand over the web-form link? Needs
  confirming against current Microsoft documentation. — *Owner: Jesus Lara*
- [ ] `/getform <ref>`: the spec accepts both a slug and a `form_uid` (UUID-shaped
  → uid, otherwise slug). Confirm that rule, and what to do when a slug is
  literally UUID-shaped. — *Owner: Jesus Lara*
- [ ] In `local` mode, how is the `FormRegistry` supplied — constructor kwarg (the
  spec's assumption), the aiohttp app key, or a module-level singleton? — *Owner:
  Jesus Lara*
- [ ] Should the client session be owned by the mixin (agent lifecycle, the spec's
  assumption) or by the wrapper (integration lifecycle)? — *Owner: Jesus Lara*
- [ ] Sequencing: wait for FEAT-733's six tasks to merge before starting M7, or
  start now and rebase? — *Owner: Jesus Lara*
- [ ] Group/channel conversations are out of scope for v1 (§1 Non-Goals). Confirm
  that 1:1-only is acceptable for the first release. — *Owner: Jesus Lara*
- [ ] Wizard state across gunicorn workers: is restart-on-miss acceptable for v1,
  or is Redis-backed state required before release? — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `n/a` · Status: skipped (exploration document
> `sdd/proposals/formdesigner-serve-forms.brainstorm.md` has `**Status**:
> exploration`, not `accepted` — §3b precondition not met) · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

To run it: set the brainstorm's `**Status**` to `accepted`, then re-run
`/sdd-spec formdesigner-serve-forms`; §9 is the only section that changes.

---

## Worktree Strategy

- **Isolation**: one feature worktree,
  `feat-FEAT-734-formdesigner-serve-forms`, branched from `origin/dev`. The
  `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M1 (client), M2 (identity), M5 (wizard store) and M9 (server section render)
    can proceed independently against the specified interfaces.
  - M3 depends on M1's `FormDescriptor` contract.
  - M6 → M1, M2 (the toolkit calls `FormDesignerClient` and takes the tenant /
    bearer resolvers M2 defines).
  - M4 → M1, M2, M3, M5, M6 (the mixin composes all five; it imports
    `FormDescriptor`, `resolve_form_tenant`, `build_picker_card`, `WizardStore`
    and `FormDesignerToolkit`).
  - M7 → M4 (the wrapper seam calls `handle_formdesigner_card` and
    `teams_commands`, and `PICKER_ACTION_KEY` is defined by M4).
  - M8 → M1…M7, M9 (tests and docs cover both local and remote section serving).
- **Shared files** — three, all inside M7, which is why M7 is a single module
  rather than split per file:
  - `wrapper.py`: the agent-first seam (`:576`), the command hook (`:191`) and the
    shutdown path (`:1220`).
  - `models.py`: the new config fields (`:66`) and their env fallbacks (`:101`).
  - `manager.py`: one `aclose()` added to the existing per-bot close loop (`:1067`).
- **Exclusive resources**: none. No migration, no lockfile change, no native
  extension rebuild.
- **Cross-feature dependencies** — this is the constraining factor:
  - **FEAT-729 (`msteams-user-auth-lane`) has MERGED** (`completed_at`
    2026-10-23). It owns the `MSTeamsUserSession` this feature's bearer comes from
    and the wrapper's single `MSTeamsSessionStore` (`wrapper.py:223`) that M7
    injects via `bind_teams_identity`. M1–M6 still build and test against M2's
    Protocols with plain fakes. Caveat: its TASK-4664/TASK-4665 closed
    `done-with-issues` — identity persistence is unproven (no reachable Postgres),
    though the bearer path this feature needs is tested.
  - **FEAT-733 (`msteams-submit-envelope-fail-closed`) should merge first.** Its
    six pending tasks change `verify_envelope`'s signature
    (`require_signature`), add `resolve_submit_tenant` and
    `formdesigner_tenant_map`, and edit `wrapper.py` and `models.py` — the same
    three files M7 touches. If it has not merged when M7 starts, M7 rebases onto
    it rather than the reverse.
  - No overlap with FEAT-730, FEAT-731 or FEAT-732 (all `parrot-formdesigner`
    server-side); M9 now edits the render dispatcher, so recheck server-side
    overlap before implementation rather than assuming no shared files.

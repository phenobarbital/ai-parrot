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
**Status**: draft
**Target version**: 1.3.0

> **Inputs**: `sdd/proposals/formdesigner-serve-forms.brainstorm.md` (Recommended
> Option A), whose eight resolved questions are carried forward verbatim into this
> spec (§8). Every code reference below was verified at commit `a9e3c9f5f`.

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
   submit-only POST at `wrapper.py:1091`; there is no FormDesigner read client
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

**Two additive wrapper seams.** At the existing `if ENVELOPE_KEY in
submitted_data:` branch (`wrapper.py:473`) the wrapper asks the agent first via
`handle_formdesigner_card(turn_context, submitted_data) -> bool`; only a `False`
or a missing attribute runs `_handle_formdesigner_submit`. A second hook lets the
agent contribute commands that receive the `TurnContext` — the existing
`config.commands` mechanism cannot be reused, because `_make_custom_handler`
(`agent_commands.py:449`) calls `method(**kwargs)` with text-parsed kwargs and
never passes the `TurnContext`, so a handler registered that way can neither send
a card nor read the Teams identity. Both seams are `getattr`-guarded.

**Dual render.** `mode="remote"` fetches
`GET {base}{api}/{tenant}/forms/{uid}/render/teams?with_meta=true` and uses the
envelope the *server* signed. `mode="local"` resolves the form through the
in-process `FormRegistry` and renders with `TeamsFormRenderer`, which the agent
must then configure with `public_base_url` **and** `signing_secret` — FEAT-733's
`require_signature` (default `True`) will refuse an unsigned envelope, so the
secret is a requirement in local mode, not a nicety.

**Tenant precedence is fixed**: the Bot Framework-asserted AAD GUID mapped through
FEAT-733's `formdesigner_tenant_map` wins; the authenticated session's tenant is
used when the GUID is unmapped; the bot's static config value is the last resort.
The server-asserted value outranks the session for the same reason FEAT-733 gives:
what the server asserts is more trustworthy than what the client claims.

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
MSTeamsCommandRouter      _handle_card_submission (wrapper.py:385)
  try_dispatch :74          ① a2ui_token  ② a2ui_action
       │                    ③ NEW agent-first seam ──► handle_formdesigner_card()
       │                    ④ ENVELOPE_KEY :473 (fallback, FEAT-551/733)
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
| `MSTeamsAgentWrapper._handle_card_submission` | modifies | new agent-first branch immediately before `wrapper.py:473` |
| `MSTeamsAgentWrapper.__init__` (command wiring) | modifies | agent command-contribution hook after `agent_commands.register` (`wrapper.py:182`) |
| `MSTeamsCommandRouter.register()` | uses | `/getform`, `/listforms` registered like any built-in command |
| `MessageHandler.send_card()` | uses | card first, `turn_context` second (`handler.py:60`) |
| `TeamsFormRenderer.render()` / `.render_section()` | uses | local mode; `tenant=` is mandatory |
| `parse_envelope` / `verify_envelope` / `extract_answers` / `post_submission` / `build_reply_card` / `RecentActivityCache` | uses | reused unchanged from `formdesigner_submit.py` |
| `FormRegistry.get()` / `.get_by_slug()` / `.list_forms()` | uses | local mode only |
| `GET {tp}/forms`, `GET …/{uid}`, `…/render/{format}`, `POST …/data` | calls | remote mode; `GET /forms` is `tenant="required"`, so a bearer is mandatory |
| `MSTeamsAgentConfig` | modifies | new `formdesigner_*` read/render fields + `{NAME}_FORMDESIGNER_*` env fallbacks |
| `IntegrationManager.shutdown()` | modifies | close the mixin's client (and the FEAT-551 session it already leaks — ledger `a9514c9232ad`) |
| `Agent.agent_tools()` | extends | toolkit contribution (`agent.py:469`) |
| FEAT-729 `MSTeamsUserSession` | **depends on** | `nav_session_token` is the bearer; consumed through a Protocol |
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
    source: Literal["aad_map", "session", "config"]


# packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_wizard.py (new)
@dataclass
class WizardState:
    """One in-flight sectioned form for one conversation."""
    form_uid: uuid.UUID
    tenant: str
    section_index: int
    total_sections: int
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
| M2: Tenant + bearer resolution | yes | precedence `aad_map > session > config`; `TenantResolution`; Protocol-based session access | — |
| M3: Card builders | yes | picker uses `Input.ChoiceSet` + one Submit carrying `PICKER_ACTION_KEY`; login/error/empty card texts fixed | — |
| M5: Wizard state store | yes | `WizardState` fields, TTL eviction, key `(conversation_id, form_uid)` | — |
| M6: Toolkit | yes | two tools, metadata-only returns, docstrings are the LLM contract | — |
| M4: The mixin | **no** | — | orchestration order (picker vs wizard vs terminal), login/degradation branching, and the toolkit↔card handoff are design calls |
| M7: Wrapper + config seams | **no** | — | shares `wrapper.py` / `models.py` with FEAT-733 and FEAT-729; seam placement relative to branches ③/④ is a design call |
| M8: Tests + docs | partial | unit tests for M1/M2/M3/M5/M6 are mechanical; the round-trip integration test is not | — |

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
          self, *, tenant: str, form_uid: uuid.UUID, bearer_token: str | None
      ) -> RenderedCard:
          """GET {api}/{tenant}/forms/{form_uid}/render/teams?with_meta=true.

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
- **Depends on**: nothing in this spec. Reads FEAT-729's session through a
  `Protocol`, so this module compiles and tests before FEAT-729 exists.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_identity.py  (new)
  class UserSessionLike(Protocol):
      """The subset of FEAT-729's MSTeamsUserSession this feature consumes."""
      authenticated: bool
      nav_session_token: str | None
      nav_user_id: str | None

  class TeamsIdentityProvider(Protocol):
      """Supplied by FEAT-729's auth lane; absent until it lands."""
      async def current_session(self, turn_context: "TurnContext") -> UserSessionLike | None: ...

  def resolve_form_tenant(
      *,
      asserted_tenant_id: str | None,     # activity.channel_data["tenant"]["id"] (AAD GUID)
      tenant_map: dict[str, str] | None,  # FEAT-733 formdesigner_tenant_map
      session_tenant: str | None,
      config_tenant: str | None,
  ) -> TenantResolution:
      """Fixed precedence: mapped AAD GUID > authenticated session > bot config.

      Raises TenantUnresolved when all three are empty — never guesses a tenant.
      """

  def resolve_bearer(session: UserSessionLike | None) -> str | None:
      """session.nav_session_token when authenticated, else None (-> login card)."""
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
          formdesigner_identity: Any | None = None,       # TeamsIdentityProvider (FEAT-729)
          **kwargs: Any,
      ) -> None:
          """Cooperative __init__ — forwards *args/**kwargs to the next class in the MRO."""

      def teams_commands(self) -> dict[str, Callable[["TurnContext"], Awaitable[None]]]:
          """{"getform": self.handle_getform, "listforms": self.handle_listforms}."""

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
          self, *, conversation_id: str, form_uid: uuid.UUID, tenant: str, total_sections: int
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
          client: FormDesignerClient,
          *,
          tenant_resolver: Callable[[], str | None],
          bearer_resolver: Callable[[], str | None],
          **kwargs: Any,
      ) -> None:
          """Resolvers are request-scoped callables owned by the mixin."""

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
- **Responsibility**: the two additive seams, the new config fields with their
  `{NAME}_FORMDESIGNER_*` env fallbacks, and closing the client on shutdown.
- **Depends on**: M4.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:473
  # (new branch immediately BEFORE the existing `if ENVELOPE_KEY in submitted_data:`)
  handler = getattr(self.agent, "handle_formdesigner_card", None)
  if handler is not None and (ENVELOPE_KEY in submitted_data or PICKER_ACTION_KEY in submitted_data):
      if await handler(turn_context, submitted_data):
          return
  # falls through to the FEAT-551/733 branch unchanged

  # modifies packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:182
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
      # env fallbacks resolved in __post_init__ beside models.py:96, same
      # {NAME}_FORMDESIGNER_* convention as the FEAT-551 fields.

  # modifies packages/ai-parrot-integrations/src/parrot/integrations/manager.py:988
  async def shutdown(self) -> None:
      """Also await wrapper.close_formdesigner_client() and the agent's
      aclose() for every msteams bot before msteams_bots.clear()
      (manager.py:1109) — fixes ledger a9514c9232ad as a side effect.
      """
  ```

### Module 8: Tests and documentation
- **Path**: `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_serve.py`,
  `…/tests/msteams/test_formdesigner_mixin_roundtrip.py`,
  `…/tests/integrations/msteams/test_msteams_models.py` (MODIFY),
  `docs/formdesigner-serve-forms.md` (new)
- **Responsibility**: §4's tests plus the operator-facing guide (config matrix,
  the two modes, the FEAT-729/733 prerequisites).
- **Depends on**: M1–M7.
- **Interface Skeleton**: n/a (tests and prose).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_client_list_forms_parses_descriptors` | M1 | `{"forms": [...]}` → `FormDescriptor`s; empty list is not an error |
| `test_client_list_forms_sends_bearer` | M1 | `Authorization: Bearer …` present when a token is given, absent when `None` |
| `test_client_render_teams_with_meta` | M1 | `?with_meta=true` envelope → `RenderedCard` incl. `metadata["envelope"]` |
| `test_client_render_teams_415_raises` | M1 | server without the `teams` format → `FormDesignerError(status=415)` |
| `test_client_no_redirects_and_bounded_body` | M1 | `allow_redirects=False`; an oversized body is refused |
| `test_tenant_precedence_aad_map_wins` | M2 | mapped GUID beats a different session tenant |
| `test_tenant_precedence_session_when_unmapped` | M2 | unmapped GUID → session tenant, `source="session"` |
| `test_tenant_precedence_config_last` | M2 | no GUID, no session → config, `source="config"` |
| `test_tenant_unresolved_raises` | M2 | all three empty → `TenantUnresolved` |
| `test_resolve_bearer_requires_authenticated` | M2 | `authenticated=False` → `None` |
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

### Validation Contract

tests:
- packages/ai-parrot-integrations/tests/msteams/test_formdesigner_serve.py
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
    """Stands in for FEAT-729's MSTeamsUserSession (UserSessionLike Protocol)."""
    return SimpleNamespace(authenticated=True, nav_session_token="nav-tok", nav_user_id="u1")

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
- [ ] Tenant precedence is exactly `mapped AAD GUID > authenticated session > bot
      config`, with the winning source logged; all three empty → error card.
- [ ] No authenticated session → login card, and the FormDesigner client issues
      zero requests.
- [ ] Multi-section forms walk section by section; only the terminal Submit posts
      answers, and the accumulated answers of earlier sections are included.
- [ ] Upload fields keep `TeamsFormRenderer`'s notice + `Action.OpenUrl` behavior,
      and their `RenderWarning`s are visible in the card.
- [ ] `formdesigner_get_form` returns metadata with `card_pending` and never
      Adaptive Card JSON; the card is sent by the mixin.
- [ ] An agent **without** the mixin behaves exactly as FEAT-551 does today
      (`test_formdesigner_roundtrip.py` unchanged and passing).
- [ ] A duplicate `activity.id` delivery posts once.
- [ ] `IntegrationManager.shutdown()` closes the mixin's client **and** the FEAT-551
      session (ledger `a9514c9232ad` closed).
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
> Verified at commit `a9e3c9f5f`. Implementation agents MUST NOT reference imports,
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
from parrot.forms import FormSchema                      # verified: wrapper.py:46 (shim → parrot_formdesigner.core)
from parrot.tools.toolkit import AbstractToolkit         # verified: parrot/tools/toolkit.py:225
from parrot_formdesigner.services.registry import FormRegistry   # verified: services/registry.py:240
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
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):              # line 94
    self._formdesigner_session: Optional[aiohttp.ClientSession] = None   # line 163
    self._formdesigner_recent = RecentActivityCache()                    # line 164
    self._command_router: MSTeamsCommandRouter = MSTeamsCommandRouter()  # line 180
    agent_cmd_handler.register(self._command_router)                     # line 182
    async def _handle_card_submission(self, turn_context, dialog_context): ...  # line 385
    #   dispatch order: auth → a2ui_token (:424) → a2ui_action (:446)
    #                   → ENVELOPE_KEY (:473) → command (:484) → _action/dialogs
        if ENVELOPE_KEY in submitted_data:                               # line 473
            await self._handle_formdesigner_submit(turn_context, submitted_data)  # line 474
    async def on_message_activity(self, turn_context: TurnContext): ...  # line 554
        dispatched = await self._command_router.try_dispatch(clean_text, turn_context)  # line 575
    async def _handle_formdesigner_submit(self, turn_context, submitted_data) -> None: ...  # line 1057
    async def _get_formdesigner_session(self) -> aiohttp.ClientSession: ...  # line 1091
    async def close_formdesigner_client(self) -> None: ...               # line 1097
FORMDESIGNER_API_BASE_PATH: str = "/api/v1"                              # line 71 (fallback only)
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
| wrapper agent-first branch | `TeamsFormDesignerMixin.handle_formdesigner_card()` | `getattr(self.agent, …)` + await | `wrapper.py:473` |
| wrapper fallback | `MSTeamsAgentWrapper._handle_formdesigner_submit()` | unchanged call | `wrapper.py:474` |
| `_register_agent_commands` | `MSTeamsCommandRouter.register()` | method call | `commands/__init__.py:56` |
| `TeamsFormDesignerMixin.serve_form` | `MessageHandler.send_card()` | `send_card(card, turn_context)` | `handler.py:60` |
| `TeamsFormDesignerMixin` (local) | `TeamsFormRenderer.render()` / `.render_section()` | `tenant=` kwarg required | `renderers/teams.py:126`, `:150` |
| `TeamsFormDesignerMixin` (local) | `FormRegistry.get()` / `.get_by_slug()` | await | `services/registry.py:976`, `:1004` |
| `TeamsFormDesignerMixin` (inbound) | `parse_envelope` → `verify_envelope` → `post_submission` → `build_reply_card` | sequential calls | `formdesigner_submit.py:32`, `:44`, `:73`, `:122` |
| `FormDesignerClient.list_forms` | `GET {tp}/forms` | aiohttp + Bearer | `routes.py:383` |
| `FormDesignerClient.render_teams` | `GET …/render/teams?with_meta=true` | aiohttp + Bearer | `routes.py:416`, `render.py:218` |
| `FormDesignerToolkit` | `Agent.agent_tools()` | `super().agent_tools() + get_tools()` | `agent.py:469`, `toolkit.py:522` |
| `resolve_form_tenant` | FEAT-733 `formdesigner_tenant_map` | dict lookup on the AAD GUID | spec `msteams-submit-envelope-fail-closed.spec.md` M6 |
| `resolve_bearer` | FEAT-729 `MSTeamsUserSession.nav_session_token` | Protocol attribute | spec `msteams-user-auth-lane.spec.md` §2 |
| `IntegrationManager.shutdown` | `wrapper.close_formdesigner_client()` + `agent.aclose()` | await before `clear()` | `manager.py:988`, `:1109` |

### Does NOT Exist (Anti-Hallucination)

- ~~`MSTeamsUserSession`~~, ~~`MSTeamsSessionStore`~~, ~~`MSTeamsAuthStrategy`~~,
  ~~`/login`~~ — FEAT-729 is **approved** and its 7 task ids are reserved
  (`39cabf1e8`), but **0 source hits** for each name at `a9e3c9f5f`. Consume them
  only through M2's `UserSessionLike` / `TeamsIdentityProvider` Protocols.
- ~~`parrot.auth.token_exchange.TokenExchangeClient`~~ / ~~`TokenExchangeResult`~~ —
  FEAT-729 interfaces, not in the tree.
- ~~`resolve_submit_tenant()`~~, ~~`MSTeamsAgentConfig.formdesigner_tenant_map`~~,
  ~~`require_signature`~~ — FEAT-733, 6 tasks still pending; 0 source hits.
- ~~`MSTeamsAgentConfig.tenant`~~ — no FormDesigner tenant field exists. Only
  `app_tenantid` (an AAD GUID, `models.py:37`), a different namespace from
  FormDesigner's tenant slug.
- ~~`FormDesignerToolkit`~~, ~~`formdesigner_list_forms`~~,
  ~~`formdesigner_get_form`~~ — 0 hits anywhere under `packages/`.
- ~~A FormDesigner **read** client~~ — the only FormDesigner HTTP code is
  `post_submission()` and the submit-only session at `wrapper.py:1091`.
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

Verified against: `a9e3c9f5f`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | `        if ENVELOPE_KEY in submitted_data:` | `wrapper.py:473` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | `        agent_cmd_handler.register(self._command_router)` | `wrapper.py:182` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | `    async def close_formdesigner_client(self) -> None:` | `wrapper.py:1097` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` | MODIFY | `    formdesigner_api_base_path: str = "/api/v1"  # must match setup_form_api(base_path=...) on the FormDesigner side` | `models.py:66` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` | MODIFY | `        if self.formdesigner_api_base_path == "/api/v1":` | `models.py:96` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | `    async def shutdown(self) -> None:` | `manager.py:988` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | `        self.msteams_bots.clear()` | `manager.py:1109` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_client.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_identity.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_cards.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_wizard.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_mixin.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/tools/formdesigner.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_serve.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_mixin_roundtrip.py` | CREATE | — | — | — |
| `docs/formdesigner-serve-forms.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `aiohttp` only — never `requests`/`httpx` (TID251 fails the merge gate).
- Pydantic v2 for the client's models; `MSTeamsAgentConfig` is a **dataclass**, so
  new fields follow its style and resolve env fallbacks in `__post_init__` with the
  `{NAME}_FORMDESIGNER_*` convention (`models.py:96`).
- Mixin style follows `SkillRegistryMixin` (`parrot/skills/mixin.py:47`): a
  cooperative `__init__(*args, **kwargs)`, lazy configuration, and tool
  contribution through `agent_tools()`.
- Both wrapper seams are `getattr`-guarded and additive — an agent without the
  mixin must take byte-identical paths to today.
- Logging through `self.logger`; log the tenant source on every fetch, never the
  bearer, never an envelope verification reason to the user.
- Reuse `post_submission()` rather than writing a POST: it already pins
  `allow_redirects=False`, bounds the body, and converts errors to
  `SubmitOutcome(status=0, error=…)`.

### Known Risks / Gotchas

- **The picker key must never be `_formdesigner`.** `wrapper.py:473` routes on that
  key alone, and `extract_answers` treats everything outside
  `RESERVED_CONTROL_KEYS` as an answer. A picker card using `ENVELOPE_KEY` would be
  parsed as a submission with garbage answers. Use `PICKER_ACTION_KEY`
  (`_formdesigner_action`) and add it to the seam's condition. Underscore-prefixed
  additive keys are safe for the dialog lane too (finding F021).
- **Dispatch order.** The two A2UI branches (`wrapper.py:424`, `:446`) run before
  the envelope branch. A picker card must not carry `a2ui_token` or `a2ui_action`.
- **The dialog lane is a trap.** `WizardFormDialog` renders with a plain
  `AdaptiveCardRenderer` and completes via `FormOrchestrator`, so a form served
  through it carries no envelope and would never reach `post_submission`. Do not
  "simplify" M5 by delegating to it.
- **FEAT-733 will change `verify_envelope`'s signature** (`require_signature`,
  default `True`) and add `resolve_submit_tenant`. Call `verify_envelope` with
  keywords only, and treat the signature as mandatory from day one; in local mode a
  missing `signing_secret` must fail loudly rather than emit an unsigned card.
- **FEAT-729 is the hard blocker.** Its 7 task ids are reserved but no code exists.
  M2's Protocols keep M1–M6 implementable and testable with a fake session, but the
  feature cannot be marked done until a real `TeamsIdentityProvider` is wired.
- **Shared-file contention.** `wrapper.py` and `models.py` are edited by FEAT-733
  (TASK-4653/4655) and FEAT-729. M7 should land last and rebase onto whichever
  merges first.
- **Session leak precedent.** `IntegrationManager.shutdown()` never closes the
  FEAT-551 session (ledger `a9514c9232ad`); M7 must close both, or this feature
  doubles the leak.
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
- [x] Where does the code live? — *Resolved in brainstorm*: all of it in
  `ai-parrot-integrations` under `parrot/integrations/msteams/`. (§3)
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
  2026-10-23*: the mapped AAD GUID wins; the session decides only when the GUID is
  unmapped. The server-asserted value is more trustworthy than the client's claim.
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
  - M1 (client), M2 (identity), M3 (cards) and M5 (wizard store) are
    **independent** — four new files, no shared symbol between them. Expected to
    run concurrently.
  - M6 → M1, M2 (the toolkit calls `FormDesignerClient` and takes the tenant /
    bearer resolvers M2 defines).
  - M4 → M1, M2, M3, M5, M6 (the mixin composes all five; it imports
    `FormDescriptor`, `resolve_form_tenant`, `build_picker_card`, `WizardStore`
    and `FormDesignerToolkit`).
  - M7 → M4 (the wrapper seam calls `handle_formdesigner_card` and
    `teams_commands`, and `PICKER_ACTION_KEY` is defined by M4).
  - M8 → M1…M7 (tests and docs describe their final names).
- **Shared files** — three, all inside M7, which is why M7 is a single module
  rather than split per file:
  - `wrapper.py`: the agent-first seam (`:473`), the command hook (`:182`) and the
    shutdown path (`:1097`).
  - `models.py`: the new config fields (`:66`) and their env fallbacks (`:96`).
  - `manager.py`: `shutdown()` (`:988`) and `msteams_bots.clear()` (`:1109`).
- **Exclusive resources**: none. No migration, no lockfile change, no native
  extension rebuild.
- **Cross-feature dependencies** — this is the constraining factor:
  - **FEAT-729 (`msteams-user-auth-lane`) must merge first.** It owns the
    `MSTeamsUserSession` this feature's bearer comes from. M1–M6 can be built and
    tested against M2's Protocols with a fake session, but the feature cannot be
    verified or marked done without it. Its 7 task ids are reserved
    (`39cabf1e8`); no code exists yet.
  - **FEAT-733 (`msteams-submit-envelope-fail-closed`) should merge first.** Its
    six pending tasks change `verify_envelope`'s signature
    (`require_signature`), add `resolve_submit_tenant` and
    `formdesigner_tenant_map`, and edit `wrapper.py` and `models.py` — the same
    three files M7 touches. If it has not merged when M7 starts, M7 rebases onto
    it rather than the reverse.
  - No overlap with FEAT-730, FEAT-731 or FEAT-732 (all `parrot-formdesigner`
    server-side; this feature changes no FormDesigner source file).

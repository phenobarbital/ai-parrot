---
type: feature
base_branch: dev
projects: [ai-parrot-integrations, ai-parrot, ai-parrot-server, docs]
tags: [oauth2, connections, msteams, adaptive-cards, principal, channel-notifier]
---

# Feature Specification: Connections on MS Teams — S-3b of Delegated Auth Connections (Teams principal, generic `/connect`, Teams `ChannelNotifier`, Adaptive-Card connect action)

**Feature ID**: FEAT-775
**Date**: 2026-10-30
**Author**: Jesus Lara (with Claude Opus 5.5)
**Status**: draft
**Target version**: 1.3.0

> **Source**: proposal `sdd/proposals/delegated-auth-connections.proposal.md` §6 row **"S-3b MS Teams"**
> ("Teams `ChannelNotifier` over the existing `MSTeamsOAuthNotifier` and FEAT-729 principal mapping; generic
> commands") and the FEAT-773 spec `sdd/specs/delegated-auth-connections.spec.md` §1 Non-Goals ("Teams
> `ChannelNotifier` beyond the compatibility adapter, Adaptive-Card connect action — **S-3b**").
> This spec has no exploration document of its own; every decision U1–U5 / S1–S11 taken for FEAT-773 binds it.
> **Hard dependency: FEAT-773 (S-1) merged.** Every core name used below that is marked *(FEAT-773)* is defined
> by that spec and does not exist on `dev` today (see §6 "Does NOT Exist").

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-773 makes connections principal-keyed and channel-neutral, but it only ports the Teams Jira flow onto a
**compatibility adapter** (`MSTeamsJiraNotifierAdapter`, FEAT-773 M8). Teams users still cannot use the
connections model as a first-class channel, and research at spec time found five concrete gaps:

1. **Commands are Jira-only.** `/connect_jira`, `/disconnect_jira`, `/jira_status` and the `jira` / `integrations`
   menu (`msteams/commands/jira_commands.py`) are hard-wired to one `JiraOAuthManager`; Office 365 and every
   descriptor-registered provider are unreachable from Teams. The commands key the token by the **AAD object id**
   (`_get_user_id`, jira_commands.py:129), which FEAT-773 retires as a key.
2. **No Teams principal on tool calls.** The Teams agent call passes only `user_id` / `session_id`
   (`FormOrchestrator.process_message` → `agent.ask(..., **context)`, wrapper.py:810-816, orchestrator.py:320);
   no `PermissionContext` with `channel="msteams"` reaches `ToolManager`, so FEAT-773's
   `OAuthCredentialResolver` cannot resolve a Teams caller. The fallback `user_id` for an unauthenticated user is
   `from_property.id` (`29:…`), not the AAD id the Jira store uses.
3. **The identity-row lookup misses logged-in Teams users.** FEAT-773's `IdentityPrincipalResolver` looks up
   `auth.user_identities` by `(channel, channel_user_id)` = `("msteams", aad_oid)`. The only writer of an
   `msteams` row is `handle_msteams_jira_callback` (oauth_callback.py:283), gated on
   `request.app.get("identity_mapping_service")` (:261) — **and nothing in `packages/` ever registers that app
   key** (grep: only `.get` reads). Teams `/login` (FEAT-729) does write a row, but under provider **`azure`**
   (navigator-auth `TokenExchange` → `store.save_linked_identity(uid, req.provider, …)`, exchange.py:190, called
   with `provider="azure"` from `MSTeamsAuthStrategy._ensure_authenticated`, auth.py:~345).
4. **Completion messages only work for one bot and one event.** `app["msteams_jira_oauth_notifier"]` is assigned
   by every `MSTeamsAgentWrapper.__init__` (wrapper.py:215), so with two Teams bots on one app the last one wins and
   proactive messages go out through the wrong adapter / app id. Only the callback path has a conversation
   reference; `connection.revoked` and `connection.refresh_failed` (no OAuth state) cannot reach the user at all.
5. **A tool's needs-auth signal never reaches the Teams user as an action.** `ToolManager.execute_tool` returns
   `ToolResult(status="authorization_required", metadata={auth_url, …})` (manager.py:2273-2290), but
   `AbstractClient._execute_tool` returns `result.result` (`None`) for every non-error `ToolResult`
   (clients/base.py:1661-1668), and `AIMessage.tool_calls[*].result` therefore carries nothing. The Teams wrapper
   has no way to render a "Connect" button; the user sees whatever prose the LLM improvises.

### Goals

- **G1 — Teams principal per turn.** An authenticated Teams turn (FEAT-729 session, `nav_user_id` present and
  unexpired) yields a FEAT-773 `Principal(user_id=nav_user_id, canonical_identity=aad_oid, tenant_id,
  channel="msteams", channel_user_id=aad_oid)`; it is passed to the agent call as a `PermissionContext` with
  `channel="msteams"`. An unauthenticated turn yields **no principal** — fail closed, never an AAD-keyed fallback.
- **G2 — Out-of-turn principal resolution.** `IdentityPrincipalResolver.resolve("msteams", aad_oid)` finds the
  Navigator id through the `msteams` identity row **or** the `azure` row FEAT-729 login already writes.
- **G3 — Generic connection commands.** `/connect [<provider>]`, `/disconnect <provider>`, `/connections`, driven by
  `OAuth2ProviderRegistry` through `IntegrationsService` (`channel="msteams"`); `/connect_jira`,
  `/disconnect_jira`, `/jira_status` and the plain `jira` / `integrations` triggers stay as aliases. Adaptive-Card
  `Action.Submit` buttons carry the provider and reach the same handlers.
- **G4 — Teams `ChannelNotifier` for every provider and every event.** One `MSTeamsConnectionNotifier`
  (`channel = "msteams"`) handles `connection.completed`, `connection.revoked` and `connection.refresh_failed`,
  routes each message through the adapter of the bot that owns the conversation, and replaces FEAT-773's
  `MSTeamsJiraNotifierAdapter` and the `app["msteams_jira_oauth_notifier"]` key.
- **G5 — Adaptive-Card connect action.** When any tool in a Teams turn reports needs-auth, the wrapper sends one
  card per provider with a **Connect** button (or the device-code instructions), minted through
  `IntegrationsService.start_connect(channel="msteams")` so the OAuth state carries the conversation reference.
- **G6 — No regression for the production Teams Jira flow:** an authenticated user who connected Jira before
  FEAT-773's cutover keeps the connection (FEAT-773 legacy read), the success page and the proactive "connected"
  message behave as today.

### Non-Goals (explicitly out of scope)

- Anything FEAT-773 owns: principal keys, `AbstractOAuth2Manager`, descriptors, `ConnectionEventPublisher`,
  `AuthRequiredPayload`, `/api/v1/connections*`, the generic OAuth callback and the legacy-key window.
- Telegram generic commands and its legacy cutover — **S-2**; web Connections panel, WS push, automatic retry
  after connect, Slack notifier and first-link fix — **S-3a**; CLI / local MCP — **S-4** (FEAT-774).
- Automatic re-execution of the failed tool after a Teams connect completes (the completion message tells the
  user to ask again; auto-retry is the S-3a design and can be adopted later).
- The MSAgentSDK lane (`integrations/msagentsdk/`, native OAuthCard + `CredentialRequired` resume) — unchanged.
- Fixing `AbstractClient._execute_tool`'s loss of `ToolResult.metadata` for the LLM (`clients/base.py` is the
  foundation and needs a separate discussion; see §8 Q3). This spec routes around it with a request-scoped
  collector instead.
- Teams message extensions / Teams SSO for third-party providers (Bot Framework OAuth connection per provider).
- Group-chat / channel-conversation connect: connect commands answer only in **personal** (1:1) conversations
  (see §7); in a group they reply with a "message me directly" hint.

---

## 2. Architectural Design

### Overview

All Teams-specific code stays in `ai-parrot-integrations/…/msteams/`; core gains exactly one small module
(the needs-auth collector) and one call in `ToolManager`; the server resolver gains a provider alias.

**Principal (M1).** `MSTeamsPrincipalSource.principal_for_turn(turn_context)` reads the FEAT-729
`MSTeamsUserSession` through the wrapper's `MSTeamsSessionStore` (never triggers an exchange — same rule as
`_effective_user_id`, wrapper.py:351) and returns a FEAT-773 `Principal` or `None`. The wrapper passes
`permission_context=build_msteams_permission_context(session)` into the orchestrator `context` dict, which
`FormOrchestrator` already forwards verbatim to `agent.ask(**context)` (orchestrator.py:320-324;
`ask(permission_context=…)` verified at bots/base.py:1083). The `PermissionContext` carries
`session.user_id = nav_user_id` (PBAC is evaluated against the Navigator identity) and `channel="msteams"`;
how the AAD id travels for FEAT-773's `OAuthCredentialResolver.resolve(channel, channel_user_id)` is §8 Q1.

**Router arguments (M2).** `MSTeamsCommandRouter` keeps the handler signature `handler(turn_context)` (agent,
auth and knowledge-upload handlers depend on it) and additionally stores the remainder of the command line under
`turn_context.turn_state["msteams.command_args"]`; `command_args(turn_context) -> str` reads it. This makes
`{"command": "/connect jira"}` from a card `Action.Submit` (routed at wrapper.py:601-605, where `activity.text` is
empty) behave exactly like the typed command.

**Commands (M3).** `register_connection_commands(router, *, service_factory, principal_source,
provider_lister)` registers `connect`, `disconnect`, `connections` and the aliases. Every handler:
1. replies with the group-conversation hint unless `conversation.conversation_type == "personal"`;
2. resolves the principal (M1) — `None` ⇒ "Please `/login` first" (or, with the auth lane disabled, "Connections
   need Navigator sign-in; ask an operator to enable it") and **no OAuth state is created**;
3. calls `IntegrationsService` *(FEAT-773)* with `channel="msteams"` and `principal`:
   `/connect <p>` → `status` (already connected ⇒ account reply) else `start_connect(..., extra_state=
   {"conversation_reference": <serialized ref>, "bot_app_id": <app id>})` → Connect card;
   `/connect` with no provider → provider-picker card (one `Action.Submit {"command": "/connect <id>"}` per
   registered provider); `/disconnect <p>` → `disconnect`; `/connections` → status card for every provider.
PBAC denials from `start_connect` / `disconnect` are rendered as a plain "not allowed" reply.
`jira_commands.py` is reduced to the aliases (`connect_jira` → `/connect jira`, `jira_status` →
`/connections jira`, menus → `/connections`) and keeps its public `register_jira_commands` name for callers.

**Notifier (M4).** `MSTeamsConnectionNotifier` implements the FEAT-773 `ChannelNotifier` Protocol:
- holds a map `bot_app_id → BotFrameworkAdapter`; each `MSTeamsAgentWrapper` calls `attach(app_id, adapter)`;
  one instance per aiohttp app at `app["msteams_connection_notifier"]`, registered once in FEAT-773's
  `ChannelNotifierRegistry` (replacing `MSTeamsJiraNotifierAdapter`);
- target conversation: `state_payload["extra"]["conversation_reference"]` when present (callback path), else the
  `MSTeamsConversationRefStore` entry for `event.user_id` (revoke / refresh paths);
- the adapter is chosen by `bot_app_id` from the state, else by the conversation reference's `bot.id`
  (`28:<app id>`); unknown app id ⇒ warning, no send;
- messages per kind: completed → "<Provider> connected as **<display_name>**. Ask again to use it.";
  revoked → "<Provider> disconnected."; refresh_failed → "<Provider> access expired — `/connect <id>` to
  reconnect." (never token material, never `event.reason` verbatim beyond the FEAT-773 redacted reason);
- every failure is logged, never raised (FEAT-773 publisher contract).
`MSTeamsConversationRefStore` keeps the latest **personal** conversation reference per `(nav_user_id)` in Redis
(`msteams:convref:{nav_user_id}`, TTL 30 days, refreshed on each authenticated personal turn by the wrapper).

**Needs-auth collector (M5, core).** `parrot/auth/pending.py`: `collect_auth_requirements()` is a context manager
that binds a fresh list on a `ContextVar` and yields it; `record_auth_requirement(payload)` appends when a
collector is bound (no-op otherwise). `ToolManager.execute_tool` calls it in the needs-auth branch FEAT-773 M5
unifies (both `AuthorizationRequired` and `CredentialRequired`). The list object is shared by reference, so
appends made inside tasks spawned from the bound context are visible to the caller.

**Connect card (M6).** The wrapper wraps the orchestrator call in `collect_auth_requirements()`. After sending
the agent's response, for each distinct `payload.provider` it calls the M3 connect routine (same principal,
same `extra_state`) and sends the Connect card — the tool-produced `auth_url` is **not** used, because its OAuth
state lacks the conversation reference and bot app id. `auth_kind == "device_code"` renders `user_code` +
`verification_uri` instead of `Action.OpenUrl`. No principal ⇒ the "/login first" reply once per turn.

**Server (M7).** FEAT-773's `IdentityPrincipalResolver` gains a channel → identity-provider alias table
`{"msteams": ("msteams", "azure")}` tried in order; `canonical_identity` = the AAD oid. `integrations/manager.py
::_start_msteams_bot` stops gating Teams connections on `config.jira_client_id`: the wrapper always registers
connection commands when `app` exposes the FEAT-773 provider registry with at least one provider.

### Component Diagram

```
Teams activity ─► MSTeamsAgentWrapper.on_message_activity
   │  FEAT-729 MSTeamsAuthStrategy.ensure_authenticated → MSTeamsUserSession(nav_user_id, aad_object_id, tenant_id)
   │  MSTeamsConversationRefStore.save(nav_user_id, ref)             (personal turns only)          [M4]
   │
   ├─ "/connect jira" (text or card Submit) ─► MSTeamsCommandRouter (args → turn_state)            [M2]
   │        └─► connect handler ─► MSTeamsPrincipalSource.principal_for_turn ─► Principal | None     [M1, M3]
   │                 └─► IntegrationsService.start_connect(channel="msteams", principal,
   │                          extra_state={conversation_reference, bot_app_id})   (FEAT-773)
   │                 └─► Connect card (Action.OpenUrl)
   │
   └─ chat ─► with collect_auth_requirements():                                                    [M5]
                FormOrchestrator.process_message(context={user_id, session_id, permission_context}) [M1]
                   └─► agent.ask ─► ToolManager.execute_tool ─► needs-auth ─► record_auth_requirement
              send response; for each provider in collector ─► M3 connect routine ─► Connect card  [M6]

IdP consent ─► FEAT-773 generic callback ─► ConnectionEventPublisher
                 └─► ChannelNotifierRegistry.get("msteams") = MSTeamsConnectionNotifier             [M4]
                        ref = state.extra.conversation_reference  or  ConvRefStore.get(user_id)
                        adapter = by bot_app_id / ref.bot.id ─► continue_conversation(ref, send text)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `msteams/wrapper.py::MSTeamsAgentWrapper` | modifies | principal + `permission_context` into the orchestrator context; collector around the agent call; Connect cards after the response; conv-ref save; notifier `attach`; connection-command registration replaces the `oauth_manager`-gated Jira block (wrapper.py:202-221) |
| `msteams/commands/__init__.py::MSTeamsCommandRouter` | modifies | stash command args in `turn_state`; handler signature unchanged |
| `msteams/commands/jira_commands.py` | modifies (shrink) | aliases onto M3; `_get_user_id` AAD keying removed |
| `msteams/oauth_callback.py::MSTeamsOAuthNotifier`, `handle_msteams_jira_callback` | replaces | superseded by `MSTeamsConnectionNotifier`; whatever FEAT-773 left of the Teams callback helper is deleted |
| `msteams/auth.py::MSTeamsSessionStore`, `MSTeamsUserSession` | uses | read-only source of the principal |
| `msteams/dialogs/orchestrator.py::FormOrchestrator.process_message` | uses | already forwards `context` to `agent.ask` |
| `parrot/tools/manager.py::ToolManager.execute_tool` | modifies | one `record_auth_requirement(...)` call in the FEAT-773 unified needs-auth branch |
| `parrot/auth/permission.py::build_principal_context`, `PermissionContext` | uses | Teams permission context |
| FEAT-773 `IntegrationsService`, `OAuth2ProviderRegistry`, `ChannelNotifierRegistry`, `Principal`, `AuthRequiredPayload` | uses | consumed, not changed |
| FEAT-773 `services/identity_principal.py::IdentityPrincipalResolver` | modifies | `msteams → (msteams, azure)` alias |
| `integrations/manager.py::IntegrationManager._start_msteams_bot` | modifies | connections not gated on `jira_client_id` |

### Data Models

```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/connections.py  (new)
class TeamsConnectState(BaseModel):
    """What the Teams channel puts in IntegrationsService.start_connect(extra_state=...)."""
    conversation_reference: Dict[str, Any]   # ConversationReference.serialize()
    bot_app_id: str                          # MSTeamsAgentConfig.client_id of the bot that issued the card
```

No new database tables. Redis key: `msteams:convref:{nav_user_id}` → JSON conversation reference (TTL 30 d).

### New Public Interfaces

```python
# parrot/auth/pending.py  (core, new)
@contextmanager
def collect_auth_requirements() -> Iterator[List[AuthRequiredPayload]]: ...
def record_auth_requirement(payload: AuthRequiredPayload) -> None: ...

# parrot/integrations/msteams/connections.py  (new)
class MSTeamsPrincipalSource: principal_for_turn(turn_context) -> Optional[Principal]
def build_msteams_permission_context(session: MSTeamsUserSession) -> PermissionContext
class MSTeamsConversationRefStore: save(nav_user_id, ref) / get(nav_user_id)
class MSTeamsConnectionNotifier:  channel = "msteams"; attach(app_id, adapter); notify(event, state_payload)
def connect_card(...) / device_code_card(...) / provider_picker_card(...) / connections_status_card(...)

# parrot/integrations/msteams/commands/connect_commands.py  (new)
def register_connection_commands(router, *, connect: TeamsConnector) -> None
class TeamsConnector: connect / disconnect / status / list   (shared by M3 commands and M6 cards)

# parrot/integrations/msteams/commands/__init__.py
def command_args(turn_context) -> str
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Teams principal source + permission context | yes | read-only session lookup mirroring `_effective_user_id` (wrapper.py:351-368); `None` on unauthenticated/expired; `build_principal_context(nav_user_id, channel="msteams", tenant_id=session.tenant_id)` | — |
| M2: Router command args | yes | `turn_state["msteams.command_args"]`; signature unchanged | — |
| M3: Generic connection commands + `TeamsConnector` | no | — | fail-closed rules, personal-only rule, alias mapping and PBAC rendering are behaviour decisions applied across every provider |
| M4: `MSTeamsConnectionNotifier` + conv-ref store | yes | Protocol from FEAT-773; adapter routing rule and messages fixed in §2; never raises | — |
| M5: Core needs-auth collector | yes | ContextVar holding a mutable list; no-op when unbound; one call in `ToolManager` | — |
| M6: Adaptive-Card connect action | no | — | wrapper turn-flow change (ordering vs. response, dedup, device-code) touches the live Teams message path |
| M7: Server resolver alias + manager wiring | yes | alias table `{"msteams": ("msteams", "azure")}`; first hit wins | — |
| M8: Docs | yes | outline below | — |

### Module 1: Teams principal source and permission context
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/connections.py` (new); `msteams/wrapper.py` (modify)
- **Responsibility**: map the FEAT-729 session to a FEAT-773 `Principal`; build the Teams `PermissionContext`;
  pass it through the orchestrator context on every agent call site of the wrapper that uses
  `"user_id": await self._effective_user_id(...)`.
- **Depends on**: FEAT-773 M1 (`Principal`).
- **Interface Skeleton**:
  ```python
  # msteams/connections.py  (new)
  class MSTeamsPrincipalSource:
      """Principal for the speaking Teams user, from the cached FEAT-729 session; never runs an exchange."""
      def __init__(self, store: Optional[MSTeamsSessionStore]) -> None: ...   # verified: auth.py:102
      async def principal_for_turn(self, turn_context: TurnContext) -> Optional[Principal]:
          """None unless session.authenticated, nav_user_id set and not store.is_expired(session)
          (same rule as MSTeamsAgentWrapper._effective_user_id, wrapper.py:351-368).
          channel_user_id = canonical_identity = session.aad_object_id or session.teams_user_id."""

  def build_msteams_permission_context(session: MSTeamsUserSession) -> PermissionContext:
      """build_principal_context(session.nav_user_id, channel="msteams", tenant_id=session.tenant_id)."""  # verified: permission.py:166
  ```
  ```python
  # msteams/wrapper.py  (modifies) — every orchestrator call site
  context={
      "user_id": await self._effective_user_id(turn_context, turn_context.activity.from_property.id),  # verified: wrapper.py:813-815
      "session_id": conversation_id,
      # NEW: only when principal_for_turn() is not None
      "permission_context": build_msteams_permission_context(session),
  }
  ```

### Module 2: Router command arguments
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py` (modify)
- **Responsibility**: store the text after the command word in `turn_context.turn_state` before calling the handler,
  in both `try_dispatch` and `try_dispatch_plain`; expose `command_args()`.
- **Depends on**: none.
- **Interface Skeleton**:
  ```python
  COMMAND_ARGS_KEY = "msteams.command_args"
  def command_args(turn_context: "TurnContext") -> str:
      """Arguments of the dispatched command ('' when none)."""
  class MSTeamsCommandRouter:                                                   # verified: commands/__init__.py:30
      async def try_dispatch(self, text: str, turn_context: "TurnContext") -> bool:   # verified: :74
          """parts = text.split(maxsplit=1); turn_state[COMMAND_ARGS_KEY] = parts[1] if len(parts) > 1 else ''."""
  ```

### Module 3: Generic connection commands
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/connect_commands.py` (new); `msteams/commands/jira_commands.py` (modify → aliases)
- **Responsibility**: `TeamsConnector` (principal + service calls + card building, reused by M6) and the command
  registrations described in §2 Overview "Commands".
- **Depends on**: M1, M2, M4 (card builders live in `connections.py`); FEAT-773 M6 (`IntegrationsService`).
- **Interface Skeleton**:
  ```python
  class TeamsConnector:
      def __init__(self, *, principal_source: MSTeamsPrincipalSource, service_factory: Callable[[], Any],
                   provider_ids: Callable[[], List[str]], bot_app_id: str, auth_enabled: bool) -> None: ...
      async def connect(self, turn_context: TurnContext, provider_id: str) -> None:
          """Fail closed without principal; status() first; else start_connect(principal.user_id, provider_id,
          channel="msteams", principal=principal, extra_state=TeamsConnectState(...).model_dump()) → connect_card."""
      async def disconnect(self, turn_context: TurnContext, provider_id: str) -> None: ...
      async def status(self, turn_context: TurnContext, provider_id: Optional[str] = None) -> None: ...
      async def pick_provider(self, turn_context: TurnContext) -> None: ...

  def register_connection_commands(router: "MSTeamsCommandRouter", *, connector: TeamsConnector) -> None:
      """connect, disconnect, connections + aliases connect_jira, disconnect_jira, jira_status, plain 'jira', 'integrations', 'connections'."""

  # jira_commands.py (modifies)
  def register_jira_commands(router, connector: TeamsConnector) -> None:      # verified: jira_commands.py:350 (signature changes: oauth_manager, nav_user_id_resolver → connector)
  ```

### Module 4: Teams `ChannelNotifier` and conversation-reference store
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/connections.py` (new, same file as M1); `msteams/oauth_callback.py` (delete `MSTeamsOAuthNotifier` and any surviving Teams callback helper); `msteams/wrapper.py` (attach + conv-ref save); `integrations/core/auth/notifiers.py` *(FEAT-773)* (drop `MSTeamsJiraNotifierAdapter`)
- **Responsibility**: §2 Overview "Notifier".
- **Depends on**: FEAT-773 M4 (`ChannelNotifier`, `ConnectionEvent`, `ChannelNotifierRegistry`).
- **Interface Skeleton**:
  ```python
  class MSTeamsConversationRefStore:
      def __init__(self, redis: Any, ttl_s: int = 30 * 86400) -> None: ...
      async def save(self, nav_user_id: str, conversation_reference: Dict[str, Any]) -> None: ...
      async def get(self, nav_user_id: str) -> Optional[Dict[str, Any]]: ...

  class MSTeamsConnectionNotifier:
      channel = "msteams"
      def __init__(self, ref_store: Optional[MSTeamsConversationRefStore]) -> None: ...
      def attach(self, app_id: str, adapter: "BotFrameworkAdapter") -> None: ...
      async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None:
          """Pick ref (state extra → ref store), adapter (bot_app_id → ref['bot']['id'] minus '28:'),
          adapter.continue_conversation(ConversationReference.deserialize(ref), cb, app_id); log, never raise."""  # pattern verified: oauth_callback.py:119-142
  ```

### Module 5: Core needs-auth collector
- **Path**: `packages/ai-parrot/src/parrot/auth/pending.py` (new); `packages/ai-parrot/src/parrot/tools/manager.py` (modify)
- **Responsibility**: §2 Overview "Needs-auth collector".
- **Depends on**: FEAT-773 M5 (`AuthRequiredPayload`, unified branch in `execute_tool`).
- **Interface Skeleton**:
  ```python
  _PENDING_AUTH: ContextVar[Optional[List[AuthRequiredPayload]]] = ContextVar("parrot_pending_auth", default=None)
  @contextmanager
  def collect_auth_requirements() -> Iterator[List[AuthRequiredPayload]]:
      """Bind a fresh list; reset the ContextVar token on exit."""
  def record_auth_requirement(payload: AuthRequiredPayload) -> None:
      """Append when bound; otherwise no-op."""
  # tools/manager.py — inside the FEAT-773 unified needs-auth branch (today: `except AuthorizationRequired as auth_exc:`, manager.py:2273)
  #   record_auth_requirement(payload)   # before returning the ToolResult
  ```

### Module 6: Adaptive-Card connect action
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` (modify); card builders in `msteams/connections.py`
- **Responsibility**: wrap each orchestrator call in `collect_auth_requirements()`; after the response is sent,
  dedupe by provider and call `TeamsConnector.connect(turn_context, provider)` per provider (device-code payloads
  → `device_code_card`); at most one "/login first" reply per turn.
- **Depends on**: M3, M5.
- **Interface Skeleton**:
  ```python
  # msteams/wrapper.py (modifies)
  async def _offer_connections(self, turn_context: TurnContext, pending: List[AuthRequiredPayload]) -> None:
      """Dedupe by provider; device_code → device_code_card; else self._connector.connect(...)."""
  # msteams/connections.py
  def connect_card(provider_display: str, auth_url: str) -> Dict[str, Any]: ...      # shape verified: jira_commands.py:52-79
  def device_code_card(provider_display: str, user_code: str, verification_uri: str, expires_in: Optional[int]) -> Dict[str, Any]: ...
  def provider_picker_card(providers: List[Tuple[str, str]]) -> Dict[str, Any]: ...  # Action.Submit {"command": "/connect <id>"}
  def connections_status_card(rows: List[IntegrationDescriptor]) -> Dict[str, Any]: ...
  ```

### Module 7: Server resolver alias and manager wiring
- **Path**: `packages/ai-parrot-server/src/parrot/services/identity_principal.py` *(FEAT-773, modify)*; `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` (modify)
- **Responsibility**: alias lookup; `_start_msteams_bot` builds the wrapper without requiring `jira_client_id`;
  creates `app["msteams_connection_notifier"]` once and registers it in `ChannelNotifierRegistry`.
- **Depends on**: FEAT-773 M8.
- **Interface Skeleton**:
  ```python
  # services/identity_principal.py (FEAT-773 file, modifies)
  _CHANNEL_IDENTITY_PROVIDERS: Dict[str, Tuple[str, ...]] = {"msteams": ("msteams", "azure")}
  #   resolve(channel, id): for provider in _CHANNEL_IDENTITY_PROVIDERS.get(channel, (channel,)):
  #       IdentityStore.find_user_by_provider_account(provider, id)   # verified: navigator_auth 0.28.7 identity/store.py:333
  ```

### Module 8: Docs
- **Path**: `docs/integrations/msteams-connections.md` (new)
- **Responsibility**: commands, personal-only rule, `/login` prerequisite, multi-bot notifier, operator checklist
  (registered redirect URIs, `navigator_auth_url`), migration note for `/connect_jira` users.
- **Depends on**: M3, M4.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_principal_for_turn_authenticated` | M1 | session with nav id → `Principal(channel="msteams", channel_user_id=aad, canonical_identity=aad)` |
| `test_principal_for_turn_unauthenticated_or_expired_is_none` | M1 | no session / expired / no auth lane → `None` |
| `test_permission_context_reaches_ask` | M1 | orchestrator `context` carries `permission_context` with `channel="msteams"` and `user_id=nav id` |
| `test_router_stashes_args_text_and_card` | M2 | `/connect jira` typed and via card `value.command` → `command_args() == "jira"`; existing handlers unaffected |
| `test_connect_requires_principal` | M3 | no principal → "/login first", `start_connect` not called |
| `test_connect_personal_only` | M3 | group conversation → hint, no service call |
| `test_connect_calls_start_connect_with_teams_state` | M3 | `channel="msteams"`, `principal`, `extra_state` has `conversation_reference` + `bot_app_id` |
| `test_connect_already_connected` | M3 | `status` active → account reply, no new state |
| `test_jira_aliases_map_to_generic` | M3 | `/connect_jira`, `/disconnect_jira`, `/jira_status`, `jira`, `integrations` route to the generic handlers |
| `test_pbac_denied_renders_message` | M3 | `start_connect` raising the FEAT-773 PBAC denial → "not allowed" reply |
| `test_notifier_completed_uses_state_ref` | M4 | callback state ref + `bot_app_id` → that adapter's `continue_conversation` |
| `test_notifier_refresh_failed_uses_ref_store` | M4 | no state → ref store lookup by `event.user_id` |
| `test_notifier_multi_bot_routing` | M4 | two attached adapters; ref `bot.id = 28:<app2>` → adapter 2 |
| `test_notifier_never_raises` | M4 | adapter raising / missing ref / unknown app id → logged, no exception |
| `test_conv_ref_saved_on_personal_authenticated_turn_only` | M4 | group or unauthenticated turn → no save |
| `test_collector_unbound_is_noop` | M5 | `record_auth_requirement` without collector does nothing |
| `test_collector_sees_appends_from_child_tasks` | M5 | `asyncio.gather` children append into the bound list |
| `test_toolmanager_records_needs_auth` | M5 | both `AuthorizationRequired` and `CredentialRequired` recorded once each |
| `test_offer_connections_dedupes_and_mints_own_url` | M6 | two payloads same provider → one card; URL from `start_connect`, not `payload.auth_url` |
| `test_offer_connections_device_code_card` | M6 | `auth_kind="device_code"` → code card, no `start_connect` |
| `test_resolver_alias_msteams_falls_back_to_azure` | M7 | no `msteams` row, `azure` row present → principal |

### Integration Tests
| Test | Description |
|---|---|
| `test_teams_connect_end_to_end` | `/connect jira` → card URL → FEAT-773 callback with the state → `MSTeamsConnectionNotifier` sends "connected" through the issuing bot's adapter |
| `test_teams_tool_needs_auth_card` | agent tool raises `AuthorizationRequired` in a Teams turn → response sent, then one Connect card |
| `test_teams_preexisting_jira_connection_kept` | authenticated user with a legacy Jira grant (FEAT-773 legacy read) → `/jira_status` reports connected, no re-consent |

### Validation Contract

tests:
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connect_commands.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connection_notifier.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_needs_auth_card.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_jira_commands.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_wrapper_jira.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_lane.py
- packages/ai-parrot-integrations/tests/integrations/msteams/test_agent_commands.py
- packages/ai-parrot/tests/auth/test_pending_auth.py
markers: none

> `test_msteams_oauth_callback.py` is rewritten or deleted together with `MSTeamsOAuthNotifier` (M4); the task
> that deletes it must move its surviving assertions into `test_msteams_connection_notifier.py`.

### Test Data / Fixtures
```python
@pytest.fixture
def teams_session():  # authenticated FEAT-729 session
    return MSTeamsUserSession(user_key="aad-1", teams_user_id="29:x", aad_object_id="aad-1",
                              tenant_id="t-1", nav_user_id="42", authenticated=True)

@pytest.fixture
def personal_turn_context(teams_session): ...   # botbuilder TurnContext mock, conversation_type="personal",
                                                # bot.id="28:app-1"; turn_state is a real dict
```

---

## 5. Acceptance Criteria

- [ ] **AC-1 (G1)** An authenticated Teams turn passes `permission_context` with `channel="msteams"` and the Navigator id to `agent.ask`; an unauthenticated turn passes none, and no code path keys a credential by the AAD id or `from_property.id`.
- [ ] **AC-2 (G1, U3)** Every connect / disconnect path without a principal replies with the sign-in instruction and creates no OAuth state (`start_connect` not called).
- [ ] **AC-3 (G2)** `IdentityPrincipalResolver.resolve("msteams", <oid>)` returns the principal from an `azure` identity row when no `msteams` row exists.
- [ ] **AC-4 (G3)** `/connect`, `/connect <p>`, `/disconnect <p>`, `/connections` work for every provider in `OAuth2ProviderRegistry`; typed commands and card `Action.Submit` buttons behave identically; `/connect_jira`, `/disconnect_jira`, `/jira_status`, `jira`, `integrations` still work as aliases.
- [ ] **AC-5 (G3)** Connect commands answer only in personal conversations; in a group or channel they reply with a "message me directly" hint and make no service call.
- [ ] **AC-6 (G4)** `MSTeamsConnectionNotifier` is the only notifier registered for `channel="msteams"`; it delivers `connection.completed`, `connection.revoked` and `connection.refresh_failed`; with two Teams bots on one app each message goes through the adapter of the bot that owns the conversation; `app["msteams_jira_oauth_notifier"]` and `MSTeamsOAuthNotifier` no longer exist in `packages/`.
- [ ] **AC-7 (G4)** A notifier failure (adapter error, missing reference, unknown bot) is logged and never fails the callback or the refresh.
- [ ] **AC-8 (G5)** A Teams turn in which a tool reports needs-auth sends the agent's response, then exactly one card per provider; the card URL comes from `start_connect(channel="msteams")` with the conversation reference in its state; device-code payloads render the code and verification URI.
- [ ] **AC-9 (G5)** `record_auth_requirement` is a no-op outside `collect_auth_requirements()`; non-Teams callers of `ToolManager` see no behaviour change.
- [ ] **AC-10 (G6)** An authenticated user with a pre-cutover Jira grant gets `/jira_status` = connected without re-consent; the browser success page and the proactive "connected" message are still shown after a Teams-initiated connect.
- [ ] **AC-11** `docs/integrations/msteams-connections.md` exists and covers commands, the `/login` prerequisite, personal-only rule and multi-bot routing.
- [ ] **AC-12** The Validation Contract passes; no `print`, no `requests`/`httpx`, Pydantic v2 only; `ruff check` clean on touched files; no edit to `parrot/clients/base.py`.

---

## 6. Codebase Contract

> Verified against `dev` @ `145a6c603` (2026-10-30). Names marked *(FEAT-773)* come from the FEAT-773 spec and
> must be re-verified against the merged FEAT-773 code by `/sdd-task`; they do not exist on `dev` today.

### Verified Imports
```python
from botbuilder.core import TurnContext                                         # msteams/commands/jira_commands.py:32
from botbuilder.schema import Activity, Attachment, ConversationReference         # jira_commands.py:207; oauth_callback.py:120
from parrot.outputs.cards.spec import DEFAULT_ADAPTIVE_CARD_VERSION               # jira_commands.py:33
from parrot.auth.permission import build_principal_context, PermissionContext    # auth/permission.py:166
from parrot.auth.exceptions import AuthorizationRequired                          # tools/manager.py:19
from parrot.integrations.msteams.auth import MSTeamsSessionStore, MSTeamsUserSession, MSTeamsAuthStrategy, user_key  # auth.py:29,45,102,256
from parrot.integrations.msteams.commands import MSTeamsCommandRouter             # commands/__init__.py:30
from parrot.services.identity_mapping import IdentityMappingService               # used at telegram/wrapper.py:606
# FEAT-773 (after merge):
# from parrot.auth.principal import Principal, resolve_principal
# from parrot.auth.oauth2.events import ChannelNotifier, ChannelNotifierRegistry, ConnectionEvent
# from parrot.auth.credentials import AuthRequiredPayload
# from parrot.auth.oauth2.service import IntegrationsService
```

### Existing Class Signatures
```python
# msteams/commands/__init__.py
class MSTeamsCommandRouter:                                                       # :30
    def register(self, command: str, handler: Callable) -> None                   # :56  (normalizes lstrip("/"))
    async def try_dispatch(self, text: str, turn_context) -> bool                 # :74  handler(turn_context) at :97
    async def try_dispatch_plain(self, text: str, turn_context) -> bool           # :111 handler(turn_context) at :138

# msteams/commands/jira_commands.py
def _connect_jira_card(auth_url: str) -> Dict[str, Any]                           # :52  Action.OpenUrl card
def _get_user_id(turn_context) -> str                                             # :129 aad_object_id or from_property.id
def _get_conversation_reference(turn_context) -> Dict[str, Any]                   # :176 TurnContext.get_conversation_reference(...).serialize()
async def connect_jira_handler(turn_context, oauth_manager, nav_user_id_resolver=None) -> None  # :224
def register_jira_commands(router, oauth_manager, nav_user_id_resolver=None) -> None            # :350 registers connect_jira, disconnect_jira, jira_status, jira, integrations

# msteams/oauth_callback.py
class MSTeamsOAuthNotifier:                                                       # :89
    def __init__(self, adapter: BotFrameworkAdapter, app_id: str) -> None         # :100
    async def notify_connected(self, conversation_ref_dict, display_name, site_url) -> None   # :105; continue_conversation(conv_ref, cb, app_id) :136
    async def notify_failure(self, conversation_ref_dict, reason) -> None         # :144
async def handle_msteams_jira_callback(request, token_set, state_payload) -> web.Response    # :182; identity write gated on app.get("identity_mapping_service") :261

# msteams/auth.py
def user_key(turn_context) -> str                                                 # :29  aad_object_id or from.id
@dataclass class MSTeamsUserSession: user_key, teams_user_id, aad_object_id, tenant_id, display_name,
    nav_user_id, nav_session_token, nav_email, authenticated, authenticated_at, external_expires_at, metadata  # :45-63
class MSTeamsSessionStore:                                                        # :102
    def is_expired(self, session) -> bool                                         # :130
    async def get_or_create(self, turn_context) -> MSTeamsUserSession             # :134
class MSTeamsAuthStrategy:                                                        # :256
    async def ensure_authenticated(self, turn_context) -> MSTeamsUserSession      # :301; exchange(provider="azure") → navigator-auth writes the azure identity row

# msteams/wrapper.py
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler):                       # :100
    def __init__(self, agent, config, app, forms_directory=None, voice_config=None, oauth_manager=None)  # :132-140
    #   Jira block :202-221 (register_jira_commands; app["msteams_jira_oauth_notifier"] = MSTeamsOAuthNotifier(...) :215)
    #   self._session_store :224; self._auth (MSTeamsAuthStrategy) :230-239; register_auth_commands :239
    async def _effective_user_id(self, turn_context, fallback: str) -> str        # :351
    #   card Submit → command router :601-605; text commands :715-723; orchestrator call :810-816

# msteams/dialogs/orchestrator.py
class FormOrchestrator: async def process_message(self, message, conversation_id, context) -> ProcessResult
    #   agent.ask(message, output_mode=OutputMode.MSTEAMS, **(context or {}))     # :320-324; raw_response=response :348

# parrot/bots/base.py
async def ask(self, question, session_id=None, user_id=None, ..., permission_context: Optional[Any] = None, ...)  # :1069, kwarg :1083

# parrot/tools/manager.py
#   except AuthorizationRequired as auth_exc: → ToolResult(status="authorization_required", metadata={auth_url, provider, scopes, tool_name})  # :2273-2290

# parrot/clients/base.py — DO NOT MODIFY
#   _execute_tool: isinstance(result, ToolResult) and status != "error" → return result.result   # :1661-1668 (metadata lost)

# integrations/manager.py
async def _start_msteams_bot(self, name, config)                                  # :347; JiraOAuthManager gated on config.jira_client_id :355; wrapper(oauth_manager=...) :390

# navigator_auth 0.28.7
IdentityStore.find_user_by_provider_account(provider, provider_user_id) -> Optional[Any]   # identity/store.py:333
TokenExchange: store.save_linked_identity(uid, req.provider, ext, userinfo)       # backends/exchange.py:190 (best-effort)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `MSTeamsPrincipalSource` | `MSTeamsSessionStore.get_or_create` / `is_expired` | method call | `auth.py:134`, `:130` |
| Teams `permission_context` | `FormOrchestrator.process_message` → `agent.ask(permission_context=)` | kwargs passthrough | `orchestrator.py:320`, `base.py:1083` |
| `command_args` | `MSTeamsCommandRouter.try_dispatch*` | `turn_context.turn_state` | `commands/__init__.py:97`, `:138` |
| `TeamsConnector` | `IntegrationsService.start_connect/status/disconnect/list_for_principal` *(FEAT-773)* | method call | FEAT-773 spec §3 M6 |
| `MSTeamsConnectionNotifier` | `ChannelNotifierRegistry.register` *(FEAT-773)*; `BotFrameworkAdapter.continue_conversation` | Protocol / method call | FEAT-773 §2; `oauth_callback.py:136` |
| `record_auth_requirement` | `ToolManager.execute_tool` needs-auth branch | function call | `manager.py:2273` |
| resolver alias | `IdentityStore.find_user_by_provider_account` | method call | `navigator_auth/identity/store.py:333` |

### Does NOT Exist (Anti-Hallucination)
- ~~`app["identity_mapping_service"]`~~ — read at `oauth_callback.py:261` and `slack/oauth_callback.py:238`, **never assigned** anywhere in `packages/`; do not rely on it.
- ~~an `msteams` identity row written at Teams `/login`~~ — login writes provider **`azure`** (navigator-auth exchange); only the Jira callback writes `msteams`, and only when the dead key above is set.
- ~~`permission_context` on the Teams agent call~~ — today only `user_id` / `session_id` (wrapper.py:813-816).
- ~~command arguments passed to `MSTeamsCommandRouter` handlers~~ — handlers receive only `turn_context`; agent commands re-read `activity.text` (agent_commands.py:65-67), which is empty for card Submits.
- ~~`ToolResult.metadata` on `AIMessage.tool_calls[*].result`~~ — `_execute_tool` returns `result.result` (clients/base.py:1668).
- ~~`parrot.auth.pending`~~, ~~`collect_auth_requirements`~~, ~~`MSTeamsConnectionNotifier`~~, ~~`MSTeamsConversationRefStore`~~, ~~`TeamsConnector`~~, ~~`connect_commands.py`~~ — created by this spec.
- ~~`Principal`, `IntegrationsService(channel=…)`, `ChannelNotifierRegistry`, `AuthRequiredPayload`, `IdentityPrincipalResolver`, `MSTeamsJiraNotifierAdapter`~~ — FEAT-773, not on `dev` at `145a6c603`.
- ~~a generic `/connect <provider>` command on any channel~~ — none exists (FEAT-773 proposal §3.4).

### Edit Sites (Blueprint Anchors)

Verified against: `145a6c603`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/connections.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/connect_commands.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/auth/pending.py` | CREATE | — | — | — |
| `docs/integrations/msteams-connections.md` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py` | MODIFY | `            await handler(turn_context)` — context: `:97` follows `try:` inside `try_dispatch` (after `handler = self._handlers.get(cmd)`); `:138` inside `try_dispatch_plain` (after `handler = self._handlers.get(text)`) | `commands/__init__.py:97, :138` | 2 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py` | MODIFY | `def register_jira_commands(` | `jira_commands.py:350` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py` | MODIFY (delete notifier) | `class MSTeamsOAuthNotifier:` | `oauth_callback.py:89` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | `        if oauth_manager is not None:` | `wrapper.py:202` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | `        command = submitted_data.get("command")` | `wrapper.py:601` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | `                context={` — 4 call sites (`:523`, `:568`, `:813`, `:1165`); the chat path is `:813`, preceded by `result = await self.form_orchestrator.process_message(` | `wrapper.py:813` | 4 |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | `    async def _run_post_login(self, turn_context: TurnContext, session: Any) -> None:` (insert `_offer_connections` before it) | `wrapper.py:394` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | `            oauth_manager=jira_oauth_manager,` — `:390` is the Teams wrapper (under `wrapper = MSTeamsAgentWrapper(`); `:947` is Slack | `manager.py:390` | 2 |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | `        except AuthorizationRequired as auth_exc:` (FEAT-773 M5 reshapes this branch — re-anchor after merge) | `manager.py:2273` | 1 |
| `packages/ai-parrot-server/src/parrot/services/identity_principal.py` | MODIFY | (unverified — created by FEAT-773 M8; check before use) | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py` | MODIFY | (unverified — created by FEAT-773 M8; remove `MSTeamsJiraNotifierAdapter`) | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Card shape and send path: `_connect_jira_card` / `_send_adaptive_card` (jira_commands.py:52-79, :198-217); reuse
  `DEFAULT_ADAPTIVE_CARD_VERSION`.
- Proactive messaging: `ConversationReference.deserialize` + `adapter.continue_conversation(ref, cb, app_id)`
  inside a broad `except` that logs (oauth_callback.py:119-142).
- Session reads never trigger an exchange (`_effective_user_id`, wrapper.py:351); only `/login` and the auth gate
  call `ensure_authenticated`.
- `nav_user_id` is never derived from `user_id` / the AAD id (FEAT-729 review, issue `187ce3fe3b93`, oauth_callback.py:249-256).
- `self.logger`, Pydantic v2, async-only I/O; Redis via the app's existing client (`app['redis']`), no new client.

### Known Risks / Gotchas
- **Teams users without the auth lane lose connect.** Today `/connect_jira` works with no Navigator sign-in
  (AAD-keyed). Under FEAT-773 principal keys there is no principal without `/login`; deployments without
  `navigator_auth_url` get the operator message. This is the Teams form of U3 — announce it with the S-2 cutover.
- **Group conversations.** A conversation reference from a channel or group chat would post the "connected"
  message (account name) to everyone; connect is therefore personal-only and the ref store saves personal refs only.
- **Collector and concurrency.** The ContextVar holds a *list*; `asyncio.create_task` copies the context, so
  children share the same list object — appends are visible, rebinding is not. Never rebind inside tools.
- **Duplicate notification.** If the user connects from the card and the generic callback also renders a success
  page, both are expected (browser page + Teams message), as today.
- **Dead identity write today.** `app["identity_mapping_service"]` is never registered, so the current Teams/Slack
  callbacks never write identity rows in production; FEAT-773 M8's adapter must not assume they did. M7's `azure`
  alias is what makes out-of-turn resolution work for Teams. *(Worth a ledger issue against FEAT-773 M8.)*
- **LLM sees `None` for needs-auth tools** (clients/base.py:1668). The card fixes the user path only; the LLM may
  still produce a confusing sentence before the card (§8 Q3).
- **FEAT-773 drift.** Every *(FEAT-773)* signature here is from its spec, not code; `/sdd-task` must re-verify
  after the merge, especially `start_connect`'s `extra_state` and the `ToolManager` needs-auth branch.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `botbuilder-core` / `botbuilder-schema` | already pinned | Adaptive Cards, proactive messaging |
| `navigator-auth` | `>=0.28.7` (installed) | `find_user_by_provider_account` |

No new dependencies.

---

## 8. Open Questions

- [ ] **Q1** How does the AAD id reach FEAT-773's `OAuthCredentialResolver.resolve(channel, channel_user_id)` on a
  Teams tool call? Default proposed: `PermissionContext.session.user_id = nav_user_id` (PBAC) and the resolver, for
  `channel == "msteams"`, treats a numeric id as already-resolved Navigator id. Alternative: carry
  `channel_user_id` in `UserSession.metadata`. Must match whatever FEAT-773 M5 implements — *Owner: Jesus*
- [ ] **Q2** Should the channel-neutral part of the connect commands (provider listing, status text,
  fail-closed messages) live in `integrations/core/auth/` so S-2 (Telegram) and S-3a (Slack) reuse it, or stay
  Teams-local and be extracted later? Default: Teams-local (`TeamsConnector`), extract when S-2 lands — *Owner: Jesus*
- [ ] **Q3** Should `AbstractClient._execute_tool` return the needs-auth `ToolResult` metadata (or a short
  "authorization required for <provider>" string) to the LLM instead of `None`? Touches `clients/base.py`, so it
  needs a separate decision — *Owner: Jesus*
- [ ] **Q4** Consent denial (`?error=` on the callback): FEAT-773's `ConnectionEventKind` has no failure kind, so the
  Teams "authorization failed" proactive message (today `notify_failure`, oauth_callback.py:144) is lost unless
  FEAT-773 publishes one. Accept the loss (the browser page still shows the error) or add a
  `connection.failed` kind to FEAT-773? Default: accept — *Owner: Jesus*
- [x] Teams principal mapping comes from FEAT-729, not a new `TeamsHumanChannel` — *Resolved in FEAT-773
  proposal* (C16, §2.4 "MOOT").
- [x] Unlinked users are asked to `/login` and re-connect; no channel-keyed fallback — *Resolved in FEAT-773 (U3)*.
- [x] Notifier registry is load-bearing, bus additive; core never imports channel code — *Resolved in FEAT-773 (U5)*.

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-775-connections-msteams` off `origin/dev` **after FEAT-773 is
  merged**; the `sdd-coder` engine gives each task its own sub-worktree.
- **Module dependency graph**:
  - M3 → M1 (`MSTeamsPrincipalSource`), M2 (`command_args`), M4 (card builders in `connections.py`)
  - M6 → M3 (`TeamsConnector.connect`), M5 (`collect_auth_requirements`)
  - M8 → M3, M4
  - M1, M2, M4, M5, M7 have no edges between them and can run concurrently.
- **Shared files**: `msteams/wrapper.py` (M1, M3 registration, M4 attach/save, M6) and `msteams/connections.py`
  (M1, M4, M6) — their tasks are serialized on those files.
- **Exclusive resources**: none (no migration, no lockfile change, no native rebuild).
- **Cross-feature dependencies**: **FEAT-773 merged** (hard). Coordinate with S-2 (Telegram) on §8 Q2 if it is
  in flight at the same time.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document for this slug; the source is the FEAT-773
> proposal, whose design research ran for FEAT-773) · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-30 | Jesus Lara (with Claude Opus 5.5) | Initial draft from FEAT-773 proposal §6 S-3b + spec §1 Non-Goals |

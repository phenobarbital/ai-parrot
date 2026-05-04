# Feature Specification: Cross-Repository JiraToolkit OAuth2 3LO (Web AgentChat)

**Feature ID**: FEAT-144
**Date**: 2026-05-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Source brainstorm**: `sdd/proposals/cross-repository-jiratoolkit-oauth2-3lo.brainstorm.md` (Recommended Option B)

---

## 1. Motivation & Business Requirements

### Problem Statement

`JiraToolkit` already runs in `oauth2_3lo` mode and is fully wired into the **Telegram**
integration (`/connect_jira` → inline button → `/api/auth/jira/callback` → token in
Redis → toolkit pre-execute resolves token per user). Web users of the Svelte
**`AgentChat`** component in the `navigator-frontend-next` repository have **no
equivalent path**: there is no UI to initiate OAuth2, no popup callback handling, and
no per-user toolkit registration mechanism reachable from the browser.

The web channel additionally needs:

1. A **discovery surface** — a "+ Integrations" menu inside `AgentChat` that lists
   the OAuth2-capable toolkits the current user is allowed to connect (initially
   Jira, by design extensible to Slack, GitHub, Google Drive, Confluence…).
2. A **persistent registration** model — when a user connects Jira on agent X, that
   choice must survive Redis flushes and new browser sessions.

Today the only workaround is to also authenticate via Telegram — not a viable UX for
a web-first product.

### Goals
- Allow a web user authenticated via `navigator-auth` to connect their Jira account
  through a popup OAuth2 3LO flow initiated from inside `AgentChat`.
- Persist the per-user Jira credential durably so it survives Redis flushes and
  browser sessions, while keeping Redis as the fast-path cache.
- Persist per-`(user, agent, toolkit)` enablement so `JiraToolkit` is auto-rehydrated
  into the agent's `ToolManager` on every cold session — only for agents the user
  has explicitly enabled it on.
- Surface `AuthorizationRequired` exceptions raised at tool-call time as a
  structured chat envelope that AgentChat can render as an inline "Connect Jira"
  pill.
- Establish an `OAuth2ProviderRegistry` so future OAuth2-based toolkits register
  themselves with one call and inherit the same UI, persistence, popup, and
  envelope plumbing.
- Keep the Telegram OAuth2 3LO flow byte-for-byte unchanged.

### Non-Goals (explicitly out of scope)
- Cross-channel credential sharing (a user who connects Jira on web does NOT
  automatically gain a Telegram connection, and vice-versa). Same Atlassian account,
  separate Redis rows.
- Provider-side token revocation on disconnect (`POST .../oauth/token/revoke`).
  Disconnect deletes Redis row + DocumentDB row + session entry only.
- Vault mirroring of web-channel tokens. Telegram retains its Vault mirror; web
  does not.
- Streaming / SSE response transport for the `auth_required` envelope. Single
  response body.
- Iframe-embedded OAuth UX (Atlassian sets `X-Frame-Options`, so it is non-viable).
- Rejected from brainstorm Option A (Jira-specific plumbing): hardcoded
  Jira-only menu and per-provider duplicated endpoints — see brainstorm Option A
  for context.
- Rejected from brainstorm Option C (always-on lazy injection): JiraToolkit will
  NOT be auto-loaded into every agent — per-agent opt-in is required.
- Multi-tab live synchronisation of "connected" state via SSE / WebSocket. v1
  accepts that the second tab needs a manual refresh.

---

## 2. Architectural Design

### Overview

A new backend package `parrot/integrations/oauth2/` introduces an
`OAuth2ProviderRegistry` and an `IntegrationsService`. JiraToolkit is the first
registered provider (`JiraOAuth2Provider`), thin-wrapping the existing
`JiraOAuthManager` and `JiraToolkit`. A new `IntegrationsHandler` exposes
`/api/v1/agents/integrations/{agent_id}` family endpoints (list, connect-init,
enable, disconnect), each PBAC-checked and origin-validated.

The existing `/api/auth/jira/callback` route is **extended**, not replaced: a new
branch on `extra_state["channel"]` distinguishes `"telegram"` (current behaviour
preserved verbatim) from `"web"` (new behaviour: render an HTML page that posts a
message to `window.opener` and self-closes). The post-message target origin is
validated server-side against `WEB_OAUTH_ALLOWED_ORIGINS` (a new navconfig key).

`AgentTalk.post` wraps agent invocation in `try/except AuthorizationRequired` and
translates the exception into a single-body `AuthRequiredEnvelope`
(`{type: "auth_required", provider, auth_url, scopes, message}`). The frontend
detects this envelope in the message renderer and shows an inline connect pill that
opens the same popup helper used by the menu.

Two new DocumentDB collections back persistence:
- `users_integrations` — per `(user_id, provider)` credential record (durable source
  of truth for "user has Jira connected").
- `user_agent_toolkits` — per `(user_id, agent_id, toolkit_id)` enablement record
  (drives auto-rehydration of `JiraToolkit` into the user's `ToolManager`).

`UserObjectsHandler.configure_tool_manager` is extended with a "cold-session
hydration" step that consults `user_agent_toolkits` and registers each enabled
toolkit via `provider.toolkit_factory(resolver)`.

The frontend (`navigator-frontend-next`) gets:
- `IntegrationsMenu.svelte` — toolbar dropdown injected at `AgentChat.svelte`
  between the Refresh and Canvas-toggle buttons.
- `OAuthPopupHelper` (TS module) — `window.open` lifecycle + `postMessage`
  listener with origin validation + 60s timeout.
- `ConnectIntegrationPill.svelte` — inline message renderer for `auth_required`
  envelopes.
- `src/lib/api/integrations.ts` — typed axios wrappers over the new endpoints.

### Component Diagram

```
                                ┌─────────────────────────────────────┐
                                │   navigator-frontend-next            │
                                │                                      │
   AgentChat.svelte             │  IntegrationsMenu.svelte             │
   (toolbar @ L954-975)─────────┤    │                                 │
                                │    └→ OAuthPopupHelper (window.open) │
                                │           │                          │
                                │           ▼   postMessage (origin √) │
                                │      popup window                    │
                                │                                      │
                                │  MessageRenderer                     │
                                │    └→ ConnectIntegrationPill.svelte  │
                                │           (on auth_required envelope)│
                                └──────────────┬───────────────────────┘
                                               │ HTTPS (Bearer JWT)
                                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          ai-parrot (backend)                              │
│                                                                           │
│  IntegrationsHandler                  AgentTalk                           │
│    GET    .../integrations/{agent_id}    POST .../chat/{agent_id}         │
│    POST   .../integrations/.../connect      ↓                             │
│    POST   .../integrations/.../enable    try { agent.ask(...) }           │
│    DELETE .../integrations/...           except AuthorizationRequired:    │
│         ↓                                    return AuthRequiredEnvelope  │
│    IntegrationsService                                                    │
│         │                                                                 │
│         ├──→ OAuth2ProviderRegistry                                       │
│         │       └── JiraOAuth2Provider ──→ JiraOAuthManager (existing)    │
│         │                                       │                         │
│         │                                       ▼                         │
│         │                                 Redis (jira:oauth:web:{uid})    │
│         │                                                                 │
│         ├──→ DocumentDB.users_integrations  (per user+provider)           │
│         └──→ DocumentDB.user_agent_toolkits (per user+agent+toolkit)      │
│                                                                           │
│  /api/auth/jira/callback                                                  │
│    ├── channel == "telegram" → existing flow (UNCHANGED)                  │
│    └── channel == "web"      → render web_oauth_success.html              │
│                                  (postMessage + window.close)             │
│                                                                           │
│  UserObjectsHandler.configure_tool_manager                                │
│    └── hydration step: read user_agent_toolkits → toolkit_factory()       │
└──────────────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/auth/jira_oauth.py` (`JiraOAuthManager`, `JiraTokenSet`) | uses (no change) | `create_authorization_url(channel="web", user_id, extra_state={...})` and `handle_callback(code, state)` are sufficient. We pass new keys (`channel`, `agent_id`, `return_origin`) inside `extra_state`. |
| `parrot/auth/credentials.py` (`OAuthCredentialResolver`) | uses (no change) | Injected into every `JiraToolkit` instantiated by `provider.toolkit_factory(resolver)`. |
| `parrot/auth/exceptions.py` (`AuthorizationRequired`) | catches | `AgentTalk` catches and projects into `AuthRequiredEnvelope`. The exception's `provider`, `auth_url`, `scopes`, `tool_name`, and message are mapped into the envelope. |
| `parrot/auth/routes.py` (`jira_oauth_callback`) | extends | Adds `channel == "web"` branch + new HTML templates `web_oauth_success.html`, `web_oauth_error.html`. Telegram path unchanged. |
| `parrot/handlers/agent.py` (`AgentTalk`) | modifies | Wraps agent invocation with `try/except AuthorizationRequired`. Single-body envelope response. |
| `parrot/handlers/user_objects.py` (`UserObjectsHandler.configure_tool_manager`) | modifies | New hydration step that reads `user_agent_toolkits` and registers persisted toolkits via `provider.toolkit_factory`. |
| `parrot/tools/manager.py` (`ToolManager.add_tool` / `remove_tool`) | uses (no change) | Hot-add on `enable`, remove on `disconnect`. |
| `parrot/manager/manager.py` (route registration block at L985-1080) | extends | Register `/api/v1/agents/integrations/{agent_id}` family adjacent to existing AgentTalk routes. |
| `parrot/conf.py` | extends | New `WEB_OAUTH_ALLOWED_ORIGINS = config.get("WEB_OAUTH_ALLOWED_ORIGINS", fallback=[])`. |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (`JiraToolkit._pre_execute`) | uses (no change) | Continues to raise `AuthorizationRequired` when `credential_resolver.resolve(...)` returns `None`. |
| `parrot/integrations/telegram/post_auth_jira.py`, `jira_commands.py` | depends on (no change) | Telegram path unchanged. No `users_integrations` write for `channel="telegram"`. |
| Frontend `AgentChat.svelte` (toolbar @ L954-975, message renderer) | modifies | Inject `+ Integrations` button + handle `auth_required` envelope in message renderer. |
| Frontend `src/lib/api/http.ts`, `config.ts` | uses (no change) | Reuse axios `createApiClient` + `apiBaseUrl` + `tokenStorageKey`. |
| Frontend `src/lib/ui/components/AppDialog.svelte`, `stores/toast.svelte.ts` | uses (no change) | Menu host (popover or dialog) and status toasts. |
| PBAC / `request.app['abac']` | uses | New action namespace `integration:list` / `integration:connect` / `integration:disconnect` (with optional `:provider` suffix — see §8 Q-A). |
| DocumentDB | adds collections | `users_integrations`, `user_agent_toolkits`. |

### Data Models

```python
# parrot/integrations/oauth2/models.py  (new module)

from typing import List, Literal, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class IntegrationDescriptor(BaseModel):
    """Describes one OAuth2-capable integration for the menu listing."""

    provider: str                           # e.g. "jira"
    display_name: str                       # e.g. "Jira"
    icon: Optional[str] = None              # mdi or URL
    default_scopes: List[str] = Field(default_factory=list)
    connected: bool = False                 # has a users_integrations row
    enabled_on_agent: bool = False          # has a user_agent_toolkits row for this (user, agent)
    account_id: Optional[str] = None
    display_account_name: Optional[str] = None
    email: Optional[str] = None
    connected_at: Optional[datetime] = None


class ConnectInitRequest(BaseModel):
    """Body for POST .../integrations/{agent_id}/{provider}/connect."""

    return_origin: Optional[str] = None     # if absent, server reads request.headers["Origin"]


class ConnectInitResponse(BaseModel):
    auth_url: str
    state: str                              # nonce, opaque to client
    scopes: List[str]
    expires_in: int = 600                   # seconds the nonce remains valid


class EnableResponse(BaseModel):
    integration: IntegrationDescriptor


class DisconnectResponse(BaseModel):
    provider: str
    disconnected: bool = True


class AuthRequiredEnvelope(BaseModel):
    """Single-body response from AgentTalk when AuthorizationRequired is caught."""

    type: Literal["auth_required"] = "auth_required"
    provider: str                           # e.g. "jira"
    tool_name: Optional[str] = None
    auth_url: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    message: str                            # human-readable, surfaced in chat


# DocumentDB row shapes (collection-backed; not strict ORM)

class UsersIntegrationRow(BaseModel):
    user_id: str
    provider: str                           # ("user_id", "provider") is the unique key
    channel: str = "web"
    status: Literal["active", "revoked"] = "active"
    account_id: str
    display_name: str
    email: Optional[str] = None
    scopes: List[str]
    cloud_id: Optional[str] = None          # provider-specific, present for Jira
    site_url: Optional[str] = None
    connected_at: datetime
    last_used_at: Optional[datetime] = None


class UserAgentToolkitRow(BaseModel):
    user_id: str
    agent_id: str
    toolkit_id: str                         # = provider for OAuth toolkits, "jira"
    provider: str
    enabled_at: datetime
```

### New Public Interfaces

```python
# parrot/integrations/oauth2/registry.py  (new)

class OAuth2Provider(ABC):
    """Base for any OAuth2-capable provider plugged into the registry."""

    provider_id: str                        # "jira"
    display_name: str                       # "Jira"
    icon: Optional[str]                     # "mdi:jira"
    default_scopes: List[str]
    pbac_action_namespace: str              # "integration"

    @property
    @abstractmethod
    def manager(self) -> Any:
        """Return the underlying OAuth manager (e.g. JiraOAuthManager)."""

    @abstractmethod
    def toolkit_factory(
        self, credential_resolver: "CredentialResolver"
    ) -> "AbstractToolkit":
        """Build a fresh toolkit instance bound to the resolver."""


class OAuth2ProviderRegistry:
    def register(self, provider: OAuth2Provider) -> None: ...
    def get(self, provider_id: str) -> Optional[OAuth2Provider]: ...
    def all(self) -> List[OAuth2Provider]: ...


def register_oauth2_provider(provider: OAuth2Provider) -> None:
    """Module-level convenience for app startup."""


# parrot/integrations/oauth2/jira_provider.py  (new)

class JiraOAuth2Provider(OAuth2Provider):
    provider_id = "jira"
    display_name = "Jira"
    icon = "mdi:jira"
    default_scopes = [
        "read:jira-user", "read:jira-work", "write:jira-work", "offline_access",
    ]
    pbac_action_namespace = "integration"

    @property
    def manager(self) -> JiraOAuthManager: ...

    def toolkit_factory(self, credential_resolver) -> JiraToolkit: ...


# parrot/integrations/oauth2/service.py  (new)

class IntegrationsService:
    async def list_for_user(
        self, user_id: str, agent_id: str
    ) -> List[IntegrationDescriptor]: ...

    async def start_connect(
        self, user_id: str, agent_id: str, provider_id: str, return_origin: str
    ) -> ConnectInitResponse: ...

    async def confirm_enable(
        self, user_id: str, agent_id: str, provider_id: str
    ) -> IntegrationDescriptor: ...

    async def disconnect(
        self, user_id: str, agent_id: str, provider_id: str
    ) -> DisconnectResponse: ...

    async def persist_credential(
        self, user_id: str, provider_id: str, token_set: Any
    ) -> UsersIntegrationRow:
        """Called from the web-branch of jira_oauth_callback."""


# parrot/handlers/integrations.py  (new)

@is_authenticated()
@user_session()
class IntegrationsHandler(BaseView):
    async def get(self) -> web.Response: ...      # list
    async def post(self) -> web.Response: ...     # connect-init OR confirm-enable, dispatched by URL suffix
    async def delete(self) -> web.Response: ...   # disconnect
```

---

## 3. Module Breakdown

### Module 1: `parrot/integrations/oauth2/__init__.py` + `models.py`
- **Path**: `packages/ai-parrot/src/parrot/integrations/oauth2/__init__.py`,
  `packages/ai-parrot/src/parrot/integrations/oauth2/models.py`
- **Responsibility**: Pydantic models — `IntegrationDescriptor`,
  `ConnectInitRequest`, `ConnectInitResponse`, `EnableResponse`,
  `DisconnectResponse`, `AuthRequiredEnvelope`, `UsersIntegrationRow`,
  `UserAgentToolkitRow`. Module-level constants:
  `_WEB_CHANNEL = "web"`.
- **Depends on**: `pydantic >= 2`. No internal deps.

### Module 2: `parrot/integrations/oauth2/registry.py`
- **Path**: `packages/ai-parrot/src/parrot/integrations/oauth2/registry.py`
- **Responsibility**: `OAuth2Provider` ABC + `OAuth2ProviderRegistry` (in-memory
  singleton) + `register_oauth2_provider()` helper.
- **Depends on**: Module 1 (models), stdlib `abc`.

### Module 3: `parrot/integrations/oauth2/jira_provider.py`
- **Path**: `packages/ai-parrot/src/parrot/integrations/oauth2/jira_provider.py`
- **Responsibility**: `JiraOAuth2Provider` — wraps `JiraOAuthManager` and
  `JiraToolkit`. `toolkit_factory(resolver)` returns a fresh `JiraToolkit` with
  `auth_type="oauth2_3lo"` and the supplied resolver.
- **Depends on**: Module 2, `parrot.auth.jira_oauth`,
  `parrot_tools.jiratoolkit.JiraToolkit`.

### Module 4: `parrot/integrations/oauth2/persistence.py`
- **Path**: `packages/ai-parrot/src/parrot/integrations/oauth2/persistence.py`
- **Responsibility**: Async repository functions for the two new DocumentDB
  collections. Single source of truth for read/upsert/delete on
  `users_integrations` and `user_agent_toolkits`. Includes the deletion-cascade rule
  (disconnecting a provider deletes the credential row AND every matching
  enablement row for that user+provider).
- **Depends on**: Module 1 (row models), the existing DocumentDB client (the spec
  consumer should locate the canonical access pattern by reading
  `parrot/handlers/mcp_persistence.py` — same store, different collections).

### Module 5: `parrot/integrations/oauth2/service.py`
- **Path**: `packages/ai-parrot/src/parrot/integrations/oauth2/service.py`
- **Responsibility**: `IntegrationsService` — orchestrates registry + persistence +
  PBAC checks for the four operations (list, start_connect, confirm_enable,
  disconnect) and provides `persist_credential()` for the OAuth callback to call
  after a successful web-channel exchange.
- **Depends on**: Modules 2, 3, 4. Optional dep: `request.app['abac']` PDP.

### Module 6: `parrot/handlers/integrations.py`
- **Path**: `packages/ai-parrot/src/parrot/handlers/integrations.py`
- **Responsibility**: `IntegrationsHandler(BaseView)` — aiohttp view for the
  `/api/v1/agents/integrations/{agent_id}` family. Stacks `@is_authenticated()` +
  `@user_session()`. Dispatches POST by URL suffix
  (`.../{provider}/connect` vs `.../{provider}/enable`). Validates origin from
  `request.headers.get("Origin")` against `WEB_OAUTH_ALLOWED_ORIGINS`. Calls
  `IntegrationsService` for all real work.
- **Depends on**: Module 5, navigator-auth decorators (`@is_authenticated`,
  `@user_session`), `parrot.conf.WEB_OAUTH_ALLOWED_ORIGINS`.

### Module 7: `parrot/auth/routes.py` extension (web-channel callback branch)
- **Path**: `packages/ai-parrot/src/parrot/auth/routes.py` (modified, not new file)
- **Responsibility**: After `manager.handle_callback(code, state)` succeeds,
  inspect the returned `extra_state["channel"]`. If `"web"`:
  1. Call `IntegrationsService.persist_credential(user_id, "jira", token_set)`
     to upsert `users_integrations`.
  2. Render `web_oauth_success.html` with server-validated `target_origin`
     (from `extra_state["return_origin"]`, validated against
     `WEB_OAUTH_ALLOWED_ORIGINS`).
  3. The HTML JavaScript posts
     `{type: "ai-parrot-oauth-callback", provider: "jira", success: true, ...}`
     to `window.opener` and calls `window.close()`.
  Errors render `web_oauth_error.html` with the same envelope shape and
  `success: false`.
  If `extra_state["channel"]` is `"telegram"` (or absent for backward
  compatibility), the existing flow runs unchanged.
- **Depends on**: Modules 5, `aiohttp.web`. Templates can be inline string templates
  or `aiohttp_jinja2` — pick whichever the surrounding routes already use (verify
  in implementation).
- **New files**: `packages/ai-parrot/src/parrot/auth/templates/web_oauth_success.html`,
  `packages/ai-parrot/src/parrot/auth/templates/web_oauth_error.html`.

### Module 8: `parrot/handlers/agent.py` — `AuthRequiredEnvelope` translator
- **Path**: `packages/ai-parrot/src/parrot/handlers/agent.py` (modified)
- **Responsibility**: Wrap the agent invocation inside `AgentTalk.post`
  (the call chain at L979-L1023, particularly the section that invokes `agent.ask`
  / `agent.invoke` after the tool manager is loaded) with `try / except
  AuthorizationRequired`. On exception, build an `AuthRequiredEnvelope` from the
  exception fields and return as the JSON response body with HTTP 200 (the chat
  call succeeded; the agent's reply is the structured envelope). Other exception
  classes (e.g. `Exception`) keep their existing handling.
- **Depends on**: Module 1 (`AuthRequiredEnvelope`), `parrot.auth.exceptions`.

### Module 9: `parrot/handlers/user_objects.py` — cold-session hydration
- **Path**: `packages/ai-parrot/src/parrot/handlers/user_objects.py` (modified)
- **Responsibility**: Extend `UserObjectsHandler.configure_tool_manager` (L96)
  with a step that, after the existing session-based load, queries
  `user_agent_toolkits` for `(user_id, agent_id)`. For each row, look up the
  provider via `OAuth2ProviderRegistry`, instantiate the toolkit via
  `provider.toolkit_factory(OAuthCredentialResolver(provider.manager))`, and
  `tool_manager.add_tool(toolkit)` if not already present. Persist back to session
  under the same key (currently `f"{agent_name}_tool_manager"` at agent.py:1325 —
  see Risk note below about the alternate `f"{agent_id}_tool_manager"` convention
  in mcp_helper.py:93).
- **Depends on**: Modules 2, 4, `parrot.tools.manager.ToolManager`.

### Module 10: `parrot/manager/manager.py` — route registration
- **Path**: `packages/ai-parrot/src/parrot/manager/manager.py` (modified, single
  block at L985-1080)
- **Responsibility**: Register four routes adjacent to existing AgentTalk routes:
  - `GET    /api/v1/agents/integrations/{agent_id}` → `IntegrationsHandler`
  - `POST   /api/v1/agents/integrations/{agent_id}/{provider}/connect` → `IntegrationsHandler`
  - `POST   /api/v1/agents/integrations/{agent_id}/{provider}/enable` → `IntegrationsHandler`
  - `DELETE /api/v1/agents/integrations/{agent_id}/{provider}` → `IntegrationsHandler`
  Also registers `JiraOAuth2Provider` with the global `OAuth2ProviderRegistry` at
  app startup.
- **Depends on**: Modules 3, 6.

### Module 11: `parrot/conf.py` — config key
- **Path**: `packages/ai-parrot/src/parrot/conf.py` (modified)
- **Responsibility**: Add
  `WEB_OAUTH_ALLOWED_ORIGINS = config.get("WEB_OAUTH_ALLOWED_ORIGINS", fallback=[])`
  (uses navconfig `Kardex.get(..., fallback=...)` — never `default=`, see Patterns).
  Value is parsed as a list (comma-separated string acceptable; transform inside
  the same line).
- **Depends on**: navconfig `Kardex` (already imported at the top of
  `parrot/conf.py`).

### Module 12: Frontend — `src/lib/api/integrations.ts`
- **Path**: `navigator-frontend-next/src/lib/api/integrations.ts` (new)
- **Responsibility**: Typed axios wrappers — `listIntegrations(agentId)`,
  `startIntegrationConnect(agentId, provider)`,
  `confirmIntegrationEnable(agentId, provider)`,
  `disconnectIntegration(agentId, provider)`. Reuses the shared
  `createApiClient(baseURL?)` factory from `src/lib/api/http.ts`.
- **Depends on**: `src/lib/api/http.ts`, `src/lib/config.ts`.

### Module 13: Frontend — `src/lib/oauth/popup.ts`
- **Path**: `navigator-frontend-next/src/lib/oauth/popup.ts` (new)
- **Responsibility**: `awaitOAuthCallback({authUrl, allowedOrigin, timeoutMs})` —
  opens `window.open(authUrl, 'oauth-popup', 'width=500,height=700')`, registers
  a `message` listener filtered by `event.origin === allowedOrigin` AND
  `event.data?.type === "ai-parrot-oauth-callback"`. Polls `popup.closed` every
  500ms; if it goes true without a message → `cancelled`. Times out after
  `timeoutMs` (default 60000). Cleans up listener + interval on resolve/reject.
  Returns `{success: true, payload}` or `{success: false, reason: "cancelled" |
  "timeout" | "error", error?}`.
- **Depends on**: nothing (pure browser API). No new dependencies.

### Module 14: Frontend — `IntegrationsMenu.svelte` + `IntegrationItem.svelte`
- **Path**:
  `navigator-frontend-next/src/lib/components/agents/integrations/IntegrationsMenu.svelte`
  (new), and `IntegrationItem.svelte` (new).
- **Responsibility**: Dropdown / popover triggered by the toolbar button. On open,
  calls `listIntegrations(agentId)` and renders one `IntegrationItem` per result.
  Each item shows status badge (Connected / Not connected), action button
  (Connect / Disconnect). Connect → `startIntegrationConnect` → `awaitOAuthCallback`
  → `confirmIntegrationEnable` → refresh menu + `toastStore.success`.
- **Depends on**: Modules 12, 13. UI primitives `AppDialog.svelte` (or a lightweight
  popover — see §8 Q-C) and `toastStore`.

### Module 15: Frontend — `ConnectIntegrationPill.svelte` + AgentChat wiring
- **Path**:
  `navigator-frontend-next/src/lib/components/agents/integrations/ConnectIntegrationPill.svelte`
  (new), plus modifications to
  `navigator-frontend-next/src/lib/components/agents/AgentChat.svelte` (toolbar
  button injection at L954-975 + message renderer detection of `auth_required`).
- **Responsibility**: Inline pill rendered when an agent message has
  `type === "auth_required"`. Click → opens the same popup helper (Module 13).
  After success → `confirmIntegrationEnable` → toast → user is invited to retry
  the prompt (no auto-retry — see §8 Q-D).
- **Depends on**: Modules 12, 13, 14 (toast wiring).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_oauth2_registry_register_and_get` | Module 2 | Registering a provider then retrieving it returns the same instance; duplicate registration overwrites. |
| `test_jira_provider_toolkit_factory_returns_oauth2_3lo` | Module 3 | `JiraOAuth2Provider.toolkit_factory(resolver)` returns a `JiraToolkit` with `auth_type="oauth2_3lo"` and the supplied resolver attached. |
| `test_persistence_users_integrations_upsert_idempotent` | Module 4 | Two upserts with the same `(user_id, provider)` result in one row with last-write-wins. |
| `test_persistence_disconnect_cascades` | Module 4 | Disconnecting deletes the `users_integrations` row AND every `user_agent_toolkits` row for that `(user_id, provider)`. |
| `test_service_list_filters_by_pbac` | Module 5 | When PBAC denies `integration:list` for a provider, that provider is excluded from the result. When PBAC PDP is missing, fail-open (current convention; see §8 Q-B). |
| `test_service_start_connect_validates_origin` | Module 5 | A `return_origin` not in `WEB_OAUTH_ALLOWED_ORIGINS` raises a `ValueError` (translated to HTTP 400 by the handler). |
| `test_service_confirm_enable_409_when_no_credential` | Module 5 | `confirm_enable` raises if no `users_integrations` row exists for `(user_id, provider)` (popup never completed). |
| `test_handler_get_returns_descriptors` | Module 6 | `GET .../integrations/{agent_id}` returns a JSON list of `IntegrationDescriptor` for the user. |
| `test_handler_connect_init_origin_from_header` | Module 6 | If `return_origin` not in body, handler reads `request.headers["Origin"]`; if neither present, returns 400. |
| `test_callback_web_branch_renders_postmessage_html` | Module 7 | When `extra_state["channel"] == "web"`, callback renders HTML containing `window.opener.postMessage({type: "ai-parrot-oauth-callback", ...}, "<allowed_origin>")` and `window.close()`. |
| `test_callback_telegram_branch_unchanged` | Module 7 | Telegram branch path executes `_notify_telegram` and `telegram_jira_session_stamper` exactly as today (regression guard). |
| `test_callback_invalid_return_origin_renders_error_template` | Module 7 | If `return_origin` is not in `WEB_OAUTH_ALLOWED_ORIGINS`, error template is rendered with `success: false, error: "invalid_origin"`. |
| `test_agenttalk_translates_authorization_required_to_envelope` | Module 8 | When `agent.ask(...)` raises `AuthorizationRequired(provider="jira", auth_url="https://...")`, AgentTalk returns 200 with body `{"type": "auth_required", "provider": "jira", "auth_url": "..."}`. |
| `test_user_objects_hydration_adds_persisted_toolkits` | Module 9 | A `UserAgentToolkitRow` for `(user, agent, "jira")` causes `configure_tool_manager` to add a `JiraToolkit` to the session ToolManager on cold session. |
| `test_user_objects_hydration_skips_already_present` | Module 9 | If the toolkit is already in the ToolManager, hydration is a no-op (no duplicate). |
| `test_routes_registered` | Module 10 | All four `/api/v1/agents/integrations/...` routes appear in `app.router.routes()` after manager startup. |
| `test_conf_web_oauth_allowed_origins_default_empty_list` | Module 11 | When env var unset, value is `[]` (uses `fallback=`, never `default=`). |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_web_connect_jira_happy_path` | (a) Mock Atlassian. (b) `POST .../integrations/{agent_id}/jira/connect` returns `auth_url + state`. (c) Simulate `GET /api/auth/jira/callback?code=...&state=...` (with `extra_state.channel="web"`). (d) Verify `users_integrations` row exists. (e) `POST .../integrations/{agent_id}/jira/enable` returns descriptor with `connected=true, enabled_on_agent=true`. (f) Subsequent `POST .../chat/{agent_id}` invocation uses `JiraToolkit` without raising `AuthorizationRequired`. |
| `test_e2e_auth_required_envelope_when_not_connected` | Without a credential, a chat request that triggers a Jira tool call returns `{"type": "auth_required", "provider": "jira", "auth_url": "..."}` with HTTP 200. |
| `test_e2e_disconnect_removes_credential_and_enablement` | After a successful connect+enable, `DELETE .../integrations/{agent_id}/jira` removes both the `users_integrations` row and all `user_agent_toolkits` rows for `(user, "jira")`. The next chat call raises `AuthorizationRequired`. |
| `test_e2e_cold_session_rehydration` | Wipe Redis. Restart the app. First chat request to an agent for which the user has a `user_agent_toolkits` row triggers hydration; if the credential is also intact (DocumentDB), the call succeeds. If credential expired beyond refresh, returns `auth_required` envelope. |
| `test_e2e_telegram_unaffected` | A baseline Telegram `/connect_jira → callback → /jira_status` flow runs unchanged after this feature lands (regression guard for the callback branch). |

### Test Data / Fixtures

```python
# tests/integration/oauth2/conftest.py
import pytest
from parrot.integrations.oauth2.models import (
    UsersIntegrationRow, UserAgentToolkitRow, IntegrationDescriptor,
)


@pytest.fixture
def web_user_id() -> str:
    return "user-test-1234"


@pytest.fixture
def jira_token_set_factory():
    """Build a JiraTokenSet with future expiry."""
    from parrot.auth.jira_oauth import JiraTokenSet
    import time
    def _make(**overrides):
        base = dict(
            access_token="at-XYZ", refresh_token="rt-XYZ",
            expires_at=time.time() + 3600,
            cloud_id="cloud-1", site_url="https://example.atlassian.net",
            account_id="acct-1", display_name="Test User",
            email="test@example.com",
            scopes=["read:jira-work", "write:jira-work", "offline_access"],
            granted_at=time.time(), last_refreshed_at=time.time(),
            available_sites=[],
        )
        base.update(overrides)
        return JiraTokenSet(**base)
    return _make


@pytest.fixture
def allowed_origins(monkeypatch):
    monkeypatch.setenv("WEB_OAUTH_ALLOWED_ORIGINS", "https://app.example.com")
    yield ["https://app.example.com"]
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests in `tests/unit/integrations/oauth2/` pass.
- [ ] All integration tests in `tests/integration/oauth2/` pass.
- [ ] The Telegram OAuth2 3LO flow (`/connect_jira → callback → /jira_status`)
      runs unchanged after the feature is merged (regression test
      `test_e2e_telegram_unaffected` passes).
- [ ] `OAuth2ProviderRegistry` is created and `JiraOAuth2Provider` is registered
      at app startup. `OAuth2ProviderRegistry.all()` returns at least one provider.
- [ ] `GET /api/v1/agents/integrations/{agent_id}` returns a JSON list of
      `IntegrationDescriptor`, PBAC-filtered, with accurate `connected` and
      `enabled_on_agent` flags.
- [ ] `POST /api/v1/agents/integrations/{agent_id}/jira/connect` returns
      `{auth_url, state, scopes, expires_in}`. The `auth_url` points at
      `https://auth.atlassian.com/authorize` with the project's
      `JIRA_CLIENT_ID`, `JIRA_REDIRECT_URI`, and a state nonce that survives
      the round-trip.
- [ ] `POST /api/v1/agents/integrations/{agent_id}/jira/enable` succeeds only
      when a `users_integrations` row exists for `(user, "jira")` and writes a
      `user_agent_toolkits` row for `(user, agent_id, "jira")`. Repeated calls
      are idempotent.
- [ ] `DELETE /api/v1/agents/integrations/{agent_id}/jira` deletes the
      `users_integrations` row, every matching `user_agent_toolkits` row for
      `(user, "jira")`, and removes the toolkit from the session `ToolManager`.
- [ ] The OAuth callback route (`GET /api/auth/jira/callback`) renders
      `web_oauth_success.html` when `extra_state["channel"] == "web"`. The
      rendered HTML calls `window.opener.postMessage({type:
      "ai-parrot-oauth-callback", provider: "jira", success: true, ...},
      "<validated origin>")` followed by `window.close()`.
- [ ] An invalid `return_origin` (not in `WEB_OAUTH_ALLOWED_ORIGINS`) renders
      `web_oauth_error.html` with `success: false, error: "invalid_origin"`. The
      success template is **not** rendered.
- [ ] `AgentTalk.post` catches `AuthorizationRequired` and returns a single-body
      JSON response matching `AuthRequiredEnvelope` schema with HTTP 200. No
      streaming change.
- [ ] `UserObjectsHandler.configure_tool_manager` auto-rehydrates persisted
      toolkits from `user_agent_toolkits` on cold session, idempotently.
- [ ] No persistence write hits `users_integrations` for `channel="telegram"`
      callbacks (Telegram path stays Redis-only + Vault).
- [ ] `parrot/conf.py` exposes `WEB_OAUTH_ALLOWED_ORIGINS` via
      `Kardex.get(..., fallback=[])`. Default is `[]` when env unset.
- [ ] The frontend `+ Integrations` button is rendered between Refresh and
      Canvas-toggle in `AgentChat.svelte`. Click opens the menu populated from
      `listIntegrations`.
- [ ] The frontend popup helper validates `event.origin === window.location.origin`
      AND `event.data?.type === "ai-parrot-oauth-callback"` before resolving.
      Cross-origin or wrong-type messages are silently dropped.
- [ ] `ConnectIntegrationPill.svelte` renders inline whenever an agent message
      has `type === "auth_required"` and clicking it opens the popup helper with
      the supplied `auth_url`.
- [ ] No new lint errors (`ruff check`, `mypy`) and no new failing tests
      anywhere in the existing suite.
- [ ] Documentation updated:
      `docs/integrations/web-oauth2-integrations.md` (new) covering the registry,
      the popup contract, and how to add a new provider in one file.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Re-verified on 2026-05-04 by `grep` against the live tree. Implementation
> agents MUST NOT reference imports, attributes, or methods not listed here
> without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# Backend — all confirmed working:
from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet
# verified: parrot/auth/jira_oauth.py:59 (JiraTokenSet), :86 (JiraOAuthManager)

from parrot.auth.credentials import CredentialResolver, OAuthCredentialResolver
# verified: parrot/auth/credentials.py:27, :49

from parrot.auth.exceptions import AuthorizationRequired
# verified: parrot/auth/exceptions.py:12

from parrot.handlers.agent import AgentTalk
# verified: parrot/handlers/agent.py:50

from parrot.handlers.user_objects import UserObjectsHandler
# verified: parrot/handlers/user_objects.py (configure_tool_manager at :96)

from parrot.tools.manager import ToolManager
# verified: parrot/tools/manager.py:203

from parrot_tools.jiratoolkit import JiraToolkit
# verified: packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:630
# (note: JiraToolkit imports AuthorizationRequired at jiratoolkit.py:73)

# Frontend — all confirmed:
import { createApiClient } from "$lib/api/http";   // src/lib/api/http.ts:142
import { config } from "$lib/config";              // src/lib/config.ts:31-38
import { toastStore } from "$lib/stores/toast.svelte";  // src/lib/stores/toast.svelte.ts
import AppDialog from "$lib/ui/components/AppDialog.svelte";  // confirmed exists
```

### Existing Class Signatures

```python
# parrot/auth/jira_oauth.py
_TOKEN_KEY_PREFIX = "jira:oauth"        # line 37 — Redis key prefix: jira:oauth:{channel}:{user_id}
_TOKEN_TTL_SECONDS = 90 * 24 * 60 * 60  # line 42 — 90 days

class JiraTokenSet(BaseModel):           # line 59
    access_token: str
    refresh_token: str
    expires_at: float
    cloud_id: str
    site_url: str
    account_id: str
    display_name: str
    email: Optional[str]
    scopes: List[str]
    granted_at: float
    last_refreshed_at: float
    available_sites: List[Dict[str, Any]]

class JiraOAuthManager:                  # line 86
    async def create_authorization_url(  # line 258
        self,
        channel: str,
        user_id: str,
        extra_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, str]:                # returns (url, nonce)
        ...
    async def handle_callback(           # line 304
        self, code: str, state: str
    ) -> Tuple[JiraTokenSet, Dict[str, Any]]: ...
    async def get_valid_token(           # line 384
        self, channel: str, user_id: str
    ) -> Optional[JiraTokenSet]: ...

# parrot/auth/credentials.py
class CredentialResolver(ABC):                                      # line 27
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]: ...   # line 31
    async def get_auth_url(self, channel: str, user_id: str) -> str: ...        # line 40
    async def is_connected(self, channel: str, user_id: str) -> bool: ...       # line 44

class OAuthCredentialResolver(CredentialResolver):                  # line 49
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]: ...   # line 62
    async def get_auth_url(self, channel: str, user_id: str) -> str: ...        # line 65

# parrot/auth/exceptions.py
class AuthorizationRequired(Exception):  # line 12
    def __init__(
        self,
        tool_name: str,                  # line 36
        message: str,
        auth_url: Optional[str] = None,  # line 38
        provider: str = "unknown",       # line 39  — note: default is "unknown", NOT "jira"
        scopes: Optional[List[str]] = None,  # line 40
    ): ...
    # Public attrs (set in __init__): tool_name, auth_url, provider, scopes (List[str])

# parrot/handlers/agent.py
@is_authenticated()       # line 48
@user_session()           # line 49
class AgentTalk(BaseView):  # line 50
    # session key for per-user tool manager:
    #   f"{agent.name}_tool_manager"  (used at line 1325)
    #   NOTE: parrot/handlers/mcp_helper.py:93 uses f"{agent_id}_tool_manager"
    #         (different key). Spec phase has chosen agent.name; see §7 Risks.
    async def _check_pbac_agent_access(...): ...        # line 83
    async def _filter_tools_for_user(self, tool_manager: "ToolManager") -> None: ...  # line 158
    async def _configure_tool_manager(...): ...         # line 680 — delegates to UserObjectsHandler
    async def _get_user_session(self, data: dict): ...  # line 874
    async def _resolve_bot(self, data): ...             # line 927
    # Agent invocation occurs around lines 979-1023 — the new try/except wraps that block.

# parrot/handlers/user_objects.py
class UserObjectsHandler:
    async def configure_tool_manager(...): ...   # line 96
    # Uses session_key = self.get_session_key(agent_name, "tool_manager")  (line 123)
    #   → string form: f"{agent_name}_tool_manager"
    # Persists ToolManager into request.session under that key (line 168).

# parrot/tools/manager.py
class ToolManager(MCPToolManagerMixin):                             # line 203
    def set_resolver(self, resolver: "AbstractPermissionResolver") -> None: ...  # line 285
    def add_tool(self, tool: Union[ToolDefinition, AbstractTool],
                 name: Optional[str] = None) -> None: ...           # line 381
    def get_tool(self, tool_name: str) -> Optional[Any]: ...        # line 822
    def remove_tool(self, tool_name: str) -> None: ...              # line 877

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit(AbstractToolkit):                                 # line 630
    def __init__(
        self,
        ...,
        credential_resolver: Any = None,                            # line 700
        ...,
    ): ...
    async def _pre_execute(self, tool_name: str, **kwargs) -> None:  # line 866
        # Reads kwargs["_permission_context"] (channel, user_id).
        # Calls self.credential_resolver.resolve(channel, user_id).
        # If None → raises AuthorizationRequired(auth_url=...).

# parrot/auth/routes.py
async def jira_oauth_callback(request: web.Request) -> web.Response:  # line 83
    # Existing: handles GET /api/auth/jira/callback?code=...&state=...
    # Existing: optional Telegram session stamper at line 121
    # Existing: optional Telegram chat notification at line 139
def setup_jira_oauth_routes(app: web.Application) -> None: ...        # line 156

# parrot/integrations/telegram/jira_commands.py
_TELEGRAM_CHANNEL = "telegram"                                       # line 39
async def connect_jira_handler(message, oauth_manager): ...          # line 50
def register_jira_commands(...): ...                                 # line 145

# parrot/conf.py
JIRA_CLIENT_ID = config.get("JIRA_CLIENT_ID")        # line 608
JIRA_CLIENT_SECRET = config.get("JIRA_CLIENT_SECRET") # line 609
JIRA_REDIRECT_URI = config.get("JIRA_REDIRECT_URI")  # line 610
# WEB_OAUTH_ALLOWED_ORIGINS — DOES NOT EXIST yet; this spec adds it.

# parrot/manager/manager.py — route registration block (L985-1080)
# Existing AgentTalk routes:
'/api/v1/agents/chat/{agent_id}'                       # line 1001
'/api/v1/agents/chat/{agent_id}/{method_name}'         # line 1005
# Add new integrations routes adjacent to these.
```

```typescript
// navigator-frontend-next/src/lib/api/http.ts
// line 56-82: createApiClient factory + Bearer interceptor (uses config.tokenStorageKey)
// line 142:   export function createApiClient(baseURL?: string): AxiosInstance
// line 166:   export function createApiClientWithToken(token: string)

// navigator-frontend-next/src/lib/config.ts
// line 12-13: const apiBaseUrl = (env.PUBLIC_API_URL ?? DEFAULT_API).replace(/\/$/, '')
// line 31-38: export const config = { apiBaseUrl, tokenStorageKey: '...', ... }

// navigator-frontend-next/src/lib/components/agents/AgentChat.svelte
// L954-975: Toolbar div with Refresh button + (canvas-toggle) — INJECTION POINT
//   The new "+ Integrations" button goes between these two.
//   Pattern: <button class="btn btn-ghost btn-xs btn-square ...">
//              <Icon icon="mdi:..." class="size-3.5" />
//            </button>
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `JiraOAuth2Provider` | `JiraOAuthManager` | property `manager` | parrot/auth/jira_oauth.py:86 |
| `JiraOAuth2Provider.toolkit_factory` | `JiraToolkit(auth_type="oauth2_3lo", credential_resolver=…)` | constructor | parrot_tools/jiratoolkit.py:700 |
| `IntegrationsService.start_connect` | `JiraOAuthManager.create_authorization_url(channel="web", user_id, extra_state={…})` | method call | parrot/auth/jira_oauth.py:258 |
| `IntegrationsService.persist_credential` (called from web callback) | DocumentDB `users_integrations` upsert | repository fn (Module 4) | NEW |
| `IntegrationsHandler` | `IntegrationsService` | composition | NEW |
| `IntegrationsHandler` route registration | `parrot/manager/manager.py` | `router.add_view(...)` | parrot/manager/manager.py:1001-1080 |
| `AgentTalk.post` (modified) | `AuthRequiredEnvelope` | try/except → JSON | parrot/handlers/agent.py:979-1023 |
| `UserObjectsHandler.configure_tool_manager` (modified) | `OAuth2ProviderRegistry.get(...).toolkit_factory(resolver)` then `tool_manager.add_tool(...)` | method call | parrot/handlers/user_objects.py:96 + parrot/tools/manager.py:381 |
| Web-channel callback branch | `IntegrationsService.persist_credential` then HTML render | function call + template | parrot/auth/routes.py:83-153 (extension) |
| Frontend `IntegrationsMenu` | `GET /api/v1/agents/integrations/{agent_id}` | `listIntegrations(agentId)` | NEW (Module 12) |
| Frontend popup callback | `window.opener.postMessage({type: "ai-parrot-oauth-callback", ...}, target_origin)` | `postMessage` API | NEW (Module 7 template + Module 13 listener) |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.integrations.oauth2`~~ — does not exist yet; this spec creates it.
- ~~`parrot.handlers.integrations`~~ — does not exist yet.
- ~~`parrot.integrations.oauth2.OAuth2Provider`~~ — new ABC defined by this spec.
- ~~`parrot.integrations.oauth2.OAuth2ProviderRegistry`~~ — new.
- ~~`parrot.integrations.oauth2.IntegrationsService`~~ — new.
- ~~`AuthRequiredEnvelope` Pydantic model~~ — new.
- ~~`users_integrations` DocumentDB collection~~ — does not exist; this spec creates it.
- ~~`user_agent_toolkits` DocumentDB collection~~ — does not exist; this spec creates it.
- ~~`WEB_OAUTH_ALLOWED_ORIGINS` config key~~ — does not exist in `parrot/conf.py`; this spec adds it.
- ~~`AuthorizationRequired.provider` defaulting to `"jira"`~~ — the actual default is `"unknown"` (parrot/auth/exceptions.py:39). Jira call sites pass `"jira"` explicitly.
- ~~`AbstractOAuthIntegration` base class~~ — does not exist; the new `OAuth2Provider` is the abstraction.
- ~~A pre-existing OAuth popup pattern in the frontend~~ — only one `window.open` usage exists (`ExportMenu.svelte:65`) and it has no postMessage callback. This spec establishes the pattern.
- ~~A pre-existing `IntegrationsMenu.svelte` / `ConnectIntegrationPill.svelte`~~ — neither exists.
- ~~`web_oauth_success.html` / `web_oauth_error.html` templates~~ — do not exist yet.
- ~~Cross-channel credential sharing between Telegram and Web~~ — explicitly out of scope.
- ~~Provider-side token revocation on disconnect~~ — explicitly out of scope.
- ~~Vault mirroring for web-channel tokens~~ — Telegram-only; web is Redis + DocumentDB.
- ~~Streaming / SSE response transport for `auth_required`~~ — single response body (resolved).
- ~~Iframe-embedded OAuth UX~~ — non-viable due to Atlassian X-Frame-Options.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **navconfig Kardex**: use `config.get("KEY", fallback=...)` — **never** `default=` (raises `TypeError`). Confirmed in repo memory.
- **async-first**: all repository, service, and handler methods are `async def`.
  No blocking I/O.
- **Pydantic v2** for every wire-shaped model.
- **Logging**: `self.logger = logging.getLogger(__name__)`; never `print`.
- **JIRA toolkit instantiation**: always pass `auth_type="oauth2_3lo"` AND a
  `credential_resolver`. The `JiraToolkit.__init__` raises if `auth_type ==
  "oauth2_3lo"` and no resolver is given (jiratoolkit.py:766-770).
- **Channel constants**: define `_WEB_CHANNEL = "web"` in
  `parrot/integrations/oauth2/__init__.py` (mirror of
  `_TELEGRAM_CHANNEL = "telegram"` in jira_commands.py:39). Never hardcode the
  string elsewhere.
- **`extra_state` shape for web channel**:
  `{"channel": "web", "agent_id": "<id>", "return_origin": "<validated origin>"}`.
- **Origin validation**: server-side validation against `WEB_OAUTH_ALLOWED_ORIGINS`
  is the primary defence. Client-side `event.origin` check is defence-in-depth.
- **PBAC fallback**: when `request.app.get('abac')` is `None`, fail-open
  (current convention in `AgentTalk._check_pbac_agent_access`). This spec keeps
  that convention — see §8 Q-B for an open question on tightening it.
- **Idempotency**: `confirm_enable` and `disconnect` must be idempotent. Calling
  `enable` twice with the same `(user, agent, provider)` is a no-op; calling
  `disconnect` twice is a no-op after the first.
- **Cascading delete**: disconnecting a `(user, provider)` deletes the
  `users_integrations` row AND every matching `user_agent_toolkits` row for
  that user+provider. Implement in `IntegrationsService.disconnect` so the
  service is the single authority.

### Known Risks / Gotchas

- **Two session-key conventions in flight**.
  `parrot/handlers/agent.py:1325` uses `f"{agent.name}_tool_manager"` whereas
  `parrot/handlers/mcp_helper.py:93` uses `f"{agent_id}_tool_manager"`. They will
  point to different session entries if `agent.name != agent_id`. **This spec
  follows `agent.name`** (because that is what `UserObjectsHandler` itself uses
  via `get_session_key(agent_name, "tool_manager")` at user_objects.py:123).
  Hydration must use the same key. If the existing inconsistency is a real bug,
  that's a separate issue — do NOT fix it inside this feature.

- **Popup blockers**. `window.open()` may return `null` (most browsers allow it
  only in a direct user-gesture context). The popup helper must fail clearly
  with `{success: false, reason: "popup-blocked"}` and the menu must surface a
  toast: "Popup blocked. Please allow popups for this site and click Connect
  again." There is **no** full-page-redirect fallback in v1.

- **State nonce TTL is 10 minutes** (existing `JiraOAuthManager` behaviour). Long
  user think-time on the consent screen will raise on the callback with state
  mismatch. The error template surfaces `error: "state_expired"`; frontend toasts
  "Authorization expired, please try again."

- **Token-cache invalidation on refresh**. `JiraToolkit._pre_execute` caches the
  per-user JIRA client by token fingerprint (jiratoolkit.py:918+). After a
  refresh, the fingerprint changes and the cache is invalidated. We rely on this
  existing behaviour — **do not modify it**.

- **DocumentDB unreachable during `confirm_enable`**. The Redis token is in
  place (the manager wrote it), but the row write fails. Resolution: log error,
  return 500 with `{"retryable": true}`; frontend toasts "Could not save your
  integration, please retry." The retry of `confirm_enable` is idempotent (upsert).

- **Stale enablement after credential revocation**. A `user_agent_toolkits` row
  may persist after the credential expires beyond refresh. Hydration registers
  the toolkit; the very first call raises `AuthorizationRequired` and the user
  reconnects via the inline pill. Working as designed.

- **PBAC namespace decision**. The spec uses `integration:list`,
  `integration:connect`, `integration:disconnect` (without per-provider suffix).
  Per-provider variants (`integration:connect:jira`) are NOT used — the
  `provider_id` is supplied as a context attribute on the EvalContext instead
  of being baked into the action string. See §8 Q-A if you want to revisit.

- **Multi-tab live sync (deliberately out of scope for v1)**. Connecting in tab A
  does NOT live-update tab B's menu. Acceptable; documented in `Non-Goals`.

- **PBAC default policy** (open question, §8 Q-B). Current convention is
  fail-open when no PDP is configured. This may surprise security-sensitive
  tenants — flagged for product / security review before GA.

- **DocumentDB migration story** (open question, §8 Q-E). Spec assumes lazy
  collection creation on first write (the prevailing pattern observed in
  `parrot/handlers/mcp_persistence.py`). Confirm during implementation.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiohttp` | as-pinned | New endpoint registration; existing core dep |
| `pydantic` | `>=2` | Wire models (`IntegrationDescriptor`, envelopes); existing core dep |
| `navconfig` | as-pinned | `Kardex.get("WEB_OAUTH_ALLOWED_ORIGINS", fallback=[])`; existing core dep |
| `aiohttp_jinja2` (optional) | as-pinned-if-present | If existing callback templates use it; otherwise inline string templates are fine |
| `axios` (frontend) | as-pinned | API client; existing dep |
| `bits-ui` (frontend, via `AppDialog.svelte`) | as-pinned | Dialog primitive (or use plain popover) |

No new third-party dependencies are introduced. The Jira OAuth path already
uses Atlassian endpoints (`auth.atlassian.com`, `api.atlassian.com`) via the
existing `JiraOAuthManager` — unchanged.

---

## 8. Open Questions

> Resolved-in-brainstorm questions are echoed here for the audit trail; the
> spec body already reflects each resolution.

- [x] What channel string should web sessions use? — *Resolved in brainstorm*: `"web"`, no cross-channel sharing with Telegram.
- [x] Persistence depth for the credential? — *Resolved in brainstorm*: DocumentDB-backed (`users_integrations`) with Redis as fast-path cache; auto-rehydrate the toolkit on next session.
- [x] Toolkit registration scope (per-agent vs global)? — *Resolved in brainstorm*: per-agent opt-in (decision A=iii); JiraToolkit is auto-rehydrated only into agents the user has explicitly enabled it on.
- [x] OAuth UX flow? — *Resolved in brainstorm*: popup window with `window.opener.postMessage` callback; iframe is non-viable due to Atlassian X-Frame-Options.
- [x] Static or dynamic integrations list? — *Resolved in brainstorm*: dynamic from registry, PBAC-filtered.
- [x] How does `AuthorizationRequired` reach the chat UI? — *Resolved in brainstorm*: structured `auth_required` envelope on a single response body; AgentChat renders an inline connect pill.
- [x] DocumentDB schema — new collection or extend `user_mcp_configs`? — *Resolved in brainstorm*: new collection `users_integrations`, scoped per `(user_id, provider)`, plus `user_agent_toolkits` for per-agent enablement.
- [x] Disconnect flow — provider-side revoke? — *Resolved in brainstorm*: not required; only delete Redis + DocumentDB + session entry.
- [x] Popup callback security? — *Resolved in brainstorm*: `channel: "web"` field added to `extra_state` plus origin allowlist via `WEB_OAUTH_ALLOWED_ORIGINS`.
- [x] How is `request.origin` extracted in aiohttp? — *Resolved in spec*: read `request.headers.get("Origin")`. If body's `return_origin` is provided, it takes precedence (must still be in `WEB_OAUTH_ALLOWED_ORIGINS`). If neither present, return HTTP 400.

> Genuinely open — must be resolved before or during implementation:

- [x] **Q-A** PBAC action namespace. Proposed: `integration:list`, `integration:connect`, `integration:disconnect` (provider supplied as EvalContext attribute, not baked into action). Alternative: per-provider variants like `integration:connect:jira`. Decide before writing the policy fixtures. — *Owner: Jesus*: proposed.
- [ ] **Q-B** Default PBAC policy for `integration:*` when no PDP is configured. Current AgentTalk convention is fail-open; should integrations follow suit, or fail-closed (more conservative for credential surfaces)? — *Owner: Jesus + Security*: fail-closed
- [ ] **Q-C** UX of empty menu. If PBAC filters out everything, should the `+ Integrations` toolbar button hide entirely, or always render with an "No integrations available" empty state? — *Owner: Jesus*: always render
- [ ] **Q-D** Auto-retry the user's last prompt after a successful connect, or require an explicit user retry? Spec defaults to **explicit retry** (deterministic; no surprise tool calls). — *Owner: Jesus*: no auto-retry, explicit retry
- [ ] **Q-E** DocumentDB migration story for the two new collections. Spec assumes lazy collection creation on first write (mirrors `MCPPersistenceService` behaviour). Confirm during implementation. — *Owner: Jesus*: confirm during implementation

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (single worktree, sequential tasks).
- **Branch / worktree**:
  ```bash
  git checkout dev
  git worktree add -b feat-143-cross-repository-jiratoolkit-oauth2-3lo \
    .claude/worktrees/feat-143-cross-repository-jiratoolkit-oauth2-3lo HEAD
  ```
- **Cross-repo coordination**: tasks must be paired across `ai-parrot` and
  `navigator-frontend-next`. Each backend task that introduces a new endpoint
  ships with its frontend axios wrapper in the same conceptual unit.
  Suggested pairing:
  - Pair 1: Module 1+2 (models + registry).
  - Pair 2: Module 3+4 (Jira provider + persistence).
  - Pair 3: Module 5 (service) + Module 12 (frontend api/integrations.ts).
  - Pair 4: Module 6+10+11 (handler + routes + conf) + Module 13 (popup helper).
  - Pair 5: Module 7 (callback web branch + templates) — backend-only.
  - Pair 6: Module 8 (AgentTalk envelope translator) + Module 15
    (`ConnectIntegrationPill.svelte` + AgentChat wiring).
  - Pair 7: Module 9 (UserObjectsHandler hydration) — backend-only.
  - Pair 8: Module 14 (`IntegrationsMenu.svelte`) — frontend-only; depends on
    Pairs 3 & 4.
  - Pair 9: end-to-end smoke tests.
- **Cross-feature dependencies**: none required to be merged first. Spec phase
  should still confirm via
  `git log --since=2026-04-01 -- packages/ai-parrot/src/parrot/handlers/agent.py packages/ai-parrot/src/parrot/auth/routes.py packages/ai-parrot/src/parrot/handlers/user_objects.py`
  before opening the worktree, to surface any in-flight refactors that would
  conflict with Module 7, 8, or 9.
- **Rationale**: Internal parallelism (3 tracks: backend framework, frontend
  module, persistence+PBAC) saves at most ~1 dev-week, while serialisation makes
  the cross-repo schema contract (`IntegrationDescriptor`, `AuthRequiredEnvelope`)
  much easier to review. Define those two models first, then the rest can be
  reviewed pair-by-pair.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-04 | Jesus Lara | Initial draft, derived from `cross-repository-jiratoolkit-oauth2-3lo.brainstorm.md` Recommended Option B. |

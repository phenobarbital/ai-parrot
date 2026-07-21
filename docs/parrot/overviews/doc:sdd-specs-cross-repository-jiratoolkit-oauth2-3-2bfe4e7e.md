---
type: Wiki Overview
title: 'Feature Specification: Cross-Repository JiraToolkit OAuth2 3LO (Web AgentChat)'
id: doc:sdd-specs-cross-repository-jiratoolkit-oauth2-3lo-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: integration (`/connect_jira` → inline button → `/api/auth/jira/callback`
  → token in
relates_to:
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.exceptions
  rel: mentions
- concept: mod:parrot.auth.jira_oauth
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.handlers.agent
  rel: mentions
- concept: mod:parrot.handlers.integrations
  rel: mentions
- concept: mod:parrot.handlers.user_objects
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
---

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

…(truncated)…

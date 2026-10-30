---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server, ai-parrot-integrations, ai-parrot-tools, docs]
tags: [oauth2, connections, credentials, identity-vault, principal, telegram, msteams, slack]
# FEAT-773 was reserved by /sdd-proposal via reserve_ids.py (ledger commit 5fa785952,
# label delegated-auth-connections) — reused here intentionally; no second reservation.
reuse_feature_id: FEAT-773
---

# Feature Specification: Delegated Auth Connections — S-1 Connections Core (principal-keyed, channel-neutral OAuth2 3LO on `parrot.auth.oauth2`)

**Feature ID**: FEAT-773
**Date**: 2026-10-30
**Author**: Jesus Lara (with Claude Fable 5.1)
**Status**: approved
**Target version**: 1.3.0

> **Source**: proposal `sdd/proposals/delegated-auth-connections.proposal.md` (FEAT-773, status `accepted`,
> research state `sdd/state/FEAT-773/`), itself the research-grounded rewrite of the brainstorm
> `artifacts/Brainstorm Delegated Auth Connections (OAuth2 3LO core + channel consumers).md` (Option B).
> This is **S-1 of five specs** (decision at spec time: S-1 core now; S-2 Telegram, S-3a web + Slack,
> S-3b Teams and S-4 CLI / local MCP follow as separate `/sdd-spec` runs with their own FEAT ids once S-1's
> contracts are frozen; S-4 was added 2026-10-30 after the spec was first committed).
> Rejected alternatives (A: extend the Jira path per provider × channel; C: navigator-auth as remote token
> broker; D: SPA-driven OAuth) are NOT carried into this body — see the brainstorm §5.

---

## 1. Motivation & Business Requirements

### Problem Statement

Users cannot connect their own Office 365, Jira or any other OAuth2 (3LO) service once and use it from every
channel. The delegated-auth stack in `parrot.auth` is far more complete than the brainstorm assumed — a generic
3LO engine (`AbstractOAuth2Manager`), a provider registry (`OAuth2ProviderRegistry`), a web connections service
(`IntegrationsService`), a generic per-provider callback (`make_oauth2_callback`), a per-user credential broker
(`CredentialBroker`) and a principal-keyed durable owner for the Jira grant (navigator-auth Identity Vault,
FEAT-735) all exist — but three defects remain (proposal §1, C1–C14):

1. **Every live key embeds the channel.** `AbstractOAuth2Manager` writes `oauth2:{provider}:{channel}:{user_id}`
   and vault name `oauth2_{provider}_{channel}_{user_id}`; `JiraOAuthManager` writes
   `jira:oauth:{channel}:{user_id}`; `JiraToolkit` caches clients by `"{channel}:{user_id}"`. A Jira account
   connected on Telegram is invisible to the same person on the web.
2. **Jira is not on the generic engine.** `JiraOAuthManager` is a parallel implementation (no PKCE, own nonce and
   lock keys) with its own callback `/api/auth/jira/callback` that dispatches completion by **direct in-process
   calls** into channel code, which core lazily imports from `ai-parrot-integrations`.
3. **Two needs-auth signals.** `ToolManager` converts `AuthorizationRequired` into
   `ToolResult(status="authorization_required")`, while `CredentialRequired` (FEAT-264 broker seam) bubbles
   uncaught through server handlers. The MCP client still binds `user_id` at `add_oauth_mcp_server` time.

### Goals

- **G1 — Principal-keyed connections.** Every OAuth2 credential, hot cache entry and metadata row is keyed by the
  Navigator principal (`auth.users.user_id`, bigint) with the Entra OID / e-mail stored as a secondary identity
  column; `channel` is an attribute, never part of a key (U1).
- **G2 — One connection, all agents, all channels.** A connection made on any channel is visible and usable on every
  channel and by every agent the principal can reach; per-agent enablement rows are retired (U2 — reverses the
  FEAT-144 decision explicitly).
- **G3 — One engine, data-driven providers.** `JiraOAuthManager` becomes a subclass of the generic engine; provider
  metadata, endpoints, scopes, PKCE and refresh policy are a typed descriptor; only provider-specific
  post-exchange logic stays as a registered, typed hook (decision #6, S10).
- **G4 — Durable owner is the Identity Vault.** For every 3LO provider the durable copy lives in navigator-auth's
  `auth.user_identities` through a `CredentialStore` Protocol injected by the server; Redis stays the live tool
  path; a callback is only reported successful after the durable write (FEAT-735 extended; S2).
- **G5 — One needs-auth contract.** `AuthorizationRequired` and `CredentialRequired` serialize to the same
  `AuthRequiredPayload` in `ToolManager` and AgentTalk, including device-code fields (S8).
- **G6 — Decoupled completion.** Callbacks publish `connection.completed` / `connection.revoked` /
  `connection.refresh_failed` through an in-core `ChannelNotifier` registry (load-bearing) and a publish-only
  Streams bus (additive); core never imports channel code (U5).
- **G7 — Principal-level API.** `/api/v1/connections*` lists, starts, inspects and revokes connections for the
  authenticated principal with PBAC on every mutating route (S4); the agent-scoped routes remain as aliases.
- **G8 — Functional parity for the production Jira flow** on Telegram, Slack and Teams through notifier adapters;
  linked users (identity row present) never re-connect; unlinked Telegram users are asked to `/login` and
  re-connect (U3).
- **G9 — MCP resolves the principal per call** (no add-time `user_id`), reusing the FEAT-264 broker seam (S9).

### Non-Goals (explicitly out of scope)

- Generic `/connect <provider>` channel commands, `ConnectionChannel` protocol work and the Telegram legacy-key
  cutover — **S-2**.
- User-level Connections panel, WS push on completion (cross-process `UserSocketManager`), automatic retry after
  connect, Slack first-link owner fix, O365 store consolidation (device-code `VaultTokenSync o365:*`) — **S-3a**.
- Teams `ChannelNotifier` beyond the compatibility adapter, Adaptive-Card connect action — **S-3b**.
- The CLI consumer surface — `AgentREPL`, the agent daemon and the `parrot mcp-local` stdio servers used by
  Claude Code / Codex: a CLI `PrincipalResolver` that maps a local login to a Navigator `user_id` (today
  `parrot/cli/identity.py` builds a `channel="cli"` `PermissionContext` from `O365_PRINCIPAL`, Entra-keyed and
  device-code only), an out-of-process connect flow (print / open the authorize URL, learn completion by polling
  `/api/v1/connections` or from the `connection.*` bus), and a remote `CredentialStore` backend so out-of-process
  MCP tools resolve connections through the server instead of the Identity Vault directly — **S-4**. S-1 only keeps
  the seams open: `channel="cli"` is a valid `Principal.channel`, `start_connect` is channel-agnostic, and
  `CredentialStore` is a Protocol.
- `OAuthRoutesMixin` on `HttpMCPServer` and the navigator-auth OAuth 2.1 authorization server (parrot as a
  *resource server*, opposite direction).
- `CredentialBroker` / `CredentialResolverFactory` / `CanonicalIdentityMapper` internals (consumed, not changed).
- A2A suspend/resume (`register_a2a_resume_hook`) and the MSAgentSDK Adaptive/OAuth-card lane (unchanged).
- BYOK per-user LLM keys, FEAT-063 DB credentials, Fireflies/work.iq static-key and OBO resolvers.
- Multi-account selection UI (schema supports it; v1 is single account per provider with replace-on-reconnect, S3).
- Removing the FEAT-083 AgentTalk hot-swap placeholder (`jira_connect_tool.py`) — S-3a, once the web path is on
  the broker seam end to end.
- navigator-auth as a remote token broker (brainstorm Option C; a later `CredentialStore` backend).

---

## 2. Architectural Design

### Overview

The feature evolves `parrot.auth.oauth2` **in place** (U4) — no new package, no renames.

**Principal.** A `Principal` (M1) is `(user_id: Navigator bigint as str, canonical_identity: Optional[str] =
Entra OID or lower-cased e-mail, tenant_id, channel, channel_user_id)`. A `PrincipalResolver` Protocol maps
`(channel, channel_user_id)` to a `Principal`; the server implements it over navigator-auth `auth.user_identities`
(`IdentityStore.find_user_by_provider_account`) and the web session; core only holds the Protocol and a module-level
registration function, mirroring `set_vault_credential_store`. Resolution failing means **no principal** — the
caller fails closed (`AuthorizationRequired` with the channel's link instruction), never a channel-keyed fallback.

**Engine.** `AbstractOAuth2Manager` (M2) keeps its public method names but keys everything by principal:
Redis `oauth2:{provider}:{user_id}`, lock `lock:oauth2:{provider}:refresh:{user_id}`; the vault name is owned by
the `CredentialStore`. `create_authorization_url(channel, user_id, extra_state, *, principal)` binds the
principal into the signed nonce payload (`nav_user_id`, `channel`, `channel_user_id`, `canonical_identity`);
`handle_callback` verifies the binding and fails closed when it is missing (S1). `_persist_token` writes the
durable `CredentialStore` **first** and raises `CredentialPersistenceError` on failure — Redis is written only
after a successful durable write (S2). `_refresh_tokens` distinguishes a typed `InvalidGrantError` (revoke +
`connection.refresh_failed`) from `RefreshTransientError` (no revoke; S7). `revoke()` calls a best-effort
`_revoke_remote()` hook, deletes locally and publishes `connection.revoked`. Legacy channel-scoped keys
(`oauth2:{p}:{c}:{u}`, vault `oauth2_{p}_{c}_{u}`, `jira:oauth:{c}:{u}`) are read once for a bound principal,
rewritten under the principal key and deleted; reads of legacy keys stop after `OAUTH2_LEGACY_KEYS_UNTIL`.

**Providers.** `OAuth2ProviderDescriptor` (M3) is a typed Pydantic model (metadata, `authorization_url`,
`token_url`, `revoke_url`, scopes, `client_type`, `pkce`, `refresh_policy`, `identity_probe`,
`extra_authorize_params`, `post_exchange` hook **name**). `StandardOAuth2Manager(AbstractOAuth2Manager)`
implements the RFC 6749 authorization-code exchange and refresh plus a JSON-path identity probe from the
descriptor; `DescriptorOAuth2Provider(OAuth2Provider)` exposes it in the existing `OAuth2ProviderRegistry`.
Post-exchange hooks are Python callables registered in a typed `PostExchangeHookRegistry` — never import paths
loaded from YAML (S10). `O365OAuthManager` stays a hand-written subclass with typed refresh-error classification (M2); `JiraOAuthManager` (M7) becomes a
`StandardOAuth2Manager` subclass with the `atlassian_accessible_resources` hook (TASK-4418 helpers).

**Completion.** `ConnectionEventPublisher` (M4) receives a `ConnectionEvent` (no token material) from the engine,
awaits the `ChannelNotifier` registered for `event.channel` (failures are logged, never fail the callback),
appends an entry to `parrot.security.audit_ledger.AuditLedger`, and publishes on a publish-only Streams
`EventBus` when one is attached (pattern: `observability/fanout.py`). Delivery is **in-process**: the callback and
the channel notifier share one aiohttp app today (verified: `app['jira_oauth_notifier']`,
`app['msteams_jira_oauth_notifier']`, `app['slack_jira_oauth_notifier']`); the constraint is documented and the
cross-process web path is S-3a (S6).

**Service and API.** `IntegrationsService` (M6) takes `channel` as a parameter, gains `list_for_principal`, checks
PBAC `integration:connect` / `integration:disconnect` with the requested scopes (S4), drops `confirm_enable` and
the `user_agent_toolkits` table (U2), and reads status from the durable owner for every provider. A new
`ConnectionsHandler` serves `/api/v1/connections*`; the agent-scoped `IntegrationsHandler` keeps its routes with
`/enable` as a compatibility no-op until S-3a removes the UI call (S5). `UserObjectsHandler.configure_tool_manager`
hydrates toolkits from the principal's connections instead of enablement rows.

**Signals.** `AuthRequiredPayload` (M5) is the union of `AuthorizationRequired` and `CredentialRequired` fields;
`ToolManager.execute_tool` converts both to `ToolResult(status="authorization_required",
metadata=payload.model_dump())`; AgentTalk converts both to `AuthRequiredEnvelope`.

**MCP.** `add_oauth_mcp_server` / `create_oauth_mcp_server` no longer require `user_id`; the per-call principal
reaches the MCP transport through the existing `inject_broker_credential` + `header_provider(ReadonlyContext)`
path (M9), extended through the client and HTTP transport with request-local headers and principal-isolated sessions.

### Component Diagram

```
channel (web | telegram | slack | msteams)
   │ (channel, channel_user_id)
   ▼
PrincipalResolver ──► Principal(user_id, canonical_identity, channel, channel_user_id)      [M1, server impl M8]
   │
   ▼
IntegrationsService.start_connect(user_id, provider, channel, principal, scopes) ── PBAC integration:connect   [M6]
   │
   ▼
OAuth2ProviderRegistry.get(provider).manager  ──►  AbstractOAuth2Manager / StandardOAuth2Manager          [M2, M3]
   │ create_authorization_url(..., principal)  →  nonce payload {nav_user_id, channel, channel_user_id, …}
   │
   ▼  consent at IdP
GET /api/auth/oauth2/{provider}/callback  (make_oauth2_callback; Jira alias /api/auth/jira/callback)     [M7]
   │ handle_callback(code, state): verify principal → exchange → identity probe → post_exchange hook
   │ _persist_token: CredentialStore.save (Identity Vault, M8) ──► Redis oauth2:{p}:{user_id}
   │
   ▼
ConnectionEventPublisher.publish(connection.completed)                                                   [M4]
   ├── ChannelNotifierRegistry.get(channel).notify(event, state)   (telegram/slack/msteams adapters, M8)
   ├── AuditLedger.append(...)                                      (parrot.security.audit_ledger)
   └── EventBus(streams, publish_only).publish(...)                 (additive)

tool call ──► ToolManager.execute_tool ──► AbstractTool.execute (broker seam) / toolkit._pre_execute
                 │ OAuthCredentialResolver.resolve(channel, channel_user_id) → PrincipalResolver → manager.get_valid_token(user_id)
                 ├── hit  → credential (ContextVar / client cache keyed by principal)
                 └── miss → AuthorizationRequired | CredentialRequired → AuthRequiredPayload → ToolResult(status="authorization_required")  [M5]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/auth/oauth2_base.py::AbstractOAuth2Manager` | modifies | principal keys, principal binding in state, `CredentialStore`, typed refresh outcomes, `_revoke_remote`, event publication, legacy read |
| `parrot/auth/oauth2/registry.py::OAuth2Provider`, `OAuth2ProviderRegistry` | extends | `DescriptorOAuth2Provider`; registry unchanged |
| `parrot/auth/oauth2/service.py::IntegrationsService` | modifies | channel parameter, `list_for_principal`, PBAC on connect/disconnect, `confirm_enable` removed, unified status |
| `parrot/auth/oauth2/models.py` | modifies | `UsersIntegrationRow`/`IntegrationDescriptor` fields; `AuthRequiredEnvelope` superset fields; `UserAgentToolkitRow` removed |
| `parrot/auth/oauth2/persistence.py` | modifies | `list_users_integrations(user_id)`; `user_agent_toolkits` functions removed |
| `parrot/auth/oauth2_routes.py::make_oauth2_callback` | modifies | principal verification result, event publication, no web-only branch for persistence |
| `parrot/auth/routes.py::setup_jira_oauth_routes` | modifies (replace) | mounts the generic callback at `/api/auth/jira/callback`; `jira_oauth_callback` and the lazy integrations imports are deleted |
| `parrot/auth/jira_oauth.py::JiraOAuthManager` | modifies (re-base) | subclass of `StandardOAuth2Manager`; public API preserved; `CredentialSink` → `CredentialStore`; legacy `jira:oauth:*` read |
| `parrot/auth/credentials.py::OAuthCredentialResolver`, `CredentialRequired` | modifies | resolves the principal before `get_valid_token`; `to_payload()` |
| `parrot/auth/exceptions.py::AuthorizationRequired` | modifies | `to_payload()` |
| `parrot/tools/manager.py::ToolManager.execute_tool` | modifies | catch `CredentialRequired` too; one payload |
| `parrot_tools/jiratoolkit.py::JiraToolkit` | modifies | `credential_provider = "jira"`; client cache keyed by principal |
| `parrot/mcp/client.py::MCPClientConfig`, `parrot/mcp/integration.py::add_oauth_mcp_server`, `create_oauth_mcp_server` | modifies | `user_id` optional; per-call principal via broker injection |
| `ai-parrot-server handlers/integrations.py::IntegrationsHandler` | modifies | `_post_enable` compatibility no-op; delegates to new service signatures |
| `ai-parrot-server handlers/user_objects.py::UserObjectsHandler.configure_tool_manager` | modifies | hydrate from `list_users_integrations` |
| `ai-parrot-server handlers/agent.py` (AgentTalk) | modifies | catch `CredentialRequired` too |
| `ai-parrot-server manager/manager.py::BotManager._register_oauth2_providers` | modifies | register every configured provider from descriptors; store managers at `app['oauth2_manager_<id>']` |
| `ai-parrot-server services/identity_credential_sink.py::IdentityVaultCredentialSink` | modifies (generalize) | `IdentityVaultCredentialStore` for any provider / `AbstractOAuth2TokenSet` |
| `ai-parrot-server services/identity_mapping.py::IdentityMappingService` | uses | `IdentityPrincipalResolver` reads `auth.user_identities` through `IdentityStore` |
| `ai-parrot-integrations integrations/manager.py::_build_jira_credential_sink` | modifies (replace) | `_build_credential_store`, `_build_principal_resolver`, notifier adapter registration |
| `ai-parrot-integrations telegram/jira_commands.py`, `msteams/oauth_callback.py`, `slack/oauth_callback.py` | extends | `ChannelNotifier` adapters wrapping the existing notifiers; Telegram `/connect_jira` passes the session principal |
| `parrot/security/audit_ledger.py::AuditLedger` | uses | one entry per connection event |
| `parrot/observability/fanout.py` | pattern | `setup_connection_fanout(bus)` mirrors `setup_event_fanout` |
| `parrot/conf.py` | extends | `OAUTH2_LEGACY_KEYS_UNTIL`, `OAUTH2_<PROVIDER>_CLIENT_ID/_CLIENT_SECRET/_REDIRECT_URI`, `OAUTH2_PROVIDERS_FILE` |

### Data Models

```python
# parrot/auth/principal.py  (new, M1)
class Principal(BaseModel):
    """The platform identity a connection belongs to (U1: Navigator id primary, OID/e-mail secondary)."""
    user_id: str                       # Navigator auth.users.user_id (bigint, serialized as str)
    canonical_identity: Optional[str]  # Entra OID or lower-cased e-mail (CanonicalIdentityMapper output)
    tenant_id: Optional[str] = None
    channel: str                       # originating channel: web | telegram | slack | msteams | a2a | cli
    channel_user_id: str               # raw id on that channel (telegram_id, aad_object_id, slack team:user, web user_id)

# parrot/auth/oauth2/descriptor.py  (new, M3)
class RefreshPolicy(BaseModel):
    """Informational refresh facts per provider (R6, verified 2026-10-30 — see §7 External provider facts).

    Regardless of `rotating`, a `refresh_token` present in a token response ALWAYS replaces the stored one
    (Microsoft issues a new one on every use but does not revoke the old one)."""
    rotating: bool = False              # True: the used refresh token is disabled on use (old one must never be re-sent)
    sliding: bool = False               # True: refresh_lifetime_s is an inactivity window reset by each refresh;
                                        # False: refresh_lifetime_s is absolute from issue (re-consent when it lapses)
    refresh_lifetime_s: Optional[int] = None
    access_lifetime_s: Optional[int] = None

class IdentityProbe(BaseModel):
    url: str
    account_id_path: str               # JSON pointer / dotted path, e.g. "account_id" or "id"
    display_name_path: Optional[str] = None
    email_path: Optional[str] = None

class OAuth2ProviderDescriptor(BaseModel):
    provider_id: str
    display_name: str
    icon: str = ""
    authorization_url: str
    token_url: str
    revoke_url: Optional[str] = None
    default_scopes: List[str]
    client_type: Literal["confidential", "public"] = "confidential"
    pkce: Literal["required", "optional", "none"] = "required"
    refresh_policy: RefreshPolicy = RefreshPolicy()
    identity_probe: Optional[IdentityProbe] = None
    extra_authorize_params: Dict[str, str] = {}
    post_exchange: Optional[str] = None       # name in PostExchangeHookRegistry (never an import path)
    pbac_action_namespace: str = "integration"
    # client_id / client_secret / redirect_uri come from navconfig OAUTH2_<PROVIDER>_*, never from the descriptor

# parrot/auth/oauth2/events.py  (new, M4)
ConnectionEventKind = Literal["connection.completed", "connection.revoked", "connection.refresh_failed"]

class ConnectionEvent(BaseModel):
    kind: ConnectionEventKind
    user_id: str
    canonical_identity: Optional[str] = None
    tenant_id: Optional[str] = None
    provider: str
    account_id: str = ""
    display_name: str = ""
    channel: str
    occurred_at: float
    reason: Optional[str] = None        # refresh_failed only; never token material

# parrot/auth/credentials.py  (M5)
class AuthRequiredPayload(BaseModel):
    """Superset of AuthorizationRequired + CredentialRequired (S8); serialized by ToolManager and AgentTalk."""
    provider: str
    auth_url: Optional[str] = None
    scopes: List[str] = []
    tool_name: Optional[str] = None
    message: str = ""
    auth_kind: Optional[AuthKind] = None   # oauth2 | device_code | obo | static_key | mcp
    user_code: Optional[str] = None
    verification_uri: Optional[str] = None
    expires_in: Optional[int] = None

# parrot/auth/oauth2/models.py  (M6 — changes to existing models)
class UsersIntegrationRow(BaseModel):      # keyed (user_id, provider); v1 single account per provider (S3)
    user_id: str
    canonical_identity: Optional[str] = None   # NEW (U1 secondary column)
    provider: str
    channels: List[str] = []                   # REPLACES channel: str = "web" — every channel that connected/used it
    status: Literal["active", "revoked", "needs_reconnect"]
    account_id: str = ""
    display_name: str = ""
    email: Optional[str] = None
    scopes: List[str] = []
    scopes_granted: List[str] = []             # NEW
    expires_at: Optional[float] = None         # NEW (access token expiry, informational)
    cloud_id: Optional[str] = None
    site_url: Optional[str] = None
    connected_at: datetime
    updated_at: Optional[datetime] = None      # NEW (S-4 pre-check): bumped on every save / replace-on-reconnect / status change
    last_used_at: Optional[datetime] = None

class IntegrationDescriptor(BaseModel):    # enabled_on_agent REMOVED (U2); NEW: channels, scopes_granted, expires_at, updated_at
                                           # (an out-of-process CLI polls GET /api/v1/connections and detects a completed
                                           #  connect OR reconnect by status + updated_at > its start time)

class AuthRequiredEnvelope(BaseModel):     # NEW optional fields: auth_kind, user_code, verification_uri, expires_in
```

### New Public Interfaces

```python
# parrot/auth/principal.py
class PrincipalResolver(Protocol):
    async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]: ...
def set_principal_resolver(resolver: PrincipalResolver) -> None: ...
def get_principal_resolver() -> Optional[PrincipalResolver]: ...
async def resolve_principal(channel: str, channel_user_id: str) -> Optional[Principal]: ...

# parrot/auth/oauth2_base.py
class CredentialStore(Protocol):
    async def load(self, user_id: str, provider: str) -> Optional[Dict[str, Any]]: ...
    async def save(self, user_id: str, provider: str, payload: Dict[str, Any], *, minted: bool,
                   principal: Optional[Principal], state_payload: Optional[Dict[str, Any]]) -> None: ...
    async def delete(self, user_id: str, provider: str) -> None: ...
class CredentialPersistenceError(RuntimeError): ...
class InvalidGrantError(PermissionError): ...
class RefreshTransientError(RuntimeError): ...

# parrot/auth/oauth2/descriptor.py
class StandardOAuth2Manager(AbstractOAuth2Manager): ...
class DescriptorOAuth2Provider(OAuth2Provider): ...
class PostExchangeHookRegistry: register(name, fn) / get(name)
def load_provider_descriptors(source: str | Path | Sequence[Mapping[str, Any]]) -> List[OAuth2ProviderDescriptor]: ...
def register_descriptor_providers(descriptors, *, app, credential_store, event_publisher) -> List[DescriptorOAuth2Provider]: ...

# parrot/auth/oauth2/events.py
class ChannelNotifier(Protocol):
    channel: str
    async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None: ...
class ChannelNotifierRegistry: register(notifier) / get(channel) / all() / _reset()
class ConnectionEventPublisher: publish(event, state_payload) ; setup_connection_fanout(bus) ; shutdown()

# ai-parrot-server
class IdentityVaultCredentialStore(CredentialStore)        # services/identity_credential_sink.py (generalized)
class IdentityPrincipalResolver(PrincipalResolver)          # services/identity_principal.py (new)
class ConnectionsHandler(BaseView)                          # handlers/connections.py (new)
#   GET    /api/v1/connections
#   POST   /api/v1/connections/{provider}/start      body: {return_origin?, scopes?}
#   GET    /api/v1/connections/{provider}
#   DELETE /api/v1/connections/{provider}
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Principal model + resolver Protocol | yes | Pydantic model + Protocol + module-level setter/getter mirroring `set_vault_credential_store` (vault_utils.py:46); fail closed on `None` | — |
| M2: Principal-keyed `AbstractOAuth2Manager` | no | — | key migration, durable-first persistence and typed refresh outcomes touch the live O365 path; thinking model owns the ordering and the legacy-read rules |
| M3: Typed descriptor + `StandardOAuth2Manager` | yes | descriptor fields fixed in §2; RFC 6749 exchange/refresh; JSON-path probe; hook registry API fixed | — |
| M4: Connection events + notifier registry + publisher | yes | models fixed in §2; publisher order notifier → audit → bus; failures logged never raised; `_validate_bus` rule copied from fanout.py:74 | — |
| M5: Unified needs-auth payload | yes | `AuthRequiredPayload` fields fixed; both exceptions gain `to_payload()`; ToolManager/AgentTalk catch both | — |
| M6: Channel-neutral service, `/api/v1/connections`, hydration | no | — | removes `user_agent_toolkits` (production data) and changes the hydration path; thinking model owns the compatibility no-op and the migration of existing rows |
| M7: Jira on the generic engine | no | — | production flow; legacy `jira:oauth:*` dual read and callback alias must be reasoned about, not transcribed |
| M8: Server/integrations adapters (store, resolver, notifier adapters, BotManager registration) | no | — | atomic replacement/deletion and metadata-preserving re-encryption require verified transaction and cipher APIs |
| M9: MCP per-call principal | no | — | bearer forwarding crosses core and server transport; request and session isolation require end-to-end verification |
| M10: Docs, audit and re-encryption | no | — | mixed-key verification and key-retirement gate require all-column checks and M8 transaction integration |

### Module 1: Principal model and resolver Protocol
- **Path**: `packages/ai-parrot/src/parrot/auth/principal.py` (new); `packages/ai-parrot/src/parrot/auth/__init__.py` (export)
- **Responsibility**: define `Principal`, the `PrincipalResolver` Protocol, module-level registration and
  `resolve_principal()`; a `WebPrincipalResolver` default that treats `channel == "web"` ids as Navigator ids
  (today's behaviour of `IntegrationsHandler._get_user_id`, handlers/integrations.py:43).
- **Depends on**: `parrot.auth.identity.CanonicalIdentityMapper` (identity.py:57) for `canonical_identity`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/principal.py  (new)
  class Principal(BaseModel):
      """Platform identity a connection belongs to; see §2 Data Models."""

  class PrincipalResolver(Protocol):
      async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]:
          """Return the bound Principal or None (caller fails closed)."""

  class WebPrincipalResolver:
      """channel == "web": channel_user_id IS the Navigator user_id; other channels → None."""
      async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]: ...

  def set_principal_resolver(resolver: PrincipalResolver) -> None:
      """Server registers IdentityPrincipalResolver at startup (mirrors set_vault_credential_store, vault_utils.py:46)."""
  def get_principal_resolver() -> PrincipalResolver: ...   # default WebPrincipalResolver
  async def resolve_principal(channel: str, channel_user_id: str) -> Optional[Principal]: ...
  ```
  `parrot/auth/__init__.py` `_LAZY_ATTRS` gains `Principal`, `PrincipalResolver`, `set_principal_resolver`,
  `resolve_principal` (`# verified: auth/__init__.py:36-83 lazy map`).

### Module 2: Principal-keyed `AbstractOAuth2Manager`
- **Path**: `packages/ai-parrot/src/parrot/auth/oauth2_base.py`, `packages/ai-parrot/src/parrot/auth/o365_oauth.py` (modify)
- **Responsibility**: principal keys; principal binding in the nonce payload and verification at callback (S1);
  `CredentialStore` replaces `vault_writer/reader/deleter` with durable-first persistence (S2);
  typed refresh outcomes (S7); `_revoke_remote` hook; event publication (M4); legacy-key read-rewrite-delete.
  `O365OAuthManager._refresh_request` must parse the OAuth error code: only `invalid_grant` raises
  `InvalidGrantError`; network failures, HTTP 429 and 5xx raise `RefreshTransientError`. Other OAuth errors
  (including `invalid_client`, malformed responses and non-grant 400/401 errors) surface as operational errors
  without deleting the grant or emitting `refresh_failed`. Never include token values or raw token responses in errors.
  Keep O365's subclass, endpoints and public API; the typed error change is explicitly in scope.
  Callback replacement, refresh, revoke and re-encryption serialize on the same provider/principal lock;
  acquire it once per operation (no nested lock in the store), re-read durable state after acquiring it,
  and never let an in-flight refresh restore a replaced/deleted grant. Cold-cache fills must also be protected
  against concurrent deletion/replacement. Migration must not resurrect credentials after disconnect.
- **Depends on**: M1, M4; `parrot.security.vault_utils` for the default `VaultUtilsCredentialStore`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/oauth2_base.py  (modifies)
  _TOKEN_KEY_TEMPLATE = "oauth2:{provider}:{user_id}"                       # verified: oauth2_base.py:39 (was …:{channel}:{user_id})
  _LOCK_KEY_TEMPLATE = "lock:oauth2:{provider}:refresh:{user_id}"           # verified: oauth2_base.py:41
  _LEGACY_TOKEN_KEY_TEMPLATE = "oauth2:{provider}:{channel}:{user_id}"      # new — read-only during the window
  _LEGACY_VAULT_NAME_TEMPLATE = "oauth2_{provider}_{channel}_{user_id}"     # verified: oauth2_base.py:44 (renamed)

  class CredentialStore(Protocol): ...                                      # §2 New Public Interfaces
  class VaultUtilsCredentialStore:
      """Default store over vault_utils (store/retrieve/delete_vault_credential, vault_utils.py:92/…/…); name oauth2_{provider}_{user_id}."""
  class CredentialPersistenceError(RuntimeError): ...
  class InvalidGrantError(PermissionError):
      """Provider rejected the refresh token (invalid_grant); the grant is revoked locally."""
  class RefreshTransientError(RuntimeError):
      """Network / 5xx during refresh; the grant is kept."""

  class AbstractOAuth2Manager(ABC):                                         # verified: oauth2_base.py:89
      def __init__(self, client_id: str, redirect_uri: str, *, client_secret: Optional[str] = None,
                   app: Optional[web.Application] = None, redis_url: Optional[str] = None, redis_client: Any = None,
                   scopes: Optional[List[str]] = None, http_session: Optional[aiohttp.ClientSession] = None,
                   credential_store: Optional[CredentialStore] = None,          # REPLACES vault_writer/vault_reader/vault_deleter (oauth2_base.py:131-133)
                   event_publisher: Optional["ConnectionEventPublisher"] = None,  # new
                   callback_path: Optional[str] = None) -> None: ...            # verified: oauth2_base.py:120-134

      def _token_key(self, user_id: str) -> str: ...                            # verified: oauth2_base.py:251 (channel param dropped)
      def _lock_key(self, user_id: str) -> str: ...                             # verified: oauth2_base.py:259
      async def create_authorization_url(self, channel: str, user_id: str,
                                         extra_state: Optional[Dict[str, Any]] = None, *,
                                         principal: Optional[Principal] = None) -> Tuple[str, str]:
          """Bind principal (nav_user_id, channel, channel_user_id, canonical_identity) into the nonce payload;
          raise ValueError when principal is None and user_id is not a resolvable principal."""   # verified: oauth2_base.py:298
      async def handle_callback(self, code: str, state: str) -> Tuple[AbstractOAuth2TokenSet, Dict[str, Any]]:
          """Consume nonce → verify principal binding (fail closed) → exchange → probe → post_exchange →
          _persist_token (durable first) → publish connection.completed."""                       # verified: oauth2_base.py:354
      async def _persist_token(self, principal: Principal, token_set: AbstractOAuth2TokenSet, *,
                               minted: bool, state_payload: Optional[Dict[str, Any]] = None) -> None:
          """CredentialStore.save FIRST (raise CredentialPersistenceError on failure), then Redis."""  # verified: oauth2_base.py:409
      async def get_valid_token(self, channel: str, user_id: str) -> Optional[AbstractOAuth2TokenSet]:
          """user_id is the principal; cache → store → legacy (channel, user_id) read-rewrite → refresh."""  # verified: oauth2_base.py:461
      async def _read_legacy_token(self, channel: str, channel_user_id: str, user_id: str) -> Optional[AbstractOAuth2TokenSet]:
          """Read oauth2:{p}:{channel}:{channel_user_id} and the legacy vault name; rewrite under user_id; delete legacy;
          no-op after OAUTH2_LEGACY_KEYS_UNTIL."""
      async def revoke(self, channel: str, user_id: str) -> None:
          """_revoke_remote (best effort) → store.delete → Redis delete → publish connection.revoked."""  # verified: oauth2_base.py:497
      async def _refresh_tokens(self, channel: str, user_id: str, token_set: AbstractOAuth2TokenSet) -> AbstractOAuth2TokenSet:
          """InvalidGrantError → revoke + connection.refresh_failed; RefreshTransientError → keep grant."""  # verified: oauth2_base.py:507
      async def _revoke_remote(self, token_set: AbstractOAuth2TokenSet) -> None:
          """Default no-op hook; subclasses/descriptors with revoke_url implement it."""
      # abstract hooks unchanged: _exchange_code (:578), _refresh_request (:594), _discover_identity (:603), _build_token_set (:612)
  ```

### Module 3: Typed provider descriptor and `StandardOAuth2Manager`
- **Path**: `packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py` (new); `packages/ai-parrot/src/parrot/auth/oauth2/__init__.py` (export); `packages/ai-parrot/src/parrot/conf.py` (config keys)
- **Responsibility**: `OAuth2ProviderDescriptor`, `StandardOAuth2Manager` (generic RFC 6749 exchange/refresh +
  JSON-path identity probe + `extra_authorize_params` + PKCE per descriptor), `DescriptorOAuth2Provider`,
  `PostExchangeHookRegistry`, YAML/dict loader, registration helper. Secrets from navconfig only.
- **Depends on**: M2; `OAuth2Provider` / `register_oauth2_provider` (registry.py:20, :126).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py  (new)
  PostExchangeHook = Callable[["StandardOAuth2Manager", Dict[str, Any], "AbstractOAuth2TokenSet"], Awaitable["AbstractOAuth2TokenSet"]]

  class PostExchangeHookRegistry:
      """Typed in-code registry (S10): register(name, fn) / get(name) → KeyError when unknown. Never imports by path."""
      def register(self, name: str, fn: PostExchangeHook) -> None: ...
      def get(self, name: str) -> PostExchangeHook: ...

  class StandardOAuth2Manager(AbstractOAuth2Manager):                        # AbstractOAuth2Manager verified: oauth2_base.py:89
      """Descriptor-driven manager: endpoints, scopes, PKCE, extra params and identity probe from the descriptor."""
      def __init__(self, descriptor: OAuth2ProviderDescriptor, *, client_id: str, client_secret: Optional[str],
                   redirect_uri: str, **manager_kwargs: Any) -> None: ...
      def authorization_url_extra_params(self) -> Dict[str, str]: ...        # verified hook: oauth2_base.py:345
      async def _exchange_code(self, code: str, code_verifier: Optional[str]) -> Dict[str, Any]: ...   # hook: :578
      async def _refresh_request(self, refresh_token: str) -> Dict[str, Any]:
          """POST token_url grant_type=refresh_token; raise InvalidGrantError on invalid_grant, RefreshTransientError on 5xx/network."""  # hook: :594
      async def _discover_identity(self, access_token: str) -> Dict[str, Any]: ...  # JSON-path probe; hook: :603
      def _build_token_set(self, token_payload: Dict[str, Any], identity: Dict[str, Any]) -> AbstractOAuth2TokenSet: ...  # hook: :612
      async def _revoke_remote(self, token_set: AbstractOAuth2TokenSet) -> None: ...  # POST revoke_url when set

  class DescriptorOAuth2Provider(OAuth2Provider):                            # OAuth2Provider verified: registry.py:20
      """provider_id/display_name/icon/default_scopes/pbac_action_namespace from the descriptor; manager = StandardOAuth2Manager;
      toolkit_factory looks up ToolkitFactoryRegistry[provider_id] or returns None (MCP-like, mcp_provider.py:36 precedent)."""

  def load_provider_descriptors(source: str | Path | Sequence[Mapping[str, Any]]) -> List[OAuth2ProviderDescriptor]:
      """YAML file (OAUTH2_PROVIDERS_FILE) or dicts; validation errors raise ValueError naming the provider."""
  def register_descriptor_providers(descriptors: Sequence[OAuth2ProviderDescriptor], *, app: web.Application,
                                    credential_store: Optional[CredentialStore], event_publisher: Optional[ConnectionEventPublisher]
                                    ) -> List[DescriptorOAuth2Provider]:
      """Build managers (secrets from OAUTH2_<PROVIDER>_CLIENT_ID/_CLIENT_SECRET/_REDIRECT_URI), call manager.setup(),
      register_oauth2_provider(provider) (registry.py:126)."""
  ```
  `conf.py` gains `OAUTH2_PROVIDERS_FILE`, `OAUTH2_LEGACY_KEYS_UNTIL` and the per-provider secret keys next to
  `JIRA_CLIENT_ID` / `O365_CLIENT_ID` (`# verified: conf.py:618-627, 744-746`).

### Module 4: Connection events, audit and `ChannelNotifier` registry
- **Path**: `packages/ai-parrot/src/parrot/auth/oauth2/events.py` (new); `packages/ai-parrot/src/parrot/auth/oauth2/__init__.py` (export)
- **Responsibility**: `ConnectionEvent`, `ChannelNotifier` Protocol, `ChannelNotifierRegistry` singleton,
  `ConnectionEventPublisher` (notifier → audit → bus; never raises), `setup_connection_fanout(bus)` with the
  same `_validate_bus` rule as `observability/fanout.py:74`.
- **Depends on**: `parrot.security.audit_ledger.AuditLedger.append` (audit_ledger.py:338); optional `navigator_eventbus.EventBus`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/oauth2/events.py  (new)
  class ChannelNotifier(Protocol):
      channel: str
      async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None:
          """Deliver completion/revocation to the user on this channel; may raise — the publisher logs and continues."""

  class ChannelNotifierRegistry:
      """Singleton (same shape as OAuth2ProviderRegistry, registry.py:69): register / get / all / _reset."""

  class ConnectionEventPublisher:
      def __init__(self, *, notifiers: ChannelNotifierRegistry, audit_ledger: Optional[AuditLedger] = None,
                   bus: Any = None) -> None: ...
      async def publish(self, event: ConnectionEvent, state_payload: Optional[Dict[str, Any]] = None) -> None:
          """1) notifier for event.channel (await; exceptions logged), 2) AuditLedger.append(user_id=event.user_id,
          channel=event.channel, tool="connections", provider=event.provider, credential_material=f"{event.kind}:{event.account_id}")
          — the ledger fingerprints, never stores, the material (audit_ledger.py:338-352), 3) bus.publish when attached."""

  def setup_connection_fanout(bus: Any) -> None:
      """Require transport='streams' and publish_only=True (rule copied from fanout.py:74-87)."""
  ```

### Module 5: Unified needs-auth payload
- **Path**: `packages/ai-parrot/src/parrot/auth/credentials.py`, `packages/ai-parrot/src/parrot/auth/exceptions.py`, `packages/ai-parrot/src/parrot/tools/manager.py`, `packages/ai-parrot-server/src/parrot/handlers/agent.py`, `packages/ai-parrot/src/parrot/auth/oauth2/models.py` (modify)
- **Responsibility**: `AuthRequiredPayload`; `to_payload()` on both exceptions; `ToolManager.execute_tool` catches
  `CredentialRequired` next to `AuthorizationRequired` and emits the same `ToolResult`; AgentTalk emits
  `AuthRequiredEnvelope` for both; `OAuthCredentialResolver` resolves the principal before `get_valid_token`.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/credentials.py  (modifies)
  class AuthRequiredPayload(BaseModel): ...                                   # §2 Data Models
  class CredentialRequired(Exception):                                        # verified: credentials.py:113
      def to_payload(self, *, tool_name: Optional[str] = None) -> AuthRequiredPayload: ...
  class OAuthCredentialResolver(CredentialResolver):                          # verified: credentials.py:184
      def __init__(self, oauth_manager: Any, *, principal_resolver: Optional[PrincipalResolver] = None) -> None: ...
      async def resolve(self, channel: str, user_id: str) -> Optional[Any]:
          """principal = await resolve_principal(channel, user_id); None → return None (caller raises);
          else manager.get_valid_token(channel, principal.user_id)."""                                 # verified: credentials.py:197
      async def get_auth_url(self, channel: str, user_id: str) -> str:
          """create_authorization_url(channel, principal.user_id, principal=principal)."""              # verified: credentials.py:200

  # packages/ai-parrot/src/parrot/auth/exceptions.py  (modifies)
  class AuthorizationRequired(Exception):                                     # verified: exceptions.py:12
      def to_payload(self) -> "AuthRequiredPayload": ...

  # packages/ai-parrot/src/parrot/tools/manager.py  (modifies ToolManager.execute_tool, manager.py:1787)
  #   except (AuthorizationRequired, CredentialRequired) as auth_exc:        # verified: manager.py:2273 (AuthorizationRequired only today)
  #       payload = auth_exc.to_payload(...)  →  ToolResult(success=False, status="authorization_required", result=None,
  #                                                error=payload.message, metadata=payload.model_dump())   # verified: manager.py:2279-2290

  # packages/ai-parrot-server/src/parrot/handlers/agent.py  (modifies, agent.py:1916)
  #   except (AuthorizationRequired, CredentialRequired) as exc: envelope = AuthRequiredEnvelope(**exc.to_payload().model_dump())
  ```

### Module 6: Channel-neutral `IntegrationsService`, `/api/v1/connections`, hydration
- **Path**: `packages/ai-parrot/src/parrot/auth/oauth2/service.py`, `models.py`, `persistence.py`, `__init__.py` (modify); `packages/ai-parrot-server/src/parrot/handlers/connections.py` (new); `handlers/integrations.py`, `handlers/user_objects.py`, `manager/manager.py` routes (modify)
- **Responsibility**: `channel` parameter and `principal` on `start_connect`; `list_for_principal`; PBAC
  `integration:connect` / `integration:disconnect` with requested scopes (S4); unified status via the durable owner
  for every provider; remove `confirm_enable` and the `user_agent_toolkits` repository (U2); compatibility no-op on
  `/enable` (S5); `ConnectionsHandler`; hydration from connections.
- **Depends on**: M1, M2, M4, M5.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/oauth2/service.py  (modifies)
  class IntegrationsService:                                                  # verified: service.py:74
      async def list_for_principal(self, user_id: str, request: Any = None) -> List[IntegrationDescriptor]:
          """PBAC integration:list; one descriptor per registered provider with status/account/scopes_granted/expires_at/channels."""
      async def list_for_user(self, user_id: str, agent_id: str, request: Any = None) -> List[IntegrationDescriptor]:
          """Alias of list_for_principal (agent_id ignored; kept for the agent-scoped routes)."""   # verified: service.py:90
      async def start_connect(self, user_id: str, provider_id: str, return_origin: Optional[str] = None, *,
                              channel: str = "web", principal: Optional[Principal] = None,
                              scopes: Optional[List[str]] = None, request: Any = None,
                              extra_state: Optional[Dict[str, Any]] = None) -> ConnectInitResponse:
          """PBAC integration:connect (ctx provider, scopes) fail-closed; origin allowlist only for channel == web;
          extra_state carries channel/provider_id/return_origin/principal binding."""                # verified: service.py:291 (was user_id, agent_id, provider_id, return_origin)
      async def status(self, user_id: str, provider_id: str, request: Any = None) -> IntegrationDescriptor: ...
      async def disconnect(self, user_id: str, provider_id: str, request: Any = None) -> DisconnectResponse:
          """PBAC integration:disconnect; manager.revoke(…); delete_users_integration."""             # verified: service.py:406
      async def persist_credential(self, user_id: str, provider_id: str, token_set: Any, *, channel: str,
                                   canonical_identity: Optional[str] = None) -> UsersIntegrationRow: ...  # verified: service.py:440
      # REMOVED: confirm_enable (service.py:346), _IDENTITY_OWNED_PROVIDERS (service.py:53) — status is durable-owner for all

  # packages/ai-parrot/src/parrot/auth/oauth2/persistence.py  (modifies)
  async def list_users_integrations(user_id: str) -> List[UsersIntegrationRow]: ...   # new
  # REMOVED: upsert_user_agent_toolkit (:113), list_user_agent_toolkits (:148), delete_user_agent_toolkits_by_provider (:171), USER_AGENT_TOOLKITS_COLLECTION (:34)

  # packages/ai-parrot-server/src/parrot/handlers/connections.py  (new)
  class ConnectionsHandler(BaseView):                                         # BaseView pattern verified: handlers/integrations.py:34
      async def get(self) -> web.Response: ...          # GET /api/v1/connections | GET /api/v1/connections/{provider}
      async def post(self) -> web.Response: ...         # POST /api/v1/connections/{provider}/start  {return_origin?, scopes?}
      async def delete(self) -> web.Response: ...       # DELETE /api/v1/connections/{provider}
      # principal from request['user_id'] / session — never the body (pattern: integrations.py:43-62)

  # packages/ai-parrot-server/src/parrot/handlers/integrations.py  (modifies)
  #   _post_enable → returns svc.status(...) unchanged (compatibility no-op, S5)                       # verified: integrations.py:163-178
  # packages/ai-parrot-server/src/parrot/handlers/user_objects.py  (modifies configure_tool_manager, user_objects.py:99)
  #   rows = await list_users_integrations(user_id)  (was list_user_agent_toolkits(user_id, agent_id), :218)
  # packages/ai-parrot-server/src/parrot/manager/manager.py  (modifies route registration, manager.py:2459-2472)
  #   + 4 ConnectionsHandler routes
  ```

### Module 7: Jira on the generic engine
- **Path**: `packages/ai-parrot/src/parrot/auth/jira_oauth.py`, `packages/ai-parrot/src/parrot/auth/routes.py`, `packages/ai-parrot/src/parrot/auth/oauth2/jira_provider.py`, `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (modify)
- **Responsibility**: `JiraOAuthManager(StandardOAuth2Manager)` with `JiraTokenSet(AbstractOAuth2TokenSet)` and the
  `atlassian_accessible_resources` post-exchange hook (TASK-4418 helpers `exchange_code`, `refresh_access_token`,
  `fetch_accessible_resources`, `fetch_myself`, jira_oauth.py:133-214); public API preserved
  (`create_authorization_url`, `handle_callback`, `get_valid_token`, `validate_token`, `is_connected`, `revoke`);
  legacy `jira:oauth:{channel}:{user_id}` read-rewrite-delete for bound principals; `/api/auth/jira/callback`
  becomes an alias of the generic callback (IdP redirect URI unchanged); the channel dispatch and lazy
  integrations imports in `routes.py` are deleted; `JiraToolkit` declares `credential_provider = "jira"` and keys
  its client cache by principal.
- **Depends on**: M2, M3, M4, M8 (notifier adapters must be registered before the Jira route switch).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/jira_oauth.py  (modifies)
  class JiraTokenSet(AbstractOAuth2TokenSet):                                 # verified: jira_oauth.py:66 (was BaseModel)
      cloud_id: str = ""
      site_url: str = ""
      available_sites: List[Dict[str, Any]] = []

  JIRA_DESCRIPTOR = OAuth2ProviderDescriptor(provider_id="jira", authorization_url=AUTHORIZATION_URL, token_url=TOKEN_URL,
                                             pkce="none", client_type="confidential",
                                             refresh_policy=RefreshPolicy(rotating=True, sliding=True, refresh_lifetime_s=90 * 86400),  # R6: Atlassian docs
                                             extra_authorize_params={"audience": "api.atlassian.com", "prompt": "consent"},
                                             post_exchange="atlassian_accessible_resources", ...)   # values verified: jira_oauth.py:102-131 build_authorization_url

  class JiraOAuthManager(StandardOAuth2Manager):                              # verified: jira_oauth.py:262 (was a plain class)
      provider_id: ClassVar[str] = "jira"
      token_set_cls = JiraTokenSet
      def __init__(self, client_id: str, client_secret: str, redirect_uri: str, *, app=None, redis_url=None,
                   redis_client=None, scopes=None, http_session=None,
                   credential_store: Optional[CredentialStore] = None,          # REPLACES credential_sink (jira_oauth.py:285)
                   event_publisher: Optional[ConnectionEventPublisher] = None,
                   callback_path: str = "/api/auth/jira/callback") -> None: ...  # alias path keeps the registered IdP redirect URI
      async def validate_token(self, channel: str, user_id: str) -> Optional[JiraTokenSet]: ...   # verified: jira_oauth.py:621 (kept)
      async def _read_legacy_token(self, channel: str, channel_user_id: str, user_id: str) -> Optional[JiraTokenSet]:
          """Also reads jira:oauth:{channel}:{channel_user_id} (jira_oauth.py:44) during the window."""
  # REMOVED: CredentialSink Protocol (jira_oauth.py:231-259) → CredentialStore in oauth2_base; _token_key/_write_token/_read_token (:396/:416/:428)

  # packages/ai-parrot/src/parrot/auth/routes.py  (modifies)
  def setup_jira_oauth_routes(app: web.Application) -> None:                  # verified: routes.py:333
      """setup_oauth2_routes(app, "jira", "/api/auth/jira/callback") (oauth2_routes.py:283); no channel dispatch here."""
  # REMOVED: jira_oauth_callback (routes.py:232-331), _handle_oauth_error, _handle_web_callback, _notify_telegram, lazy integrations imports

  # packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py  (modifies)
  class JiraToolkit(AbstractToolkit):
      credential_provider = "jira"                                            # new class attr (AbstractToolkit.credential_provider verified: toolkit.py:331)
      # _client_cache keyed by principal.user_id (was "{channel}:{user_id}", jiratoolkit.py:1060); _pre_execute (jiratoolkit.py:1316) resolves the principal via OAuthCredentialResolver
  ```

### Module 8: Server and integrations adapters
- **Path**: `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py` (modify → `IdentityVaultCredentialStore`), `packages/ai-parrot-server/src/parrot/services/identity_principal.py` (new), `packages/ai-parrot-server/src/parrot/manager/manager.py` (modify `_register_oauth2_providers`), `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` (modify), `packages/ai-parrot-integrations/src/parrot/integrations/{telegram/jira_commands.py, slack/oauth_callback.py, msteams/oauth_callback.py}` (extend), `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py` (new)
- **Responsibility**: durable store over navigator-auth `IdentityStore` for any provider, with transactional account replacement/deletion and metadata-preserving re-sealing; principal resolver over
  `auth.user_identities`; `ChannelNotifier` adapters wrapping `TelegramOAuthNotifier`, `SlackOAuthNotifier`,
  `MSTeamsOAuthNotifier` (plus the Telegram session stamper and the Slack/Teams identity writes that
  `jira_oauth_callback` used to perform); wiring at both `JiraOAuthManager(` construction sites and in
  `BotManager`; Telegram `/connect_jira` passes the session principal or replies "please /login first" (U3).
- **Depends on**: M1, M2, M4, M7.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py  (modifies)
  class IdentityVaultCredentialStore:                                         # replaces IdentityVaultCredentialSink (identity_credential_sink.py:24)
      def __init__(self, db_pool: Any) -> None: ...
      async def load(self, user_id: str, provider: str) -> Optional[Dict[str, Any]]:
          """IdentityStore.get_by_provider(user_id, provider) → decrypt_credential → token payload dict (cold-start hydration only)."""
      async def save(self, user_id: str, provider: str, payload: Dict[str, Any], *, minted: bool,
                     principal: Optional[Principal], state_payload: Optional[Dict[str, Any]]) -> None:
          """minted → atomic provider-account replacement; refresh → update_tokens on the selected current identity.
          Raises on failure (callback fails closed, S2). See transaction contract below."""                       # IdentityStore API verified: navigator_auth 0.28.7 store.py (see §6)
      async def delete(self, user_id: str, provider: str) -> None:
          """Atomically delete ALL credential identities for this principal/provider, including superseded accounts."""

  # packages/ai-parrot-server/src/parrot/services/identity_principal.py  (new)
  class IdentityPrincipalResolver:
      """channel == web → Principal(user_id=channel_user_id); else IdentityStore.find_user_by_provider_account(channel, channel_user_id);
      canonical_identity from the identity row e-mail / provider_user_id (msteams oid)."""
      def __init__(self, db_pool: Any) -> None: ...
      async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]: ...

  # packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py  (new)
  class TelegramJiraNotifierAdapter:   channel = "telegram"   # wraps TelegramOAuthNotifier (telegram/jira_commands.py:192) + telegram_jira_session_stamper (telegram/wrapper.py:473)
  class SlackJiraNotifierAdapter:      channel = "slack"      # wraps handle_slack_jira_callback's DM + identity write (slack/oauth_callback.py)
  class MSTeamsJiraNotifierAdapter:    channel = "msteams"    # wraps MSTeamsOAuthNotifier (msteams/oauth_callback.py:89) + nav_user_id-guarded identity write (:182)

  # packages/ai-parrot-integrations/src/parrot/integrations/manager.py  (modifies)
  def _build_credential_store(app: Any) -> Optional[CredentialStore]: ...     # replaces _build_jira_credential_sink (manager.py:81-107)
  def _build_principal_resolver(app: Any) -> PrincipalResolver: ...
  def _register_channel_notifiers(app: Any) -> None: ...
  #   JiraOAuthManager(..., credential_store=_build_credential_store(app), event_publisher=...)   # verified sites: manager.py:367-373, 926-932

  # packages/ai-parrot-server/src/parrot/manager/manager.py  (modifies)
  async def _register_oauth2_providers(self, app: web.Application) -> None:  # verified: manager.py:2789
      """Register JiraOAuth2Provider when app['jira_oauth_manager'] exists (as today) AND every descriptor from
      OAUTH2_PROVIDERS_FILE via register_descriptor_providers(...); set_principal_resolver(IdentityPrincipalResolver(app['authdb']))."""
  ```

**M8 transaction contract (AC-12).** `IdentityStore.save_linked_identity` upserts by
`(user_id, provider, provider_user_id)`, not `(user_id, provider)`; `get_by_provider` selects the newest enabled row.
Neither provides single-account replacement. Under the M2 principal lock, minted saves must atomically persist
and select the new account and remove superseded credential rows for the same principal/provider. Rollback
keeps the previous grant usable if the new write fails. Disconnect deletes every such credential row, invalidates
the principal cache and prevents legacy fallback from restoring it during the migration window. Channel identity
rows for other providers are untouched. Refresh updates only the still-selected account after re-reading it.

The server adapter owns the transaction using the existing async DB pool and navigator-auth cipher; do not
compose separately committed `IdentityStore` calls and claim atomicity. Before task decomposition, verify the
transaction/sealing APIs against the upgraded navigator-auth version. If its public APIs cannot share a transaction,
explicitly scope a server-side transaction helper in `identity_credential_sink.py` using verified DB/model APIs;
do not invent an upstream method or add an unapproved dependency. Real-DB acceptance tests must cover rollback,
concurrent reconnect/refresh/disconnect, and cold-cache loads after replacing A with B and after disconnect.

### Module 9: MCP per-call principal
- **Path**: `packages/ai-parrot/src/parrot/mcp/client.py`, `packages/ai-parrot/src/parrot/mcp/integration.py`, `packages/ai-parrot/src/parrot/bots/agent.py`, `packages/ai-parrot-server/src/parrot/mcp/transports/http.py` (modify)
- **Responsibility**: `user_id` becomes optional on `add_oauth_mcp_server`, `add_netsuite_mcp_server`,
  `create_oauth_mcp_server` and `MCPClientConfig`; when absent the config sets `inject_broker_credential=True` so
  per-call `header_provider(ReadonlyContext)` + `_CREDENTIAL_VAR` resolution supplies the bearer (S9).
  Generated `MCPToolProxy` instances must declare the configured `credential_provider` so `AbstractTool.execute`
  actually invokes the broker; reject a delegated configuration without a provider mapping.
  Forward immutable per-call headers through `MCPClient.call_tool` → `HttpMCPSession.call_tool` → `_send_request`,
  including retries. Today `integration.py:442` drops `headers` and the HTTP transport has no per-call parameter;
  the existing config flag alone is insufficient. In delegated mode a missing broker credential fails closed
  before network I/O; it never falls back to a connection-level token. The request bearer takes precedence over
  connection-level OAuth/token_supplier only for that request; never mutate shared headers/config/session defaults.
  Partition initialized MCP sessions and their `Mcp-Session-Id` by principal so a server-side authenticated session
  cannot be reused by another principal. Do not repurpose the M2M `user_id` as delegated add-time identity.
  `MCPClientConfig.user_id` is documented as M2M-only (`NetSuiteM2MAuth(user_id="m2m")`); existing M2M flows remain supported.
  Delegated mode on transports without request-local authentication must fail explicitly rather than silently
  discard credentials. HTTP-level integration tests, not only config/ContextVar assertions, gate this module.
- **Depends on**: none new (FEAT-264 M9 path).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/mcp/integration.py  (modifies)
  def create_oauth_mcp_server(*, name: str, url: str, user_id: Optional[str] = None, oauth2: Optional[MCPOAuth2Config] = None,
                              ..., **kwargs) -> MCPServerConfig:               # verified: integration.py:727-740 (user_id: str today)
      """user_id None → config.inject_broker_credential = True (client.py:242)."""
  async def add_oauth_mcp_server(self, name: str, url: str, user_id: Optional[str] = None, oauth2=None, ...) -> List[str]: ...  # verified: integration.py:1394
  async def add_netsuite_mcp_server(self, account_id: str, client_id: str, user_id: Optional[str] = None, **kwargs) -> List[str]: ...  # verified: integration.py:1706
  # packages/ai-parrot-server/src/parrot/mcp/transports/http.py (modifies)
  #   HttpMCPSession.call_tool(..., *, headers: Optional[Dict[str, str]] = None)
  #   HttpMCPSession._send_request(..., *, headers: Optional[Dict[str, str]] = None)
  #   MCPClient.call_tool forwards headers to the selected principal's session on every retry.
  # packages/ai-parrot/src/parrot/mcp/client.py  (modifies)
  #   user_id: Optional[str] = field(default=None)  # verified: client.py:236 — docstring: M2M only; per-user tokens flow via inject_broker_credential (client.py:242)
  ```

### Module 10: Docs, legacy-key audit and Identity Vault re-encryption
- **Path**: `docs/auth/connections.md` (new), `docs/auth/jira-credential-ownership.md` (modify), `packages/ai-parrot/src/parrot/auth/oauth2/legacy_audit.py` (new), `packages/ai-parrot/src/parrot/auth/oauth2/reencrypt.py` (new)
- **Responsibility**: provider onboarding (descriptor + secrets), channel adapter guide (`ChannelNotifier`,
  `PrincipalResolver`), key layout and migration window (cutover = deploy + 30 days, §8); update the ownership doc ("Identity Vault owns every 3LO
  provider"); `python -m parrot.auth.oauth2.legacy_audit` prints, per provider and channel, the count of legacy
  keys with and without a resolvable principal (the U3 cutover metric) — read-only.
  **Re-encryption job** (§8, key rotation): `python -m parrot.auth.oauth2.reencrypt [--apply] [--provider P ...]`
  scans every credential-bearing `auth.user_identities` row in the selected provider scope, including disabled rows
  and hand-written providers such as O365. Never filter by row `key_version`: `update_tokens` stamps the active
  version while leaving `id_token` (and any omitted refresh token) encrypted under an older key.
  Per row: take the M2 principal lock → re-read the row → decrypt all present token columns with the full ring →
  re-seal all present token columns under the active key in one write. Preserve identity id, account binding,
  enabled status, profile/auth_data, scopes and token expiry; do not use `save_linked_identity` blindly because it
  enables rows and rewrites profile fields. M8 owns a transaction helper in `identity_credential_sink.py` for this
  metadata-preserving write, using verified navigator-auth cipher/DB APIs; M10 calls it via an injected adapter.
  Core must not import the server package. The CLI bootstraps that adapter only in the server runtime.

  Dry-run performs no writes. Classify a row as `current` only if every present token decrypts using the active
  key alone; decrypt with the full ring to distinguish `stale` (old-key material) from `failed` (undecryptable).
  An apply run may safely re-seal all readable rows, including rows whose row-level version already looks current.
  Undecryptable rows remain untouched and count as `failed`; never log token values. Key retirement requires a
  full-store verification with the active key alone, `stale == 0` AND `failed == 0`, covering all providers sharing
  the retiring key. A provider-filtered run cannot authorize global key retirement. Document: add the new key →
  activate it on every writer → run `--apply` → verify all token columns with only the active key → remove the old
  key only after that gate passes. Key generation, storage and cipher ownership stay in navigator-auth/session.
- **Depends on**: M2, M7, M8 (`IdentityVaultCredentialStore` path and the principal lock).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/oauth2/legacy_audit.py  (new)
  async def audit_legacy_keys(redis: Any, resolver: PrincipalResolver, *, providers: Sequence[str]) -> Dict[str, Dict[str, int]]:
      """{provider: {channel: {"bound": n, "unbound": m}}} over oauth2:{p}:{c}:{u} and jira:oauth:{c}:{u}; never prints token values."""
  def main(argv: Optional[Sequence[str]] = None) -> int: ...

  # packages/ai-parrot/src/parrot/auth/oauth2/reencrypt.py  (new)
  async def reencrypt_identities(store: "IdentityStore", db_pool: Any,
                                 lock: Callable[[str, str], AsyncContextManager[Any]], *,
                                 reseal_row: Callable[[Any, Any], Awaitable[None]],
                                 verify_active: Callable[[Any], bool],
                                 providers: Sequence[str], active_key_id: int,
                                 apply: bool = False) -> Dict[str, Dict[str, int]]:
      """reseal_row(row, decrypted_token) preserves metadata; verify_active(row) checks all ciphertext with only the active key.
      Return {provider: {"current": n, "stale": m, "resealed": k, "failed": f}}; dry-run unless apply; no token output."""
  def main(argv: Optional[Sequence[str]] = None) -> int: ...
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_principal_resolver_default_web_only` | M1 | default resolver binds web ids, returns `None` for telegram/slack/msteams |
| `test_resolve_principal_fail_closed` | M1 | `None` propagates; no channel-keyed fallback |
| `test_manager_keys_are_principal_scoped` | M2 | token/lock keys contain no channel; same principal from two channels hits one key |
| `test_state_binds_principal_and_callback_verifies` | M2 | nonce payload carries `nav_user_id/channel/channel_user_id`; callback without binding fails closed (S1) |
| `test_persist_durable_first_then_redis` | M2 | store failure → `CredentialPersistenceError`, no Redis write, callback error page (S2) |
| `test_legacy_key_read_rewrite_delete` | M2 | legacy `oauth2:{p}:{c}:{u}` read once, rewritten under principal, deleted; no read after `OAUTH2_LEGACY_KEYS_UNTIL` |
| `test_o365_refresh_error_classification` | M2 | invalid_grant revokes/emits; network/429/5xx are transient; invalid_client, other 400/401 and malformed responses preserve grant and expose operational errors without secrets |
| `test_refresh_invalid_grant_revokes_and_emits` | M2 | `InvalidGrantError` → revoke + `connection.refresh_failed` |
| `test_refresh_transient_keeps_grant` | M2 | `RefreshTransientError` → grant kept, no event (S7) |
| `test_concurrent_refresh_single_flight` | M2 | two refreshers, one token endpoint call, rotated refresh token persisted once |
| `test_revoke_calls_remote_then_local_then_event` | M2 | `_revoke_remote` best effort; local delete; `connection.revoked` |
| `test_descriptor_validation_and_secrets_from_conf` | M3 | invalid descriptor names the provider; client id/secret never read from the descriptor |
| `test_standard_manager_exchange_refresh_probe` | M3 | RFC 6749 exchange/refresh, PKCE per descriptor, JSON-path probe |
| `test_post_exchange_hook_registry_is_typed` | M3 | unknown name → `KeyError`; no import-by-path |
| `test_event_publisher_order_and_isolation` | M4 | notifier → audit → bus; notifier exception logged, callback succeeds (S6) |
| `test_setup_connection_fanout_requires_publish_only_streams` | M4 | mirrors `fanout.py:74` rule |
| `test_auth_required_payload_superset` | M5 | both exceptions → identical `ToolResult` metadata; device-code fields preserved (S8) |
| `test_toolmanager_catches_credential_required` | M5 | `CredentialRequired` → `status="authorization_required"` |
| `test_oauth_resolver_resolves_principal_first` | M5 | telegram id → principal → `get_valid_token(principal)` |
| `test_service_pbac_on_connect_and_disconnect` | M6 | missing PDP or denial → no OAuth state / no deletion (S4) |
| `test_service_list_for_principal_cross_channel` | M6 | connection made as `channel=telegram` is listed for the same principal on web |
| `test_descriptor_updated_at_bumps_on_reconnect` | M6 | `updated_at` changes on first connect, replace-on-reconnect and status change; `connected_at` keeps the first-connect time |
| `test_confirm_enable_removed_enable_route_noop` | M6 | `/enable` returns the descriptor without writing rows (S5) |
| `test_hydration_from_connections` | M6 | `configure_tool_manager` registers toolkits for every connected provider |
| `test_connections_handler_principal_from_session` | M6 | body `user_id` ignored; 401 without session |
| `test_jira_manager_is_standard_subclass_public_api` | M7 | `create_authorization_url/handle_callback/get_valid_token/validate_token/revoke` signatures unchanged |
| `test_jira_legacy_key_dual_read_bound_only` | M7 | bound telegram user: `jira:oauth:telegram:<id>` read + rewritten; unbound: `None` |
| `test_jira_callback_alias_path` | M7 | `/api/auth/jira/callback` served by the generic handler; `jira_oauth_callback` gone |
| `test_jiratoolkit_cache_keyed_by_principal` | M7 | two channels, one principal → one client; token change → new client |
| `test_identity_vault_store_roundtrip_any_provider` | M8 | `save(minted)` commits atomic replacement; refresh durably updates the selected row; `load` decrypts; o365 payload accepted; rollback preserves prior grant |
| `test_identity_principal_resolver` | M8 | `find_user_by_provider_account(channel, id)` mapping; web passthrough |
| `test_notifier_adapters_delegate` | M8 | Telegram/Slack/Teams adapters call the wrapped notifier with the former arguments |
| `test_telegram_connect_jira_requires_principal` | M8 | no `nav_user_id` on session → "/login first" reply, no OAuth state |
| `test_register_oauth2_providers_from_descriptors` | M8 | BotManager registers descriptor providers and the principal resolver |
| `test_mcp_user_id_optional_injects_broker` | M9 | `user_id=None` → `inject_broker_credential=True`; per-call bearer from `_CREDENTIAL_VAR` |
| `test_legacy_audit_counts` | M10 | bound/unbound counts per provider/channel; no token values in output |
| `test_reencrypt_dry_run_counts_only` | M10 | inspect every token column using active-key-only decryption, regardless of row `key_version`; no writes without `--apply` |
| `test_reencrypt_reseals_all_columns` | M10 | with two keys in the ring and v2 active, `--apply` leaves access/refresh/**id_token** decryptable after v1 is removed from the ring; `auth_data` preserved |
| `test_reencrypt_undecryptable_row_counted_failed` | M10 | `IdentityCredentialError` row → `failed`, untouched; job continues; no token value in output |
| `test_reencrypt_mixed_key_row` | M10 | refresh after activating v2 stamps row v2 but leaves v1 id_token; scan detects it, apply re-seals it, active-key-only decrypt succeeds |
| `test_reencrypt_preserves_disabled_metadata` | M8/M10 | disabled rows stay disabled; identity id, profile/auth_data, scopes and expiry unchanged |
| `test_reencrypt_retirement_gate` | M10 | undecryptable row or a provider-filtered scan blocks global retirement; hand-written providers included |
| `test_reencrypt_takes_principal_lock` | M10 | a refresh holding the principal lock is not overwritten (job waits for the lock, re-reads the row) |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_web_connect_principal_keyed` | web start → callback → Identity Vault write → Redis → `list_for_principal` shows connected (replaces `tests/integration/oauth2/test_e2e_web_connect.py` expectations) |
| `test_e2e_telegram_jira_parity` | bound Telegram user: `/connect_jira` → alias callback → Telegram notifier adapter called → tool call resolves (updates `test_e2e_telegram_regression.py`) |
| `test_cross_channel_reuse` | connect on telegram, resolve on web and A2A for the same principal |
| `test_isolation_between_principals` | principal A cannot read principal B's token from any channel |
| `test_authorization_required_roundtrip_both_signals` | toolkit `_pre_execute` and broker seam both yield `authorization_required` with the same metadata through AgentTalk |
| `test_callback_fails_without_durable_write` | Identity Vault unavailable → error page, no Redis key, no event |

### Added integration gates (required, owned by the corresponding module)

- M8: real-DB replace A with B, clear Redis, verify only B loads; disconnect then clear Redis and verify neither
  account nor legacy keys restore credentials. Force failure inside replacement and prove A survives rollback.
  Interleave replacement, refresh and disconnect to prove stale writes cannot resurrect A.
- M9: a local aiohttp MCP endpoint records actual Authorization headers and session ids for two concurrent
  principals, including retries; assert correct broker bearer, distinct sessions, no shared-state mutation,
  no request on missing credentials, and unchanged M2M authentication.
- M10: refresh under the new key before migration; verify every token with an active-key-only ring afterward.

Task decomposition must assign these new tests to package-local test files, add those exact paths to each
module's Validation Contract, and include them in the feature gate. Existing tests below are regression coverage,
not substitutes for these new integration gates. No implementation completion can rely solely on mocked config tests.

### Validation Contract

runners:
- kind: pytest
  tests:
  - tests/auth/test_oauth2_base.py
  - packages/ai-parrot/tests/unit/test_jira_oauth_manager.py
  - packages/ai-parrot/tests/unit/test_oauth_callback_routes.py
  - packages/ai-parrot/tests/unit/test_oauth2_service_token_status.py
  - packages/ai-parrot/tests/unit/test_auth_required.py
  - packages/ai-parrot/tests/unit/test_tool_credential_seam.py
  - packages/ai-parrot/tests/unit/test_credential_broker.py
  - packages/ai-parrot/tests/auth/test_integrations_status.py
  - packages/ai-parrot/tests/unit/test_post_auth_jira.py
  - packages/ai-parrot/tests/unit/observability/test_event_fanout.py
  - packages/ai-parrot-server/tests/unit/test_identity_credential_sink.py
  - packages/ai-parrot-server/tests/unit/test_a2a_resume_trigger.py
  - packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py
  - tests/unit/integrations/oauth2/test_service.py
  - tests/unit/integrations/oauth2/test_registry.py
  - tests/unit/integrations/oauth2/test_jira_provider.py
  - tests/unit/integrations/oauth2/test_callback_web.py
  - tests/unit/integrations/oauth2/test_handler.py
  - tests/unit/integrations/oauth2/test_agenttalk_envelope.py
  - tests/auth/test_mcp_oauth2_callback.py
  - tests/integration/oauth2/test_e2e_web_connect.py
  - tests/integration/oauth2/test_e2e_telegram_regression.py
  - tests/integration/oauth2/test_e2e_auth_envelope.py
  - packages/ai-parrot/tests/unit/auth/test_principal.py
  - packages/ai-parrot/tests/unit/auth/test_connection_events.py
  - packages/ai-parrot/tests/unit/auth/test_oauth2_descriptor.py
  - packages/ai-parrot/tests/unit/auth/test_oauth2_principal_keys.py
  - packages/ai-parrot/tests/unit/auth/test_oauth2_refresh_legacy.py
  - packages/ai-parrot/tests/unit/auth/test_o365_refresh_errors.py
  - packages/ai-parrot/tests/unit/auth/test_standard_oauth2_manager.py
  - packages/ai-parrot/tests/unit/auth/test_auth_required_payload.py
  - packages/ai-parrot/tests/unit/auth/test_users_integrations_model.py
  - packages/ai-parrot-server/tests/unit/test_connections_handler.py
  - packages/ai-parrot-server/tests/unit/test_user_objects_hydration.py
  - packages/ai-parrot/tests/unit/auth/test_no_user_agent_toolkits.py
  - packages/ai-parrot-server/tests/integration/test_identity_vault_store_db.py
  - packages/ai-parrot-server/tests/unit/test_identity_reseal.py
  - packages/ai-parrot-server/tests/unit/test_identity_principal_resolver.py
  - packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py
  - packages/ai-parrot-integrations/tests/test_telegram_jira_principal.py
  - packages/ai-parrot-integrations/tests/test_slack_msteams_jira_principal.py
  - packages/ai-parrot-server/tests/unit/test_register_oauth2_providers.py
  - packages/ai-parrot-server/tests/unit/test_http_mcp_session_headers.py
  - packages/ai-parrot/tests/mcp/test_mcp_delegated_principal.py
  - packages/ai-parrot-server/tests/integration/test_mcp_delegated_http.py
  - packages/ai-parrot/tests/unit/auth/test_legacy_audit.py
  - packages/ai-parrot/tests/unit/auth/test_reencrypt.py
  - tests/integration/oauth2/test_connections_isolation_matrix.py
  markers: none

### Test Data / Fixtures
```python
@pytest.fixture
def principal() -> Principal:
    return Principal(user_id="1042", canonical_identity="jlara@example.com", channel="telegram", channel_user_id="88123")

@pytest.fixture
def fake_credential_store():  # in-memory CredentialStore; `fail_next_save` flag for the durable-first tests
    ...

@pytest.fixture
def fake_principal_resolver():  # {(channel, channel_user_id): Principal}; unknown → None
    ...

@pytest.fixture
def notifier_registry():  # ChannelNotifierRegistry._reset(); records (event, state_payload); `raise_on_notify` flag
    ...

@pytest.fixture
def fake_redis():  # reuse the fakeredis double from tests/auth/test_oauth2_base.py
    ...

@pytest.fixture
def jira_descriptor() -> OAuth2ProviderDescriptor:
    return JIRA_DESCRIPTOR
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC-1 (G1)** No Redis key, lock key or durable-store name produced by `AbstractOAuth2Manager` or `JiraOAuthManager` contains the channel; `grep -rn ':{channel}:' packages/ai-parrot/src/parrot/auth/` matches only the `_LEGACY_*` templates.
- [ ] **AC-2 (G1, S1)** Every OAuth state payload carries `nav_user_id`, `channel`, `channel_user_id` (and `canonical_identity` when known); a callback whose state lacks `nav_user_id` renders the error page and writes nothing.
- [ ] **AC-3 (G2)** A connection created with `channel="telegram"` is returned by `list_for_principal` and resolves in `OAuthCredentialResolver.resolve("web", <nav id>)` and `resolve("a2a", <email>)` for the same principal; `user_agent_toolkits` has no remaining reader or writer in `packages/`.
- [ ] **AC-4 (G3)** `JiraOAuthManager` subclasses `StandardOAuth2Manager`; `O365OAuthManager` keeps its subclass/API but implements M2 typed refresh-error classification; a new provider is added by a descriptor + navconfig secrets with no manager subclass (test adds a dummy provider end to end).
- [ ] **AC-5 (G4, S2)** `_persist_token` writes the `CredentialStore` before Redis and raises `CredentialPersistenceError` on failure; with the Identity Vault store configured, a callback is successful only after the M8 durable replacement transaction committed; refresh likewise requires its durable token update to succeed.
- [ ] **AC-6 (G5, S8)** `ToolManager.execute_tool` converts both `AuthorizationRequired` and `CredentialRequired` to `ToolResult(status="authorization_required", metadata=AuthRequiredPayload)`; AgentTalk returns `AuthRequiredEnvelope` for both; device-code fields survive.
- [ ] **AC-7 (G6, U5)** `connection.completed`, `connection.revoked`, `connection.refresh_failed` are published through `ConnectionEventPublisher`: notifier awaited, audit entry appended, bus publish when attached; a raising notifier never fails the callback; `parrot/auth/routes.py` imports nothing from `parrot.integrations`.
- [ ] **AC-8 (G7, S4)** `/api/v1/connections` GET/POST/DELETE exist; principal from the session only; `integration:connect` and `integration:disconnect` are evaluated with the requested scopes and fail closed without a PDP.
- [ ] **AC-9 (G8, U3)** Telegram, Slack and Teams Jira completion notifications and identity writes behave as before through the adapters; a Telegram user with a `telegram` identity row keeps the connection without re-authorizing; a Telegram user without `nav_user_id` on the session receives the "/login first" reply and no OAuth state is created.
- [ ] **AC-10 (S7)** Both standard and O365 managers classify `invalid_grant` as `InvalidGrantError` (revoke + `refresh_failed`); network/429/5xx become `RefreshTransientError` (keep grant, no event); other OAuth/protocol failures preserve the grant and surface operational errors without token material.
- [ ] **AC-11 (G9, S9)** `add_oauth_mcp_server` / `add_netsuite_mcp_server` / `create_oauth_mcp_server` accept `user_id=None`; the resulting config has `inject_broker_credential=True` and generated proxies invoke the broker. Actual HTTP requests carry the correct per-call bearer through retries, concurrent principals have isolated headers and MCP sessions, missing credentials fail closed, and M2M behavior is preserved.
- [ ] **AC-12 (S3)** v1 stores one account per provider per principal; a reconnect atomically replaces it with rollback on failure; disconnect removes all provider-account credentials without cold-cache or legacy resurrection; concurrent refresh cannot restore the prior account; `account_id` is present on `UsersIntegrationRow`, `IntegrationDescriptor` and every `ConnectionEvent`.
- [ ] **AC-13** Legacy keys (`oauth2:{p}:{c}:{u}`, vault `oauth2_{p}_{c}_{u}`, `jira:oauth:{c}:{u}`) are read at most once per principal, rewritten and deleted; no legacy read happens after `OAUTH2_LEGACY_KEYS_UNTIL`; `python -m parrot.auth.oauth2.legacy_audit` reports bound/unbound counts without token values.
- [ ] **AC-14** `/api/auth/jira/callback` keeps working as the registered Atlassian redirect URI (alias of the generic callback); `jira_oauth_callback` and `CredentialSink` are deleted.
- [ ] **AC-15** `docs/auth/connections.md` exists; `docs/auth/jira-credential-ownership.md` states the Identity Vault owns every 3LO provider.
- [ ] **AC-16** The Validation Contract passes; no `print`, no `requests`/`httpx`, Pydantic v2 only; `ruff check` clean on touched files.
- [ ] **AC-17 (S11)** The isolation matrix passes: cross-principal read denied, unlinked-user rejection, legacy deletion, concurrent refresh single-flight, notifier-failure isolation, durable-write-required callback, `CredentialRequired` serialization.
- [ ] **AC-18 (§8 key rotation)** `python -m parrot.auth.oauth2.reencrypt` is dry-run by default; with `--apply` every readable credential row in scope is eligible for re-sealing regardless of row `key_version`, preserving metadata and enabled status; all present token columns are re-sealed (access, refresh **and** id token) under the active key while holding the principal refresh lock, and key retirement requires full-store active-key-only verification across all providers with both `stale == 0` and `failed == 0`; undecryptable rows are reported as `failed`, never modified; no token value is logged or printed.
- [ ] **AC-19 (§8 S-4 pre-check)** `UsersIntegrationRow` and `IntegrationDescriptor` carry `updated_at`, bumped on every save, replace-on-reconnect and status change; `GET /api/v1/connections` returns `provider`, `status` and `updated_at`; `CredentialStore` and `Principal` live in `packages/ai-parrot` with no import from `ai-parrot-server`.
- [ ] **AC-20 (§8 R6)** Every `refresh_token` present in a token response replaces the stored one, whatever `RefreshPolicy.rotating` says; `JIRA_DESCRIPTOR.refresh_policy == RefreshPolicy(rotating=True, sliding=True, refresh_lifetime_s=7776000)`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified 2026-10-30 against `dev` @ `65aa79dfe` (`packages/*/src`) and
> the 76 research findings in `sdd/state/FEAT-773/findings/` (282 citations probed, 0 missing). Implementation
> agents MUST NOT reference imports / attributes / methods not listed here without re-verifying.

### Verified Imports
```python
from parrot.auth.oauth2_base import AbstractOAuth2Manager, AbstractOAuth2TokenSet           # verified: oauth2_base.py:89, :61
from parrot.auth.oauth2_base import VaultWriter, VaultReader, VaultDeleter                   # verified: oauth2_base.py:56-58 (to be replaced by CredentialStore)
from parrot.auth.oauth2.registry import OAuth2Provider, OAuth2ProviderRegistry, register_oauth2_provider  # verified: registry.py:20, :69, :126
from parrot.auth.oauth2.service import IntegrationsService                                   # verified: service.py:74
from parrot.auth.oauth2.models import (IntegrationDescriptor, ConnectInitRequest, ConnectInitResponse, EnableResponse,
                                       DisconnectResponse, AuthRequiredEnvelope, UsersIntegrationRow, UserAgentToolkitRow)  # verified: models.py:21,67,79,95,105,117,147,183
from parrot.auth.oauth2.persistence import (upsert_users_integration, get_users_integration, delete_users_integration,
                                            upsert_user_agent_toolkit, list_user_agent_toolkits, delete_user_agent_toolkits_by_provider)  # verified: persistence.py:42,67,89,113,148,171
from parrot.auth.oauth2 import _WEB_CHANNEL                                                  # verified: service.py:26 imports it from oauth2/__init__.py
from parrot.auth.oauth2.jira_provider import JiraOAuth2Provider                              # verified: jira_provider.py:21
from parrot.auth.oauth2.mcp_provider import MCPOAuth2Provider                                # verified: mcp_provider.py:36
from parrot.auth.oauth2_routes import make_oauth2_callback, setup_oauth2_routes, register_a2a_resume_hook, handle_mcp_oauth2_callback  # verified: oauth2_routes.py:200, :283, :49, :317
from parrot.auth.routes import setup_jira_oauth_routes, jira_oauth_callback                  # verified: routes.py:333, :232
from parrot.auth.jira_oauth import (JiraOAuthManager, JiraTokenSet, CredentialSink, build_authorization_url, exchange_code,
                                    refresh_access_token, fetch_accessible_resources, fetch_myself)  # verified: jira_oauth.py:262, :66, :231, :102, :133, :163, :191, :214
from parrot.auth.o365_oauth import O365OAuthManager                                          # verified: o365_oauth.py:55
from parrot.auth.credentials import (CredentialResolver, OAuthCredentialResolver, StaticCredentialResolver, AuthKind,
                                     ProviderCredentialConfig, ResolvedCredential, NeedsAuth, CredentialRequired)  # verified: credentials.py:162,184,216,43,46,65,82,113
from parrot.auth.exceptions import AuthorizationRequired                                     # verified: exceptions.py:12
from parrot.auth.broker.core import CredentialBroker                                         # verified: broker/core.py:32
from parrot.auth.identity import CanonicalIdentityMapper, identity_mapper                    # verified: identity.py:57, :123
from parrot.auth.permission import UserSession, PermissionContext, build_principal_context   # verified: permission.py:21, :81, :166
from parrot.security.vault_utils import store_vault_credential, retrieve_vault_credential, delete_vault_credential, set_vault_credential_store, oauth2_vault_name  # verified: vault_utils.py:92, (reader/deleter in file), :46, :205
from parrot.security.audit_ledger import AuditLedger, AuditLedgerEntry                      # verified: audit_ledger.py:296, :80
from parrot.observability.fanout import setup_event_fanout, _validate_bus                    # verified: fanout.py:90, :74
from parrot.tools.manager import ToolManager                                                 # verified: manager.py (execute_tool :1787, set_broker :517)
from parrot.tools.abstract import AbstractTool, current_credential, _CREDENTIAL_VAR          # verified: abstract.py (execute :916, :45, :42)
from parrot.tools.toolkit import AbstractToolkit                                             # verified: toolkit.py (credential_provider :331, _pre_execute :491)
from parrot.mcp.client import MCPClientConfig                                                # verified: client.py:133
from parrot.mcp.integration import create_oauth_mcp_server                                   # verified: integration.py:727
from parrot.mcp.oauth2_config import MCPOAuth2Config, MCPOAuth2Preset                        # verified: oauth2_config.py:27, :98
from parrot.mcp.oauth import TokenStore, RedisTokenStore, VaultTokenStore, NetSuiteM2MAuth   # verified: mcp/oauth.py:22, :42, :63, :168
from parrot.conf import WEB_OAUTH_ALLOWED_ORIGINS, JIRA_CLIENT_ID, JIRA_CLIENT_SECRET, JIRA_REDIRECT_URI, O365_CLIENT_ID, O365_REDIRECT_URI, OAUTH2_REDIS_URL  # verified: conf.py:751, 744-746, 618, 622, 626
# ai-parrot-server
from parrot.services.identity_credential_sink import IdentityVaultCredentialSink             # verified: identity_credential_sink.py:24
from parrot.services.identity_mapping import IdentityMappingService                          # verified: identity_mapping.py:136
from parrot.services.vault_token_sync import VaultTokenSync                                  # verified: vault_token_sync.py:107
from parrot.handlers.integrations import IntegrationsHandler                                 # verified: handlers/integrations.py:34
# ai-parrot-integrations
from parrot.integrations.telegram.jira_commands import connect_jira_handler, register_jira_commands, TelegramOAuthNotifier  # verified: telegram/jira_commands.py:50, :156, :192
from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback, MSTeamsOAuthNotifier  # verified: msteams/oauth_callback.py:182, :89
from parrot.integrations.slack.oauth_callback import handle_slack_jira_callback             # verified: slack/oauth_callback.py (F067)
from parrot.integrations.telegram.post_auth_jira import JiraPostAuthProvider                 # verified: post_auth_jira.py:38
# external (navigator-auth 0.28.7, .venv)
from navigator_auth.identity.store import IdentityStore                                      # verified: site-packages/navigator_auth/identity/store.py
from navigator_auth.identity.types import TokenResponse                                      # verified: fields credential, expires_at, expires_in, id_token, provider_user_id, refresh_token, token_type; classmethods from_credential, from_oauth_response(payload, scopes)
from navigator_auth.models import UserIdentity                                               # verified: fields identity_id, user_id, auth_provider, provider_user_id, auth_data, email, display_name, scopes, access_token, refresh_token, id_token, token_type, expires_at, refreshed_at, enabled, key_version, created_at
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/auth/oauth2_base.py
_TOKEN_KEY_TEMPLATE = "oauth2:{provider}:{channel}:{user_id}"                 # :39
_NONCE_KEY_TEMPLATE = "oauth2:{provider}:nonce:{nonce}"                       # :40
_LOCK_KEY_TEMPLATE = "lock:oauth2:{provider}:refresh:{channel}:{user_id}"     # :41
_VAULT_NAME_TEMPLATE = "oauth2_{provider}_{channel}_{user_id}"                # :44
_TOKEN_TTL_SECONDS = 90 * 24 * 60 * 60; _NONCE_TTL_SECONDS = 10 * 60; _REFRESH_LOCK_TIMEOUT = 10; _REFRESH_LOCK_BLOCKING_TIMEOUT = 5  # :47-50
class AbstractOAuth2TokenSet(BaseModel):                                      # :61  access_token, refresh_token, expires_at, scopes, granted_at, last_refreshed_at, account_id, display_name, email; is_expired (:82)
class AbstractOAuth2Manager(ABC):                                             # :89
    provider_id: ClassVar[str] = ""                                           # :109
    use_pkce: ClassVar[bool] = True                                           # :116
    def __init__(self, client_id, redirect_uri, *, client_secret=None, app=None, redis_url=None, redis_client=None, scopes=None,
                 http_session=None, vault_writer=None, vault_reader=None, vault_deleter=None, callback_path=None) -> None  # :120-134
    #   :172-174 self._vault_writer/_vault_reader/_vault_deleter default to vault_utils store/retrieve/delete_vault_credential
    #   :181 callback_path or f"/api/auth/oauth2/{self.provider_id}/callback"
    def setup(self) -> None                                                   # :186  app[f"oauth2_manager_{provider_id}"] (:201); setup_oauth2_routes(app, provider_id, callback_path) (:213)
    def _token_key(self, channel, user_id) -> str                             # :251
    def _nonce_key(self, nonce) -> str                                        # :256
    def _lock_key(self, channel, user_id) -> str                              # :259
    def _vault_name(self, channel, user_id) -> str                            # :264
    @staticmethod def _new_pkce_pair() -> Tuple[str, str]                     # :289
    async def create_authorization_url(self, channel, user_id, extra_state=None) -> Tuple[str, str]  # :298  (:327 if self.use_pkce; :340 nonce ex=_NONCE_TTL_SECONDS)
    def authorization_url_extra_params(self) -> Dict[str, str]              # :345
    async def handle_callback(self, code, state) -> Tuple[AbstractOAuth2TokenSet, Dict[str, Any]]  # :354
    async def _persist_token(self, channel, user_id, token_set) -> None       # :409  vault write swallowed on failure (:415-420), then Redis (:422-426)
    async def _read_token_from_cache(self, channel, user_id)                  # :429
    async def _read_token_from_vault(self, channel, user_id)                  # :443
    async def get_valid_token(self, channel, user_id) -> Optional[AbstractOAuth2TokenSet]  # :461
    async def is_connected(self, channel, user_id) -> bool                    # :493
    async def revoke(self, channel, user_id) -> None                          # :497
    async def _refresh_tokens(self, channel, user_id, token_set)              # :507  lock (:519-523); except PermissionError → revoke (:543-545); aiohttp.ClientError → PermissionError (:546-549)
    @abstractmethod async def _exchange_code(self, code, code_verifier)       # :578
    @abstractmethod async def _refresh_request(self, refresh_token) -> Dict[str, Any]  # :594
    @abstractmethod async def _discover_identity(self, access_token) -> Dict[str, Any]  # :603
    @abstractmethod def _build_token_set(self, token_payload, identity)       # :612

# packages/ai-parrot/src/parrot/auth/jira_oauth.py
_TOKEN_KEY_PREFIX = "jira:oauth"  # jira:oauth:{channel}:{user_id}            # :44
class JiraTokenSet(BaseModel)                                                 # :66
def build_authorization_url(...)                                              # :102
async def exchange_code(...) / refresh_access_token(...) / fetch_accessible_resources(...) / fetch_myself(session, access_token, cloud_id)  # :133 / :163 / :191 / :214
class CredentialSink(Protocol):                                               # :231
    async def persist(self, channel: str, user_id: str, token: "JiraTokenSet") -> None  # :242
    async def persist_minted(self, channel, user_id, token, state_payload) -> None      # :246
class JiraOAuthManager:                                                       # :262  authorization_url/token_url/accessible_resources_url class attrs (:270-272)
    def __init__(self, client_id, client_secret, redirect_uri, *, app=None, redis_url=None, redis_client=None, scopes=None,
                 http_session=None, credential_sink: Optional[CredentialSink] = None) -> None  # :274-286
    def _token_key(channel, user_id) -> str                                   # :396  f"{_TOKEN_KEY_PREFIX}:{channel}:{user_id}"
    async def _read_token(self, key) / _write_token(self, key, token)         # :416 / :428
    async def create_authorization_url(self, channel, user_id, extra_state=None)  # :435
    async def handle_callback(self, code, state) -> Tuple[JiraTokenSet, Dict[str, Any]]  # :481  sink.persist_minted after Redis write (:540-548)
    async def get_valid_token(self, channel, user_id) -> Optional[JiraTokenSet]  # :602
    async def is_connected(self, channel, user_id) -> bool                    # :612
    async def validate_token(self, channel, user_id) -> Optional[JiraTokenSet]  # :621
    async def revoke(self, channel, user_id) -> None                          # :691
    async def _refresh_tokens(self, channel, user_id, token_set) -> JiraTokenSet  # :697  sink.persist after refresh (:776-781)

# packages/ai-parrot/src/parrot/auth/oauth2/registry.py
class OAuth2Provider(ABC):  default_scopes: ClassVar[List[str]] (:39); pbac_action_namespace = "integration" (:40); manager property (:44); toolkit_factory(credential_resolver) (:53)  # :20
class OAuth2ProviderRegistry:  register (:96) / get (:106) / all (:117)      # :69
def register_oauth2_provider(provider) -> None                                # :126

# packages/ai-parrot/src/parrot/auth/oauth2/service.py
_IDENTITY_OWNED_PROVIDERS = frozenset({"jira"})                               # :53
class IntegrationsService:                                                    # :74
    async def list_for_user(self, user_id, agent_id, request=None) -> List[IntegrationDescriptor]  # :90  PBAC "integration:list" (:115); list_user_agent_toolkits (:127); enabled_on_agent (:145)
    def _vault_sync(self, request) / def _identity_store(self, request)       # :155 / :177
    async def _identity_token_status(self, user_id, provider_id, request) -> str  # :202
    async def _token_status(self, user_id, provider_id, request) -> str       # :250  (:267 if provider_id in _IDENTITY_OWNED_PROVIDERS)
    async def start_connect(self, user_id, agent_id, provider_id, return_origin) -> ConnectInitResponse  # :291  extra_state {channel:_WEB_CHANNEL, provider_id, agent_id, return_origin} (:328-333); manager.create_authorization_url(channel=_WEB_CHANNEL, user_id, extra_state) (:334-338)
    async def confirm_enable(self, user_id, agent_id, provider_id) -> IntegrationDescriptor  # :346  upsert_user_agent_toolkit (:391)
    async def disconnect(self, user_id, provider_id) -> DisconnectResponse    # :406  delete_user_agent_toolkits_by_provider (:429)
    async def persist_credential(self, user_id, provider_id, token_set) -> UsersIntegrationRow  # :440  channel=_WEB_CHANNEL (:467)
    async def _check_pbac(self, request, action, provider_id=None) -> bool    # :490  fail-closed; ctx {"action", "provider"}; abac.is_allowed(request, ctx)

# packages/ai-parrot/src/parrot/auth/oauth2/models.py
class IntegrationDescriptor(BaseModel)  # :21 provider, display_name, icon, default_scopes, connected, status, enabled_on_agent, account_id, display_account_name, email, connected_at
class ConnectInitRequest (:67) / ConnectInitResponse(auth_url, state, scopes, expires_in=600) (:79) / EnableResponse (:95) / DisconnectResponse (:105)
class AuthRequiredEnvelope(BaseModel)  # :117 type="auth_required", provider, tool_name, auth_url, scopes, message
class UsersIntegrationRow(BaseModel)   # :147 user_id, provider, channel: str = "web" (:171), status, account_id, display_name, email, scopes, cloud_id, site_url, connected_at, last_used_at
class UserAgentToolkitRow(BaseModel)   # :183

# packages/ai-parrot/src/parrot/auth/oauth2/persistence.py
USERS_INTEGRATIONS_COLLECTION = "users_integrations" (:33); USER_AGENT_TOOLKITS_COLLECTION = "user_agent_toolkits" (:34)
async def upsert_users_integration(row) (:42) / get_users_integration(user_id, provider) (:67) / delete_users_integration(user_id, provider) (:89)
async def upsert_user_agent_toolkit(row) (:113) / list_user_agent_toolkits(user_id, agent_id) (:148) / delete_user_agent_toolkits_by_provider(user_id, provider) (:171)

# packages/ai-parrot/src/parrot/auth/oauth2_routes.py
def register_a2a_resume_hook(...)                                             # :49
async def _handle_web_callback(request, provider_id, token_set, state_payload) -> web.Response  # :123  svc.persist_credential(user_id, provider, token_set) (:173)
def make_oauth2_callback(provider_id: str)                                    # :200  handler: channel = state_payload.get("channel", "web") (:264); web → _handle_web_callback (:265-268); else _GENERIC_SUCCESS_HTML (:270-279)
def setup_oauth2_routes(app, provider_id, callback_path) -> None             # :283  exclude_list append (:302-305)
async def handle_mcp_oauth2_callback(request) -> web.Response                # :317

# packages/ai-parrot/src/parrot/auth/routes.py
async def jira_oauth_callback(request) -> web.Response                        # :232  dispatch by state channel; direct notifier calls
def setup_jira_oauth_routes(app) -> None                                      # :333  add_get("/api/auth/jira/callback", jira_oauth_callback) (:341); exclude_list (:346-349)

# packages/ai-parrot/src/parrot/auth/credentials.py
AuthKind = Literal["obo", "oauth2", "static_key", "mcp", "device_code"]        # :43
class NeedsAuth(BaseModel) (:82); class CredentialRequired(Exception) (:113) provider, auth_url, auth_kind, *, user_code, verification_uri, expires_in
class CredentialResolver(ABC): resolve(channel, user_id) (:166); get_auth_url(channel, user_id) (:175); is_connected(channel, user_id) (:179)  # :162
class OAuthCredentialResolver(CredentialResolver): __init__(oauth_manager) (:194); resolve → manager.get_valid_token (:197-198); get_auth_url → manager.create_authorization_url (:200-202)  # :184

# packages/ai-parrot/src/parrot/auth/exceptions.py
class AuthorizationRequired(Exception): __init__(tool_name, message, auth_url=None, provider="unknown", scopes=None)  # :12, :34

# packages/ai-parrot/src/parrot/auth/identity.py
class CanonicalIdentityMapper: @staticmethod to_canonical(raw_identity: Dict) -> Optional[str]  # :57, :75 ; identity_mapper singleton (:123)

# packages/ai-parrot/src/parrot/auth/permission.py
class UserSession (:21); class PermissionContext (:81) channel: Optional[str] = None (:124); def build_principal_context(principal, *, channel, tenant_id=None, roles=None) (:166)

# packages/ai-parrot/src/parrot/tools/manager.py
from ..auth.exceptions import AuthorizationRequired                           # :19
def set_broker(self, broker) -> None                                          # :517
async def execute_tool(self, tool_name, parameters, permission_context=None, *, return_tool_result=False) -> Any  # :1787
#   :2178-2183  exec_kwargs["_broker"]; _cred_channel/_cred_user_id from permission_context
#   :2273-2290  except AuthorizationRequired as auth_exc: ToolResult(success=False, status="authorization_required", result=None, error=auth_exc.message, metadata={auth_url, provider, scopes, tool_name})
def clone(self, *, include_search_tool=False) -> "ToolManager"               # :2824

# packages/ai-parrot/src/parrot/tools/abstract.py
_CREDENTIAL_VAR: ContextVar (:42); def current_credential() (:45); credential_provider: Optional[str] = None (:306)
async def execute(self, *args, **kwargs) -> ToolResult                        # :916  _broker kwarg (:950); seam (:1013-1049); re-raise AuthorizationRequired (:1186-1189) and CredentialRequired (:1194-1197)

# packages/ai-parrot/src/parrot/tools/toolkit.py
credential_provider: str | None = None (:331); _pre_execute(self, tool_name, /, **kwargs) (:491); _post_execute (:506); propagation (:717-718)

# packages/ai-parrot/src/parrot/mcp/client.py
class MCPClientConfig:  token_supplier: Optional[Callable[[], Optional[str]]] (:174); header_provider: Optional[Callable[['ReadonlyContext'], Dict[str,str]]] (:186); user_id: Optional[str] = field(default=None) (:236); inject_broker_credential: bool = False (:242); async def get_headers(self, context=None) (:244; :282 if self.inject_broker_credential)  # :133

# packages/ai-parrot/src/parrot/mcp/integration.py
def create_oauth_mcp_server(*, name, url, user_id: str, oauth2=None, client_id=None, auth_url=None, token_url=None, scopes=None, client_secret=None, headers=None, **kwargs) -> MCPServerConfig  # :727-740
async def add_mcp_server(self, config) -> List[str]                           # :1363
async def add_oauth_mcp_server(self, name, url, user_id, oauth2=None, client_id=None, auth_url=None, token_url=None, scopes=None, client_secret=None, **kwargs) -> List[str]  # :1394  (:1429-1432 create_oauth_mcp_server(..., user_id=user_id))
async def add_netsuite_mcp_server(self, account_id, client_id, user_id, **kwargs) -> List[str]  # :1706  (:1739 user_id=user_id)

# packages/ai-parrot/src/parrot/security/audit_ledger.py
class AuditLedger: async def append(self, *, user_id, channel, tool, provider, credential_material) -> AuditLedgerEntry (:338); async def verify(self, entry_id) -> bool (:407)  # :296

# packages/ai-parrot/src/parrot/observability/fanout.py
FORWARD_DENYLIST (:28); def _validate_bus(bus) (:74; transport != "streams" or publish_only is not True → RuntimeError :86-87); def setup_event_fanout(bus=None) (:90; EventBus(transport="streams", publish_only=True, outbox=…) :99-102); async def shutdown_event_fanout() (:123)

# packages/ai-parrot/src/parrot/conf.py
O365_CLIENT_ID (:618); O365_REDIRECT_URI (:622); OAUTH2_REDIS_URL (:626); JIRA_CLIENT_ID/JIRA_CLIENT_SECRET/JIRA_REDIRECT_URI (:744-746); WEB_OAUTH_ALLOWED_ORIGINS (:751-753)

# packages/ai-parrot-server/src/parrot/handlers/integrations.py
class IntegrationsHandler(BaseView): _get_user_id (:43); get (:65); post (:90); _post_connect (:109; svc.start_connect(user_id, agent_id, provider, return_origin) :152-160); _post_enable (:163; svc.confirm_enable :178); delete (:193)  # :34

# packages/ai-parrot-server/src/parrot/handlers/user_objects.py
from parrot.auth.oauth2.persistence import list_user_agent_toolkits          # :18
async def configure_tool_manager(...)                                         # :99  enablements = await list_user_agent_toolkits(user_id, agent_id) (:218); OAuthCredentialResolver(provider.manager); provider.toolkit_factory(resolver); tool_manager.register_toolkit(toolkit)

# packages/ai-parrot-server/src/parrot/handlers/agent.py
except AuthorizationRequired as exc: AuthRequiredEnvelope(provider, tool_name, auth_url, scopes, message=str(exc)); web.json_response(envelope.model_dump(), status=200)  # :1916-1927

# packages/ai-parrot-server/src/parrot/manager/manager.py
from ..handlers.integrations import IntegrationsHandler                       # :41
self.app.on_startup.append(self._register_oauth2_providers)                   # :2388
IntegrationsHandler routes                                                    # :2459-2472
async def _register_oauth2_providers(self, app) -> None                       # :2789  jira_manager = app.get("jira_oauth_manager") (:2799); register_oauth2_provider(JiraOAuth2Provider(manager=jira_manager)) (:2801)

# packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py
class IdentityVaultCredentialSink: __init__(db_pool, provider="jira") (:34); _store() → IdentityStore(db_pool) (:39); _as_token_response(token) → TokenResponse(access_token, refresh_token, expires_at, scopes, provider_user_id=token.account_id, raw={cloud_id, site_url}) (:45-63); persist_minted(channel, user_id, token, state_payload) (:64; find_user_by_provider_account :95; save_linked_identity :105); persist(channel, user_id, token) (:123; update_tokens :166)  # :24

# packages/ai-parrot-server/src/parrot/services/identity_mapping.py
class IdentityMappingService: __init__(db_pool, identity_store=None) (:156); upsert_identity(*, nav_user_id, auth_provider, provider_user_id, auth_data, display_name=None, email=None, token=None) (:173); get_identity (:270); get_all_identities (:291); delete_identity (:307)  # :136

# navigator_auth 0.28.7 (external) — IdentityStore
decrypt_credential(identity) -> TokenResponse; delete(user_id, identity_id) -> bool; find_user_by_provider_account(provider, provider_user_id) -> Optional[Any];
get_by_provider(user_id, provider) -> Optional[UserIdentity]; get_one(user_id, identity_id); list_for_user(user_id) -> list[dict]; masked(identity) -> dict;
save_linked_identity(user_id, provider, token: TokenResponse, userinfo: Optional[dict] = None) -> UserIdentity; update_tokens(identity, token: TokenResponse) -> UserIdentity

# packages/ai-parrot-integrations/src/parrot/integrations/manager.py
def _build_jira_credential_sink(app) -> Any                                   # :81-107  IdentityVaultCredentialSink(db_pool=app['authdb']) or None
JiraOAuthManager(client_id=config.jira_client_id, client_secret=config.jira_client_secret, redirect_uri=config.jira_redirect_uri, app=app, credential_sink=_build_jira_credential_sink(app))  # :367-373 (MS Teams), :926-932 (Slack)

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py
async def connect_jira_handler(message, oauth_manager) -> None               # :50  user_id = str(message.from_user.id); create_authorization_url("telegram", user_id, extra_state={"chat_id": …})
def register_jira_commands(router, oauth_manager, session_clearer=None) -> None  # :156
class TelegramOAuthNotifier: notify_connected(chat_id, display_name, site_url) / notify_failure  # :192
# telegram/wrapper.py: app["telegram_jira_session_stamper"] = _stamp (:473); _build_permission_context user_id=telegram_id, channel="telegram" (:1280-1300); JiraPostAuthProvider wiring (:603-617)
# msteams/oauth_callback.py: class MSTeamsOAuthNotifier (:89); handle_msteams_jira_callback(request, token_set, state_payload) (:182); app["msteams_jira_oauth_notifier"] set by msteams/wrapper.py:215
# slack/oauth_callback.py: handle_slack_jira_callback; app["slack_jira_oauth_notifier"] set by slack/wrapper.py:132

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
self.credential_resolver = credential_resolver (:1055); self._client_cache: Dict[str, tuple] = {} keyed "{channel}:{user_id}" (:1059-1060); async def _pre_execute(self, tool_name, /, **kwargs) (:1316)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `Principal` binding | `AbstractOAuth2Manager.create_authorization_url` nonce payload | state dict | `oauth2_base.py:298-343` |
| `CredentialStore.save` | `AbstractOAuth2Manager._persist_token` | awaited before Redis | `oauth2_base.py:409-426` |
| `IdentityVaultCredentialStore` | `IdentityStore` read/decrypt APIs plus M8 transaction helper for replacement/deletion/re-sealing | upstream upsert is account-scoped; helper APIs must be verified against the upgraded dependency | `navigator_auth/identity/store.py` (0.28.7 baseline) |
| `IdentityPrincipalResolver` | `IdentityStore.find_user_by_provider_account(channel, channel_user_id)` | method call | same |
| `ConnectionEventPublisher` | `AbstractOAuth2Manager.handle_callback` / `_refresh_tokens` / `revoke` | awaited after persistence | `oauth2_base.py:354, :507, :497` |
| `ConnectionEventPublisher` | `AuditLedger.append(user_id, channel, tool, provider, credential_material)` | method call | `audit_ledger.py:338` |
| `ChannelNotifier` adapters | `TelegramOAuthNotifier`, `MSTeamsOAuthNotifier`, Slack DM | wrapped calls | `telegram/jira_commands.py:192`, `msteams/oauth_callback.py:89` |
| `make_oauth2_callback` | `IntegrationsService.persist_credential(user_id, provider, token_set, channel=…)` | method call | `oauth2_routes.py:173` |
| `setup_jira_oauth_routes` | `setup_oauth2_routes(app, "jira", "/api/auth/jira/callback")` | function call | `oauth2_routes.py:283` |
| `OAuthCredentialResolver.resolve` | `resolve_principal` → `manager.get_valid_token` | function + method | `credentials.py:197` |
| `ToolManager.execute_tool` | `CredentialRequired.to_payload()` | except clause | `manager.py:2273` |
| `ConnectionsHandler` | `IntegrationsService.list_for_principal / start_connect / status / disconnect` | method calls | `service.py:74` |
| `configure_tool_manager` | `list_users_integrations(user_id)` | function call | `user_objects.py:218` |
| `BotManager._register_oauth2_providers` | `register_descriptor_providers`, `set_principal_resolver` | function calls | `manager.py:2789-2807` |
| `JiraOAuthManager` hook | `fetch_accessible_resources`, `fetch_myself` | post-exchange hook | `jira_oauth.py:191, :214` |
| MCP per-call bearer | `get_headers(context)` → `MCPClient.call_tool` → HTTP session | M9 must add forwarding and principal session isolation; currently headers are dropped | `client.py:242, :282`; `integration.py:422-442`; `transports/http.py:390, :580` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.connections`~~, ~~`ConnectionManager`~~, ~~`OAuthProviderRegistry`~~, ~~`VaultCredentialResolver`~~, ~~`CredentialVault`~~, ~~`ConnectionChannel`~~, ~~`AuthRequirement`~~, ~~`requires_auth`~~ — brainstorm names; absent in `packages/` (probe `absent`, F019). Use the names in §2/§3 instead.
- ~~`NeedsAuthorizationError`~~, ~~`WebOAuthManager`~~, ~~`StateStore`~~ — never implemented; the MCP `OAuthManager` was removed (FEAT-262 TASK-1665).
- ~~`Principal`, `PrincipalResolver`, `resolve_principal`, `CredentialStore`, `CredentialPersistenceError`, `InvalidGrantError`, `RefreshTransientError`, `OAuth2ProviderDescriptor`, `StandardOAuth2Manager`, `DescriptorOAuth2Provider`, `PostExchangeHookRegistry`, `ConnectionEvent`, `ChannelNotifier`, `ChannelNotifierRegistry`, `ConnectionEventPublisher`, `AuthRequiredPayload`, `IdentityVaultCredentialStore`, `IdentityPrincipalResolver`, `ConnectionsHandler`, `list_users_integrations`, `legacy_audit`~~ — **new in this spec**; do not import until the owning task creates them.
- ~~`AbstractOAuth2Manager.credential_store` / `event_publisher` kwargs~~ — today the kwargs are `vault_writer`, `vault_reader`, `vault_deleter` (oauth2_base.py:131-133).
- ~~`JiraOAuthManager(AbstractOAuth2Manager)`~~ — today a plain class (jira_oauth.py:262); `JiraTokenSet(BaseModel)` (jira_oauth.py:66) is not an `AbstractOAuth2TokenSet`.
- ~~`IntegrationsService.list_for_principal` / `status`~~, ~~`start_connect(channel=…)`~~ — today `start_connect(user_id, agent_id, provider_id, return_origin)` with channel hard-coded `_WEB_CHANNEL` (service.py:291-338).
- ~~`/api/v1/connections*`~~ — only `/api/v1/agents/integrations/{agent_id}[/{provider}/connect|enable|DELETE]` exist (manager.py:2459-2472).
- ~~`/oauth/callback/{provider}`~~, ~~`/api/o365/oauth/*`~~ — the generic path is `/api/auth/oauth2/{provider}/callback` (oauth2_base.py:181); Jira's is `/api/auth/jira/callback` (routes.py:341).
- ~~`ToolManager` catching `CredentialRequired`~~ — only `AuthorizationRequired` is caught (manager.py:2273); `CredentialRequired` is re-raised by `AbstractTool.execute` (abstract.py:1194-1197).
- ~~`AuthorizationRequired.to_payload()` / `CredentialRequired.to_payload()`~~ — new.
- ~~`PermissionContext.principal_id` / `nav_user_id`~~ — only `user_id` (permission.py:81-126); on Telegram it is the raw telegram id (telegram/wrapper.py:1280-1300).
- ~~`UserSocketManager.send_to_principal`~~ — only process-local `send_direct_message(from_username, to_username, content)` (handlers/user.py:382); out of S-1 scope.
- ~~A consuming `navigator_eventbus` subscriber in `integrations/telegram|slack|msteams`~~ — none (F022); the bus is publish-only in parrot (fanout.py:74-87).
- ~~`IdentityStore` metadata-only write~~ — `save_linked_identity` requires a `TokenResponse` with `access_token`; channel identity rows are written by `IdentityMappingService` raw SQL (identity_mapping.py:173).
- ~~`CanonicalIdentityMapper` → Navigator `user_id` mapping~~ — it returns OID/e-mail only (identity.py:75); the Navigator id comes from `auth.user_identities` (M8).
- ~~`OAuth2ProviderDescriptor` YAML with `post_exchange` import paths~~ — hooks are registered Python callables only (S10).
- ~~`AbstractOAuth2Manager` provider-side revoke~~ — `revoke()` deletes locally only (oauth2_base.py:497-505).

### Edit Sites (Blueprint Anchors)

Verified against: `65aa79dfe` (`dev`, 2026-10-30). `/sdd-task` MUST re-run `grep -c` for every row it uses.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/auth/principal.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/auth/__init__.py` | MODIFY | `    "CredentialResolver": "parrot.auth.credentials",` | `auth/__init__.py:56` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2_base.py` | MODIFY | `_TOKEN_KEY_TEMPLATE = "oauth2:{provider}:{channel}:{user_id}"` | `oauth2_base.py:39` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2_base.py` | MODIFY | `_VAULT_NAME_TEMPLATE = "oauth2_{provider}_{channel}_{user_id}"` | `oauth2_base.py:44` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2_base.py` | MODIFY | `        vault_writer: Optional[VaultWriter] = None,` | `oauth2_base.py:131` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2_base.py` | MODIFY | `    async def create_authorization_url(` | `oauth2_base.py:298` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2_base.py` | MODIFY | `    async def handle_callback(` | `oauth2_base.py:354` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2_base.py` | MODIFY | `    async def _persist_token(` | `oauth2_base.py:409` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2_base.py` | MODIFY | `    async def get_valid_token(` | `oauth2_base.py:461` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2_base.py` | MODIFY | `    async def revoke(self, channel: str, user_id: str) -> None:` | `oauth2_base.py:497` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2_base.py` | MODIFY | `            except aiohttp.ClientError as exc:` | `oauth2_base.py:546` | 1 |
| `packages/ai-parrot/src/parrot/auth/o365_oauth.py` | MODIFY | `    async def _refresh_request(self, refresh_token: str) -> Dict[str, Any]:` | `o365_oauth.py:140` | 1 |
| `packages/ai-parrot-server/src/parrot/mcp/transports/http.py` | MODIFY | `    async def call_tool(self, tool_name: str, arguments: dict):` | `transports/http.py:580` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/auth/oauth2/events.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/auth/oauth2/legacy_audit.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/auth/oauth2/reencrypt.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/auth/oauth2/__init__.py` | MODIFY | `    UserAgentToolkitRow,` | `oauth2/__init__.py:26` | 1 (second occurrence is the `__all__` string `"UserAgentToolkitRow",` at :47 — distinct text) |
| `packages/ai-parrot/src/parrot/auth/oauth2/registry.py` | MODIFY | `def register_oauth2_provider(provider: OAuth2Provider) -> None:` | `registry.py:126` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | MODIFY | `_IDENTITY_OWNED_PROVIDERS = frozenset({"jira"})` | `service.py:53` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | MODIFY | `    async def start_connect(` | `service.py:291` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | MODIFY | `    async def confirm_enable(` | `service.py:346` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | MODIFY | `    async def disconnect(` | `service.py:406` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | MODIFY | `    async def persist_credential(` | `service.py:440` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/models.py` | MODIFY | `    channel: str = "web"` | `models.py:171` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/models.py` | MODIFY | `class AuthRequiredEnvelope(BaseModel):` | `models.py:117` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/models.py` | MODIFY | `class UserAgentToolkitRow(BaseModel):` | `models.py:183` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py` | MODIFY | `USER_AGENT_TOOLKITS_COLLECTION: str = "user_agent_toolkits"` | `persistence.py:34` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py` | MODIFY | `async def upsert_user_agent_toolkit(row: UserAgentToolkitRow) -> None:` | `persistence.py:113` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2_routes.py` | MODIFY | `        channel = state_payload.get("channel", "web")` | `oauth2_routes.py:264` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2_routes.py` | MODIFY | `        await svc.persist_credential(user_id, provider, token_set)` | `oauth2_routes.py:173` | 1 |
| `packages/ai-parrot/src/parrot/auth/routes.py` | MODIFY | `async def jira_oauth_callback(request: web.Request) -> web.Response:` | `routes.py:232` | 1 |
| `packages/ai-parrot/src/parrot/auth/routes.py` | MODIFY | `    app.router.add_get("/api/auth/jira/callback", jira_oauth_callback)` | `routes.py:341` | 1 |
| `packages/ai-parrot/src/parrot/auth/jira_oauth.py` | MODIFY | `class JiraTokenSet(BaseModel):` | `jira_oauth.py:66` | 1 |
| `packages/ai-parrot/src/parrot/auth/jira_oauth.py` | MODIFY | `class CredentialSink(Protocol):` | `jira_oauth.py:231` | 1 |
| `packages/ai-parrot/src/parrot/auth/jira_oauth.py` | MODIFY | `class JiraOAuthManager:` | `jira_oauth.py:262` | 1 |
| `packages/ai-parrot/src/parrot/auth/jira_oauth.py` | MODIFY | `        credential_sink: Optional[CredentialSink] = None,` | `jira_oauth.py:285` | 1 |
| `packages/ai-parrot/src/parrot/auth/credentials.py` | MODIFY | `class CredentialRequired(Exception):` | `credentials.py:113` | 1 |
| `packages/ai-parrot/src/parrot/auth/credentials.py` | MODIFY | `class OAuthCredentialResolver(CredentialResolver):` | `credentials.py:184` | 1 |
| `packages/ai-parrot/src/parrot/auth/exceptions.py` | MODIFY | `class AuthorizationRequired(Exception):` | `exceptions.py:12` | 1 |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | `        except AuthorizationRequired as auth_exc:` | `manager.py:2273` | 1 |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | `from ..auth.exceptions import AuthorizationRequired` | `manager.py:19` | 1 |
| `packages/ai-parrot/src/parrot/mcp/client.py` | MODIFY | `    user_id: Optional[str] = field(default=None)` | `client.py:236` | 1 |
| `packages/ai-parrot/src/parrot/mcp/integration.py` | MODIFY | `def create_oauth_mcp_server(` | `integration.py:727` | 1 |
| `packages/ai-parrot/src/parrot/mcp/integration.py` | MODIFY | `    async def add_oauth_mcp_server(` | `integration.py:1394` | 1 |
| `packages/ai-parrot/src/parrot/mcp/integration.py` | MODIFY | `    async def add_netsuite_mcp_server(` | `integration.py:1706` | 1 |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `JIRA_REDIRECT_URI = config.get("JIRA_REDIRECT_URI")` | `conf.py:746` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | `            # Per-user JIRA client cache: {"{channel}:{user_id}": (client, token_hash)}` | `jiratoolkit.py:1059` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | `    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None:` | `jiratoolkit.py:1316` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/connections.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/services/identity_principal.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py` | MODIFY | `class IdentityVaultCredentialSink:` | `identity_credential_sink.py:24` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/integrations.py` | MODIFY | `            descriptor = await svc.confirm_enable(user_id, agent_id, provider)` | `handlers/integrations.py:178` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/integrations.py` | MODIFY | `    async def _post_connect(self) -> web.Response:` | `handlers/integrations.py:109` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/user_objects.py` | MODIFY | `            enablements = await list_user_agent_toolkits(user_id, agent_id)` | `user_objects.py:218` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/user_objects.py` | MODIFY | `from parrot.auth.oauth2.persistence import list_user_agent_toolkits` | `user_objects.py:18` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `        except AuthorizationRequired as exc:` | `handlers/agent.py:1916` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `    async def _register_oauth2_providers(self, app: web.Application) -> None:` | `manager/manager.py:2789` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `from ..handlers.integrations import IntegrationsHandler` | `manager/manager.py:41` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | `def _build_jira_credential_sink(app: Any) -> Any:` | `integrations/manager.py:81` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | `                        credential_sink=_build_jira_credential_sink(app),` | `integrations/manager.py:372, :931` | 2 — context: `:372` sits under `self.logger.info("MS Teams bot '%s': initialized JiraOAuthManager", name)`; `:931` under `"Slack bot '%s': initialized JiraOAuthManager"` |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py` | MODIFY | `async def connect_jira_handler(` | `telegram/jira_commands.py:50` | 1 |
| `docs/auth/connections.md` | CREATE | — | — | — |
| `docs/auth/jira-credential-ownership.md` | MODIFY | `# Who owns the Jira credential` | `docs/auth/jira-credential-ownership.md:1` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Protocol injection from server into core** — `CredentialSink` on `JiraOAuthManager` (jira_oauth.py:231-259) is the template for `CredentialStore`, `PrincipalResolver` and `ChannelNotifier`; core defines the Protocol and a module-level setter (`set_vault_credential_store`, vault_utils.py:46), the server/integrations register implementations at startup. `ai-parrot` never imports `parrot.services.*` or `parrot.integrations.*`.
- **Durable first, cache second** — `_persist_token` writes the store, then Redis (reverses today's order and makes the store failure fatal, S2). Reads stay Redis → store (cold start only) → legacy → refresh (G4 of FEAT-735: no per-call Postgres decrypt).
- **Publish-only Streams bus** — `setup_connection_fanout` copies `_validate_bus` (fanout.py:74-87); parrot publishes, consumers live elsewhere. The in-process notifier registry is the load-bearing path (U5).
- **Principal from the authenticated session, never the body** — `IntegrationsHandler._get_user_id` (handlers/integrations.py:43-62) is the pattern for `ConnectionsHandler`; `return_origin` is validated against `WEB_OAUTH_ALLOWED_ORIGINS` only for `channel == "web"`.
- **`nav_user_id` under its own state key** — never reuse `state["user_id"]` as the Navigator id (wiki memory `mem-30df362979b0`); callbacks fail closed on a missing or non-numeric id (identity_mapping.py:173, msteams/oauth_callback.py:258-284).
- **Manager hooks are the extension seam** — `_exchange_code`, `_refresh_request`, `_discover_identity`, `_build_token_set`, `authorization_url_extra_params` (oauth2_base.py:345-612); `StandardOAuth2Manager` implements them from the descriptor; `O365OAuthManager` keeps its own.
- **Typed hook registry, not dynamic import** — `PostExchangeHookRegistry.register("atlassian_accessible_resources", fn)` in `jira_oauth.py`; descriptors name hooks, never import paths (S10).
- **Hard cuts for internal APIs** — `CredentialSink`, `vault_writer/reader/deleter` kwargs, `confirm_enable`, `user_agent_toolkits` and `jira_oauth_callback` are removed, not shimmed (no external consumers policy); the only compatibility surfaces are the `/api/auth/jira/callback` path (IdP redirect URI) and the `/enable` no-op (admin UI until S-3a).
- async/await throughout; Pydantic v2; `self.logger`; `aiohttp` only; `ruff` TID251 bans `requests`/`httpx`.

### Known Risks / Gotchas
- **Reversing FEAT-144** (channel-separate credentials, per-agent enablement) widens who can use a connection; the spec records the reversal (U2) and adds PBAC on connect/disconnect (S4). Removing `user_agent_toolkits` must land together with the hydration change (user_objects.py:218) or existing web users lose tools (S5).
- **Two principal keys** — Navigator bigint vs Entra OID/e-mail; both stored (U1). `IdentityPrincipalResolver` prefers the identity row's `provider_user_id == oid` for `msteams` and e-mail otherwise; anonymous/dev users without either fail closed.
- **Unlinked Telegram users** hold only `jira:oauth:telegram:<telegram_id>`; they get the "/login first" reply and re-connect (U3). Run `legacy_audit` before cutover and announce.
- **Legacy key window** — `OAUTH2_LEGACY_KEYS_UNTIL` must be set in prod; after it no legacy read occurs. O365 legacy keys were already principal-scoped (`oauth2:o365:web:{nav_user_id}`), so their rewrite is a rename.
- **Callback alias** — the Atlassian app's registered redirect URI is `/api/auth/jira/callback`; the generic handler must be mounted there, otherwise every Jira link breaks. Do not change `JIRA_REDIRECT_URI`.
- **Notifier process topology** — Telegram/Slack/Teams notifiers live on the same aiohttp app as the callback today (`app['jira_oauth_notifier']`, `app['msteams_jira_oauth_notifier']`, `app['slack_jira_oauth_notifier']`); if a deployment splits them, delivery silently stops — the registry logs a warning when no notifier is registered for `event.channel`, and the bus publication is the out-of-process fallback (S6).
- **`IdentityStore` has no metadata-only write**; `save_linked_identity` needs an `access_token`. Channel identity rows stay with `IdentityMappingService` (identity_mapping.py:173). `TokenResponse.from_oauth_response(payload, scopes)` maps a standard token payload; `JiraTokenSet` extras go in `raw`.
- **Single-account v1** (S3) — M8 atomically replaces the provider credential, including when the external account changes; raw IdentityStore upsert alone retains old accounts; `account_id` is carried everywhere so v2 can add selection without a schema break.
- **High blast radius** in `AbstractOAuth2Manager` (O365 live path) and `ToolManager.execute_tool` (every tool). Mitigation: the Validation Contract runs `tests/auth/test_oauth2_base.py` and the AgentTalk envelope tests on every task; the `CredentialRequired` catch is gated on the exception type only.
- **MCP** — `add_oauth_mcp_server(user_id=…)` callers in `bots/agent.py:1038-1200` keep working (optional param); `NetSuiteM2MAuth(user_id="m2m")` is M2M and untouched.
- **Audit ledger material** — `credential_material` is fingerprinted (audit_ledger.py:338-352); pass the event kind + account id, never a token.
- **External provider facts (R6)** — verified against provider docs on 2026-10-30 (closes C23):
  - **Atlassian** ([3LO apps](https://developer.atlassian.com/cloud/jira/platform/oauth-2-3lo-apps/)): rotating refresh tokens — each refresh returns a new refresh token and disables the one used; 90-day **inactivity** expiry reset by each refresh (no absolute expiry stated); 10-minute reuse interval for concurrent exchanges. → `RefreshPolicy(rotating=True, sliding=True, refresh_lifetime_s=7776000)`. Persisting the new refresh token durable-first (S2) is mandatory: losing it loses the grant.
  - **Microsoft identity platform** ([refresh tokens](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens)): 90 days default (24 h for `spa` redirect URIs); a new refresh token is issued on every use but the **old one is not revoked** — store the new one and discard the old. Can be revoked early (password reset, admin revoke) → surfaces as `invalid_grant` → `InvalidGrantError` (S7). → O365 keeps its subclass; if it adopts a descriptor: `RefreshPolicy(rotating=False, sliding=True, refresh_lifetime_s=7776000)`.
  - **NetSuite** ([refresh token request](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_158082518856.html)): access token always 3600 s. **Public clients**: the refresh response returns a new refresh token, one-time use, valid 2 days by default, configurable 1–720 h on the integration record (absolute). **Confidential clients**: Oracle documents no refresh-token lifetime and the refresh response carries no new refresh token; the widely-reported 7-day limit comes from community/vendor posts only, so it stays unverified. Expiry → `invalid_grant` → re-consent. Not used in S-1 (NetSuite is M2M via `NetSuiteM2MAuth` / M9); recorded for a future descriptor.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2` | descriptor, principal, event and payload models (existing core dep) |
| `aiohttp` | existing | token endpoints, identity probes, handlers |
| `redis.asyncio` | existing | hot cache, nonce state, refresh locks |
| `navigator-auth` | `>=0.28.8` (0.28.7 in `.venv` / `uv.lock`; TASK-4664 noted the real-DB Jira write needs 0.28.8). 0.28.8 and 0.28.9 are on PyPI since 2026-10-23 — floor bumped as a pre-implementation step (Worktree Strategy → Exclusive resources) | `IdentityStore`, `TokenResponse`, `auth.user_identities` |
| `navigator-session` | existing | `KeyRing` for the default `VaultUtilsCredentialStore` |
| `navigator-eventbus` | existing | optional publish-only Streams bus |
| `PyYAML` | existing | `OAUTH2_PROVIDERS_FILE` loader |

---

## 8. Open Questions

> Resolved items carried from the brainstorm and the proposal (decision trail). Unresolved items are implementation-time confirmations.

- [x] Single core with channel consumers (web, Telegram, Teams) — *Resolved in brainstorm*: yes.
- [x] Spec count — *Resolved in brainstorm*: one brainstorm, four specs (core, Telegram migration, web, Teams); *refined at spec time*: S-1 now, the consumer specs as separate `/sdd-spec` runs depending on FEAT-773 — S-2 Telegram, S-3a web + Slack, S-3b Teams, and **S-4 CLI / local MCP** (added 2026-10-30: CLI-based agents and MCP-based tools running in a CLI need their own principal resolution, out-of-process connect and credential retrieval; a sub-spec, not a task, because those are design decisions S-1 does not take).
- [x] Telegram login links to a platform user — *Resolved in brainstorm*: confirmed; *located*: `TelegramUserSession.nav_user_id` after `/login`, persisted to `auth.user_identities` by the combined Jira flow (F035, F043).
- [x] U1 principal key — *Resolved in proposal*: both columns, Navigator `user_id` primary, Entra OID/e-mail secondary.
- [x] U2 reverse FEAT-144 — *Resolved in proposal*: reverse fully — one connection, all agents, all channels; `user_agent_toolkits` dropped.
- [x] U3 unlinked Telegram users — *Resolved in proposal*: force re-connect; no indefinite channel-keyed fallback.
- [x] U4 module placement — *Resolved in proposal*: evolve `parrot.auth.oauth2` in place; no `parrot.connections`.
- [x] U5 completion transport — *Resolved in proposal*: notifier registry load-bearing + publish-only bus additive.
- [x] Vault durable backend for non-Jira providers — *Resolved at spec time*: Identity Vault for every 3LO provider through `CredentialStore`; `VaultTokenSync` stays for static keys and device-code.
- [x] `requires_auth` on toolkit vs tool — *Resolved by research*: the existing `credential_provider` (toolkit default, per-tool override, toolkit.py:331/717) is the declaration; no `requires_auth`.
- [x] Hot-swap vs declare-once — *Resolved by research + scope*: `JiraToolkit` declares `credential_provider="jira"` (declare-once on the broker seam); removing the AgentTalk placeholder is S-3a.
- [x] Legacy key cutover date (`OAUTH2_LEGACY_KEYS_UNTIL`) and the acceptable unbound count — *Resolved 2026-10-30 (Jesus)*: ops sets `OAUTH2_LEGACY_KEYS_UNTIL` = **S-1 prod deploy + 30 days** (every active user migrates on first token use, read-once/rewrite/delete). **No unbound-count gate**: unbound legacy keys belong to unlinked Telegram users, who re-connect by design (U3). `legacy_audit` runs before cutover and its bound/unbound counts go into the user announcement. (M10 docs, AC-13.)
- [x] PBAC allowlist shape — *Resolved 2026-10-30 (Jesus)*: **navigator-auth PDP only**. Policies for `integration:connect` / `integration:disconnect` are authored in the PDP that `_check_pbac` already calls (service.py:490, fail-closed); parrot passes `provider` and `scopes` in the evaluation context and keeps **no** policy store or tenant allowlist of its own. `docs/auth/connections.md` (M10) ships a sample policy. (M6, AC-8.)
- [x] Identity Vault encryption key management — *Resolved 2026-10-30 (Jesus)*: navigator-auth / navigator-session keep owning key material and the cipher (`VAULT_MASTER_KEY_v{N}` + `VAULT_ACTIVE_KEY_ID`; `key_version` stamped on every write); **S-1 adds a re-encryption job** (`python -m parrot.auth.oauth2.reencrypt`, M10) so a rotated-out key can be retired. Research finding that shaped it: `IdentityStore.update_tokens` (the refresh path) re-seals only access/refresh, never `id_token`, so a row can report the active key while retaining old-key ciphertext; M10 inspects every token column and preserves metadata when re-sealing. (M10, AC-18.)
- [x] R6 provider refresh facts — *Resolved by research 2026-10-30*: verified against Atlassian, Microsoft and Oracle docs (§7 External provider facts). `RefreshPolicy` gains `sliding`; Jira descriptor = `rotating=True, sliding=True, 90 d`; a returned refresh token always replaces the stored one (Microsoft does not revoke the old one). NetSuite confidential-client lifetime is undocumented by Oracle (the "7-day" figure is community-only) — not needed in S-1. (M3, M7, AC-20.)
- [x] navigator-auth `>=0.28.8` availability — *Resolved by research 2026-10-30*: 0.28.8 (2026-10-23 01:37 UTC) and 0.28.9 (2026-10-23 23:59 UTC) are on PyPI. The `.venv` and `uv.lock` are still on 0.28.7 and both pyproject floors say `>=0.28.3`; the operator raises both floors to `>=0.28.8` and re-locks on `dev` before the feature worktree is created (Worktree Strategy → Exclusive resources). The deployment image picks it up from the lock.
- [x] S-4 pre-check — *Resolved by code check 2026-10-30*: (a) **gap found**: neither `UsersIntegrationRow` nor `IntegrationDescriptor` (models.py:21) had `updated_at`, and `connected_at` is first-connect only, so a CLI could not detect a completed *re*connect → `updated_at` added to both (§2 Data Models, M6, AC-19). (b) **holds**: `CredentialStore` is a Protocol in core `parrot/auth/oauth2_base.py` depending only on core `Principal`; core `persistence.py` imports only `parrot.interfaces.documentdb` and `parrot.auth.oauth2.models` — an HTTP-backed store can live outside `ai-parrot-server`. No new module in S-1.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration doc** (never over this spec).
> Model: `gpt-5.6-luna` (codex-cli 0.164.0) · Status: completed · Transcript: `sdd/state/FEAT-773/design_research/`
> All cited paths passed containment and existence checks; three code claims (S4, S7, S9) were spot-checked in source.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make principal binding explicit in OAuth state (architecture) | CONFIRM | Matches U1; principal bound at start, verified at callback, fail closed. | §2 Overview, §3 M1/M2, AC-2 |
| S2 | Do not silently succeed when durable persistence fails (risk) | CONFIRM | Verified `_persist_token` swallows vault failures (oauth2_base.py:415-420) and the Jira sink is after Redis (jira_oauth.py:541-548); durable-first with `CredentialPersistenceError`. | §3 M2, AC-5 |
| S3 | Resolve account cardinality before changing keys (api) | CONFIRM | v1 single account per provider, replace on reconnect; `account_id` carried everywhere. | §2 Data Models, §7, AC-12 |
| S4 | Enforce PBAC on connect and revoke (risk) | CONFIRM | Verified `start_connect` (service.py:291) has no PBAC; `_check_pbac` (service.py:490) reused for `integration:connect` / `integration:disconnect` with scopes. | §3 M6, AC-8 |
| S5 | Separate connection ownership from agent enablement (architecture) | CONFIRM (modified) | U2 drops enablement, so no new capability mechanism; hydration (user_objects.py:218) switches to connections in the same module and `/enable` stays a no-op until S-3a. | §3 M6, §7 risks |
| S6 | Define cross-process notifier delivery explicitly (architecture) | CONFIRM (constraint) | U5 keeps the registry load-bearing; same-process constraint recorded, notifier failures isolated, bus is the out-of-process path; web cross-process delivery is S-3a. | §3 M4, §7 risks |
| S7 | Distinguish invalid refresh tokens from transient failures (risk) | CONFIRM | Verified oauth2_base.py:543-549; `InvalidGrantError` vs `RefreshTransientError`. | §3 M2, AC-10 |
| S8 | Use a superset needs-auth contract (api) | CONFIRM | `AuthRequiredPayload` union; both exceptions serialize identically in ToolManager and AgentTalk. | §3 M5, AC-6 |
| S9 | Make MCP credential resolution genuinely per-call (architecture) | CONFIRM | Config seam verified, but review found headers dropped at integration.py:442. M9 now owns transport forwarding, proxy provider declaration and principal-isolated sessions. | §3 M9, AC-11 |
| S10 | Keep provider-specific behavior typed before introducing YAML hooks (alternative) | CONFIRM (modified) | Typed descriptor + generic RFC 6749 manager; hooks are an in-code registry, never YAML import paths; O365 keeps its subclass. | §3 M3, §7 patterns |
| S11 | Require a migration and isolation contract matrix before cutover (testing) | CONFIRM | Added to §4 unit + integration tests and AC-17. | §4, AC-17 |

Summary: **11** confirmed (3 with modifications) · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Default isolation unit**: ONE feature worktree for the spec (`feat-FEAT-773-delegated-auth-connections`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edges = imports of a symbol fixed in §3):
  - M2 → M1 (`Principal` in the nonce payload), M2 → M4 (`ConnectionEventPublisher`, `ConnectionEvent`)
  - M3 → M2 (`StandardOAuth2Manager(AbstractOAuth2Manager)`, `CredentialStore`)
  - M5 → M1 (`resolve_principal` in `OAuthCredentialResolver`)
  - M6 → M1, M2, M4, M5 (`Principal`, manager signatures, events, `AuthRequiredPayload` in `AuthRequiredEnvelope`)
  - M7 → M2, M3, M4 (`StandardOAuth2Manager`, hook registry, publisher) and M8 (notifier adapters registered before the Jira route switch)
  - M8 → M1, M2, M4 (Protocols) and M3 (`register_descriptor_providers`)
  - M9 → none (FEAT-264 broker path plus HTTP transport forwarding); M10 → M2, M7, M8 (key templates, audit, metadata-preserving re-sealing adapter)
  - Concurrent after M1 + M4 land: M2 ∥ M5 ∥ M9; after M2: M3 ∥ M6; then M7 + M8 (serialized on shared files); M10 last.
- **Shared files** (tasks serialized): `parrot/auth/oauth2/__init__.py` (M3, M4, M6 exports); `parrot/auth/oauth2/models.py` (M5, M6); `parrot/auth/credentials.py` (M5 only, but M1 export touches `auth/__init__.py`); `parrot/auth/jira_oauth.py` (M7 only); `ai-parrot-server manager/manager.py` (M6 routes, M8 registration); `ai-parrot-integrations integrations/manager.py` (M8 only); `tools/manager.py` (M5 only).
- **Exclusive resources**: the `navigator-auth>=0.28.8` floor bump touches `packages/ai-parrot/pyproject.toml`, the root `pyproject.toml` constraint and `uv.lock` (locked at 0.28.7) — done by the main-checkout operator on `dev` **before** the feature worktree is created (worktree agents never lock/install, worktree-management §4); no task owns it. Otherwise none (no compiled extensions, no DB migration — `auth.user_identities` already exists; `user_agent_toolkits` removal is a code change, DocumentDB collection left in place).
- **Cross-feature dependencies**: none in flight on these files (git lane: `mcp/client.py` frozen since 2026-06-29; `parrot/auth/` last changed by FEAT-735/FEAT-729, both merged 2026-10-23). Consumer specs S-2 / S-3a / S-3b / S-4 depend on FEAT-773 being merged.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-30 | Jesus Lara (with Claude Fable 5.1) | Initial draft from proposal FEAT-773 (accepted). S-1 scope; decisions U1–U5 + vault owner carried forward; codex design research folded (11 CONFIRM). Codebase Contract verified against `65aa79dfe`. |
| 0.2 | 2026-10-30 | Jesus Lara (with Claude Fable 5.1) | Declared S-4 (CLI-based agents + MCP-based tools in a CLI) as a fifth consumer sub-spec: Non-Goals, §8 spec-count trail, S-4 pre-check item, Worktree Strategy dependency. No module or AC changes. |
| 0.3 | 2026-10-30 | Jesus Lara (with Claude Opus 5.5) | Resolved all six §8 open questions. Decisions: legacy cutover = deploy + 30 d with no unbound gate; PBAC policy in the navigator-auth PDP only; S-1 adds the Identity Vault re-encryption job (M10, AC-18). Research: R6 provider facts verified (`RefreshPolicy.sliding`, Jira descriptor values, AC-20); navigator-auth 0.28.8/0.28.9 on PyPI → floor bump + re-lock as a pre-implementation step; S-4 pre-check found a missing `updated_at` (added, AC-19). |
| 0.4 | 2026-10-30 | Codex | Resolve four design-review findings: mixed-key-safe re-encryption and retirement gate; atomic provider-account replacement/deletion; MCP request-header forwarding and session isolation; explicit O365 typed refresh errors. Strengthen regression/integration criteria and module ownership. |
| 0.5 | 2026-10-30 | Jesus Lara (with Claude Opus 5.5) | `/sdd-task`: added the 25 package-local test files of TASK-4937…4964 to the §4 Validation Contract, as §4 requires. No module or AC changes. |

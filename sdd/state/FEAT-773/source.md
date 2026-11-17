---
kind: file
jira_key: null
file_path: "artifacts/Brainstorm Delegated Auth Connections (OAuth2 3LO core + channel consumers).md"
fetched_at: 2026-10-30T11:52:11Z
summary_oneline: Generic OAuth2 3LO connections core (parrot.connections) with principal-keyed vault, consumed by web, Telegram and Teams channels
---

# Brainstorm: Delegated Auth Connections (OAuth2 3LO core + channel consumers)

Oct 30, 2026 · @Jesus Lara · **Status**: exploration · **Recommended Option**: B · **Spec split**: 4 specs (see §8)

```yaml
# SDD flow type and base branch
type: feature
base_branch: dev
```

## Problem Statement

Users cannot connect their own Office 365, Jira or any other OAuth2 (3LO) service from the AgentChat UI, and the delegated-auth logic that does exist is implemented three times, each tied to one channel.

What the codebase appears to hold today (every item is a claim from earlier design sessions, not a verified fact — see §3 and §4):

- **JiraToolkit / Telegram (FEAT-083, in production)**: `JiraOAuthManager`, Redis token keys shaped `jira:oauth:<channel>:<user_id>`, a `/connect_jira` command in `ai-parrot-integrations`, `CredentialResolver` + `AuthorizationRequired` in the toolkit path.
- **MCP client (NetSuite design, May 2026)**: `OAuthManager` for a local CLI callback (`127.0.0.1:8765`), with a `WebOAuthManager` / `StateStore` / `TokenStore` / `NeedsAuthorizationError` design that may or may not have landed.
- **O365**: `O365AuthMode.DELEGATED` and an older Svelte page hitting `/api/o365/oauth/initiate|status`, passing `user_id` in the request body.

Three consequences:

1. **No single place to add a provider or a channel.** Adding MS Teams or the web UI today means re-implementing state handling, token exchange, refresh and storage per integration.
2. **Connections are channel-bound.** A Jira account connected from Telegram is invisible to the same user on the web, because the vault key carries the channel, not the platform principal.
3. **Two "needs auth" protocols.** Toolkits raise `AuthorizationRequired`; the MCP path was designed around `NeedsAuthorizationError`. ToolManager and the chat UI cannot treat them uniformly.

**Who is affected**: end users of AgentChat (cannot self-serve connections), Telegram users (connections do not follow them to other channels), and developers adding providers/channels (duplicate, security-sensitive code).

**Why now**: the web UI is the next consumer, MS Teams is queued behind `TeamsHumanChannel`, and the existing Telegram flow is the only one in production — the migration cost only grows with each new channel built on the current shape.

## Constraints & Requirements

- **One implementation, many consumers.** Provider registry, state/PKCE, token exchange, refresh, revoke and storage live in exactly one module. Channels (web, Telegram, MS Teams, future Slack/WhatsApp) only decide how to present a link and how to notify completion.
- **Core must not depend on integrations.** `ToolManager` and the MCP client (both in `ai-parrot` core) consume credentials, so the core of this feature lives in `ai-parrot`, HTTP routes in `ai-parrot-server`, channel adapters in `ai-parrot-integrations` and the Svelte UI.
- **Connections are keyed by platform principal**, not by channel: `(tenant, principal_id, provider, account)`. A user who connects Jira on the web has it on Telegram. This requires every channel to map its external identity (Telegram id, `aadObjectId`, web session) to the navigator-auth principal — Jesus confirmed the Telegram login already links to a platform user (⚠️ VERIFY the exact mapping in code).
- **Refresh tokens must survive logout.** OAuth material is persistent per principal; session-scoped (BYO API keys from the Dec 2025 design) is a separate, ephemeral scope of the same vault. Whatever "session vault" exists today must be inspected before assuming either scope (spike S1).
- **Credentials never reach the LLM or the frontend.** The UI sees connection status, account display name, scopes and expiry only. Tool results carry `auth_url`, never tokens. Consistent with the existing security invariant (per-session ToolManager isolation, no secrets in the conversational plane).
- **Zero re-connect on migration.** Telegram users in production must not have to re-authorize Jira: legacy keys are read and rewritten under the principal key during a dual-read window.
- **Callback is a single server endpoint per provider**, registered once at the IdP (`/oauth/callback/{provider}`), regardless of which channel started the flow. The channel that started it is carried in the signed `state`.
- **Completion is decoupled.** The callback request process may not be the channel's process (Telegram autonomous bot). Completion is published as an event (`navigator-eventbus`) and each channel subscribes; the callback never calls a channel directly.
- **Provider-specific behavior is data, not code**: rotating refresh tokens (Atlassian, NetSuite 7-day), PKCE-only public clients (NetSuite), identity probe endpoint, consent-always scopes — all expressed in the provider descriptor.
- **Deterministic contract, probabilistic consumer.** The LLM only ever receives `ToolResult(status="authorization_required")`; whether to show a link, a card or a deep link is a deterministic channel decision.
- Language split: code, identifiers, SDD artifacts in English.
- **No code assumptions in this document are to be trusted by `/sdd-spec`.** `/sdd-proposal` performs the code research (§4) and corrects §3 and §10 before any spec is written.

## Prior Work & Claimed References (⚠️ VERIFY)

Nothing in this section was read from the repository during this brainstorm. Each row is what earlier design sessions (FEAT-083 Jira 3LO, NetSuite MCP, O365 delegated, per-session credentials) said would or did exist. `/sdd-proposal` must confirm, correct or strike every row with grep anchors before `/sdd-spec` cites it.

| Claimed artifact | Origin | Expected location (guess) | Status |
| --- | --- | --- | --- |
| `JiraOAuthManager` (state nonce in Redis, token exchange, rotating refresh with distributed lock, `accessible-resources` → `cloud_id`) | FEAT-083 | `ai-parrot-integrations` or `ai-parrot-tools` Jira package | ⚠️ VERIFY exists; which package; Redis key format |
| `jira_oauth_manager` attribute on `BotManager` (boot warning "jira\_oauth\_manager unset") | e2e brainstorm S1 (observed in boot logs) | `parrot/manager/manager.py` | Likely exists — ⚠️ VERIFY where it is set and consumed |
| Jira OAuth callback routes | FEAT-083 | `ai-parrot-server` or integrations | ⚠️ VERIFY path, auth exclusions, success page |
| `/connect_jira` Telegram command (deep link, `/disconnect`) | FEAT-083, confirmed by Jesus as `/connect` in integrations | `ai-parrot-integrations` Telegram wrapper | Exists per Jesus — ⚠️ VERIFY exact command names and how it reaches the manager |
| `CredentialResolver` ABC + `OAuthCredentialResolver` + `StaticCredentialResolver` | FEAT-083 | near `JiraToolkit` | ⚠️ VERIFY; is it generic or Jira-typed (`JiraTokenSet`)? |
| `AuthorizationRequired` exception → `ToolResult(status="authorization_required", metadata.auth_url)` in `ToolManager.execute_tool` | FEAT-083 | `parrot/tools/manager.py` (core) | ⚠️ VERIFY status literal and metadata shape |
| `AbstractToolkit._pre_execute` / `_post_execute` hooks | FEAT-083 | `parrot/tools/toolkit.py` | ⚠️ VERIFY |
| `PermissionContext.channel` field | FEAT-083 | `parrot/tools/...` | ⚠️ VERIFY |
| AgentTalk hot-swap of Jira tools after auth (`_sync_tools_to_llm`) | FEAT-083 | AgentTalk view / BasicAgent | ⚠️ VERIFY whether implemented or still a placeholder-tool approach |
| `OAuthManager` for MCP client (local callback `127.0.0.1:8765`, PKCE) in `integration.py` / `oauth.py` | NetSuite session | `parrot/mcp/...` (core) | ⚠️ VERIFY PKCE S256, public-client support, `token_supplier` signature |
| `WebOAuthManager`, `StateStore`, `TokenStore` keyed `(user_id, server_name)`, `NeedsAuthorizationError` | NetSuite session (designed) | unknown | ⚠️ VERIFY whether any of it landed — likely did NOT |
| `add_oauth_mcp_server(name, url, client_id, client_secret, auth_url, token_url, scopes, user_id)` on the MCP mixin | AgentTalk docs (Oct 2025) | `parrot/bots/...` MCP mixin | ⚠️ VERIFY current signature; `user_id` baked at add-time is the anti-pattern this feature removes |
| `O365AuthMode` enum (`DIRECT`, `OBO`, `DELEGATED`) on the O365 tool | O365 session | `ai-parrot-tools` O365 | ⚠️ VERIFY; delegated token storage location |
| Svelte page for O365 (`/api/o365/oauth/initiate`, `/status/{user_id}`, popup + countdown) | O365 session (Oct 2025) | TROC UI or admin UI | ⚠️ VERIFY whether it shipped; `user_id` in body must be removed |
| `user_socket_manager` on `BotManager` (boot warning "user\_socket\_manager unset") | e2e brainstorm S1 | `parrot/manager/manager.py` | Likely exists — ⚠️ VERIFY API for sending an event to one user's sockets |
| Per-session `ToolManager` + session credentials (`PUT` to configure a session) | Dec 2025 session | AgentTalk / BotManager | ⚠️ VERIFY what landed; defines the ephemeral vault scope |
| "Session vault" per user | Jesus, this session | navigator-session / navigator-auth? | ⚠️ VERIFY what it is, its API, persistence and encryption — **spike S1** |
| `OAuthRoutesMixin` on `HttpMCPServer`; OAuth 2.1 AS in navigator-auth (RFC 9728, DCR, PKCE) | FEAT-MCP-AGENT-METHODS | `parrot/mcp/transports/http.py`; navigator-auth | Exists per e2e brainstorm — **out of scope** (parrot as resource server, opposite direction); note only to avoid conflating the two |
| `TeamsHumanChannel` spec | overview (queued) | — | Not yet built — Spec 3b depends on it or on the Bot Framework wrapper's proactive messaging |

## Research Mandate for `/sdd-proposal`

The proposal is not allowed to inherit any claim from §3 without reading the code. Deliverable: §3 rewritten as *Verified Codebase References* with grep anchors (no line numbers), and §10 rewritten as the real *Does NOT Exist* list.

### R1. Vault and identity (decides the data model)

- [ ] What is the "session vault"? Find it (navigator-session, navigator-auth, parrot session state, Redis helper). Record: API, key shape, TTL/persistence, encryption at rest, whether it is per-session or per-user.
- [ ] How does the Telegram wrapper resolve the platform user: is there a `telegram_id → navigator-auth user` link at login? Where is it stored? Same for MS Teams (`aadObjectId`) and AgentTalk (session/JWT).
- [ ] What `PermissionContext` carries today (`user_id`, `channel`, roles, tenant). Is `user_id` the platform principal or the channel id in each channel?

### R2. The Jira path in production (decides the migration)

- [ ] Locate `JiraOAuthManager`, its Redis key format, refresh/lock logic, callback handler, success page, Telegram notification call.
- [ ] Locate `/connect` in integrations; how it builds the auth URL and who it calls.
- [ ] Locate `CredentialResolver`, `AuthorizationRequired`, the `ToolManager.execute_tool` catch, `_pre_execute`. Confirm they are generic or Jira-typed.
- [ ] Confirm how `JiraToolkit` builds its per-user client and whether a `(user_id, token_hash)` client cache exists.
- [ ] Enumerate every reader of the legacy Redis keys (there may be more than the toolkit).

### R3. MCP client auth (decides reuse vs rewrite)

- [ ] Locate the MCP `OAuthManager` / `oauth.py`: PKCE S256 present? public client without secret? refresh rotation? `token_supplier` signature and whether it receives a per-call user context (`ReadonlyContext` or equivalent).
- [ ] Confirm whether `WebOAuthManager` / `StateStore` / `TokenStore` / `NeedsAuthorizationError` exist at all.
- [ ] Current `add_oauth_mcp_server` / `add_*_mcp_server` signatures: where credentials are bound (configure-time vs call-time).

### R4. Server surfaces (decides routes and events)

- [ ] `BotManager` route registration pattern, auth middleware and exclusion list (callback must be reachable unauthenticated; `/connections` must be authenticated).
- [ ] `user_socket_manager` API: send to one principal's sockets; how AgentTalk identifies the principal per socket.
- [ ] `navigator-eventbus` usage in ai-parrot today: is there a pub/sub the Telegram bot process already consumes? Topic naming conventions.
- [ ] Existing OAuth-related routes (`/api/o365/oauth/*`, Jira callback) to retire or alias.

### R5. UI surfaces (Spec 3a)

- [ ] AgentChat (Svelte 5) structure: where a settings/connections panel fits, existing WS event handling, existing A2UI block types and the ActionRouter status (FEAT-B).
- [ ] Whether any O365 connect page shipped in TROC UI or the admin UI.

### R6. Provider facts (external, re-verify — these change)

- [ ] Atlassian 3LO: rotating refresh tokens, `offline_access`, `accessible-resources`, token lifetimes.
- [ ] Microsoft identity platform delegated flow: PKCE, `offline_access`, tenant handling (`common` vs tenant id), refresh lifetime.
- [ ] NetSuite: PKCE-only public client, 7-day rotating refresh, `mcp` scope consent behavior.

## Options Explored

### Option A: Extend the Jira path in place (one more provider, one more channel each time)

Keep `JiraOAuthManager` as the template; copy it for Microsoft, add web routes next to the Jira ones, add a `/connect_o365` Telegram command.

✅ **Pros:** no migration; smallest first step; the production flow is untouched.

❌ **Cons:** N providers × M channels of security-sensitive code; keys stay channel-bound so connections never follow the user; two "needs auth" protocols remain; the web UI has nothing generic to list.

📊 **Effort:** Low per provider, unbounded overall.

---

### Option B: Generic connections core + channel protocol (recommended)

A `parrot.connections` module in core: `OAuthProviderRegistry` (descriptor per provider), `ConnectionManager` (start / callback / refresh / revoke, signed state + PKCE, single-flight refresh), `CredentialVault` (persistent per principal + ephemeral per session), `VaultCredentialResolver`, one `AuthorizationRequired` contract consumed by both `ToolManager` and the MCP client. Server adds `/oauth/callback/{provider}` and `/api/v1/connections`. Each channel implements a three-method `ConnectionChannel` protocol and subscribes to `connection.*` events. Jira is migrated onto it; web and Teams are added as consumers.

✅ **Pros:** one implementation; connections keyed by principal (connect once, use everywhere); UI can enumerate required providers before any tool call; adding a provider is a descriptor, adding a channel is three methods; matches the registry/decorator pattern used elsewhere.

❌ **Cons:** a production migration (Telegram) with a dual-read window; the vault scope question must be settled first; the callback → channel notification moves from a direct call to an event, which the Telegram bot must consume.

📊 **Effort:** Medium (core) + Medium (migration) + Medium (web) + Low–Medium (Teams).

📦 **Libraries / Tools:**

| Package | Purpose | Notes |
| --- | --- | --- |
| `httpx` | token endpoints, identity probes | already present |
| Redis (via existing client) | state nonces, refresh locks, ephemeral scope | already present |
| `navigator-eventbus` | `connection.*` events | already in the ecosystem; ⚠️ VERIFY current usage in parrot |
| `cryptography` (Fernet/AES-GCM) or KMS | vault encryption at rest | ⚠️ VERIFY what the existing vault does |
| Pydantic v2 | `OAuthProvider`, `Connection`, `TokenSet` models | project standard |

🔗 **Existing Code to Reuse (⚠️ VERIFY each):** `JiraOAuthManager` refresh/lock logic → generic manager; MCP `OAuthManager` PKCE → generic manager; `CredentialResolver` → keep the ABC, add the vault implementation; `AuthorizationRequired` + `ToolManager` catch → keep; `user_socket_manager` → web notifier.

---

### Option C: Delegate to navigator-auth as a broker (auth service owns tokens, parrot asks for them)

navigator-auth already runs an OAuth 2.1 authorization server for the opposite direction; extend it to also act as a *client* broker that holds third-party tokens per user and exposes `get_token(user, provider)`.

✅ **Pros:** tokens leave the agent platform entirely; one auth product owns all identity material; reusable by Fieldsync and other Navigator apps.

❌ **Cons:** cross-repo dependency on the critical path; ai-parrot OSS users without navigator-auth get nothing; the needs-auth protocol, channel notification and UI still have to be built in parrot anyway. Better as a future `CredentialVault` backend than as the design.

📊 **Effort:** High (two repos, release coupling).

---

### Option D: Front-end-driven flow (SPA does the OAuth, posts tokens to the API)

The Svelte app runs the authorization code flow itself (PKCE, public client) and uploads the resulting tokens to the backend vault.

✅ **Pros:** no server callback; simplest for the web channel alone.

❌ **Cons:** tokens transit the browser and the API boundary; impossible for Telegram/Teams (no SPA in the loop); confidential-client providers (Atlassian 3LO needs a client secret) cannot be done from the browser; violates "credentials never reach the frontend".

📊 **Effort:** Low for web, not applicable elsewhere — rejected.

## Recommendation

**Option B**, delivered as four specs (§8), with Option C kept open as a later `CredentialVault` backend rather than the design.

It is the only option that makes a connection a property of the *user* instead of the *channel*, which is what "connect your Office 365 from the UI and have the agent use it on Telegram" actually requires. It also collapses the three existing flows into one security-reviewed path, which matters more than the migration cost: every provider added on the current shape is one more copy of CSRF state, refresh rotation and token storage to audit.

Decisions already taken in discovery (not to be reopened by the proposal unless the code research contradicts them):

1. Core module in `ai-parrot` (`parrot.connections`), routes in `ai-parrot-server`, channel adapters in `ai-parrot-integrations`, UI in the AgentChat Svelte app.
2. Vault key = `(tenant, principal_id, provider, account)`; principal = navigator-auth user; channels map their external id to it.
3. One `AuthorizationRequired` contract for toolkits and MCP; `NeedsAuthorizationError` (if it exists) is retired.
4. One callback endpoint per provider on the server; completion is an eventbus event, never a direct call into a channel.
5. `ConnectionChannel` protocol = `principal()`, `present()`, `notify()` — nothing else is channel code.
6. Provider behavior lives in descriptors (`OAuthProviderRegistry`), not in subclasses.
7. Migration must be zero-reconnect for Telegram users (dual-read window).
8. The web and Teams consumers are separate specs; web first.

What is traded off: a production migration with a dual-read window, and an upfront spike on the vault's real semantics before the core spec can fix its data model.

## Feature Description

&#91;embedded content: target architecture · one core, two server routes, three channels, event-driven completion\]

Channels start a connection through the server API and get the auth link back; the user consents at the provider, which redirects to the single callback; `ConnectionManager` exchanges the code, writes the vault and publishes `connection.completed`, which every channel subscribes to. Toolkits and MCP servers never see the flow: they call `get_credentials(principal)` at tool-call time and either get a token or raise `AuthorizationRequired`.

### User-Facing Behavior

- **Web (AgentChat)**: a *Connections* panel lists every provider the user's available agents, toolkits and MCP servers require, with status (not connected / connected as `<display name>` / expired / revoked), granted scopes and expiry. *Connect* opens the provider consent in a popup; on return the card flips to connected without a reload. *Disconnect* revokes at the provider where supported and deletes the vault entry. When a tool call fails with `authorization_required` mid-chat, an inline card offers *Connect \<provider>* and the agent retries on completion.
- **Telegram**: `/connect <provider>` and `/disconnect <provider>` (the existing `/connect_jira` becomes an alias). The bot sends the link; the user completes it in the browser; the bot posts "Connected as \<display name>". Same `authorization_required` path mid-conversation.
- **MS Teams**: *Connect* as an Adaptive Card action; completion as a proactive message. Same protocol.
- A connection made on any channel is visible and usable on all channels for the same principal.

### Internal Behavior

1. **Provider descriptor** (`OAuthProvider`, Pydantic): `name`, `display_name`, `auth_url`, `token_url`, `revoke_url?`, `scopes_default`, `scopes_allowed`, `client_type` (confidential | public), `pkce` (required | optional | none), `refresh_policy` (rotating: bool, refresh\_lifetime?, access\_lifetime?), `identity_probe` (URL + JSON paths for account id and display name), `extra_authorize_params` (e.g. `prompt=consent`, `audience`), `post_exchange` hook name (e.g. Atlassian `accessible-resources` → `cloud_id`). Registered through `OAuthProviderRegistry` (decorator + YAML/config loading, same fractal pattern as `AgentRegistry`). Client id/secret come from `navconfig`, never from the descriptor file.
2. **`ConnectionManager`** (core, one instance per app): `start(provider, principal, channel, return_to?) -> AuthLink` (signed `state` = nonce + principal + channel + provider + optional `return_to`, stored in Redis with a 10-minute TTL; PKCE verifier stored alongside when the provider needs it); `complete(code, state) -> Connection` (verify nonce, exchange code, run identity probe and `post_exchange`, write the vault, publish `connection.completed`); `get_credentials(principal, provider, account?) -> TokenSet | None` (refresh when `expires_at` is near, single-flight per key via a Redis lock, always persist the newest refresh token); `revoke(principal, provider, account?)` (provider revoke when available, delete vault entry, publish `connection.revoked`); `list(principal) -> [ConnectionStatus]`.
3. **`CredentialVault`** (ABC + the real backend found in spike S1): two scopes — `persistent` (keyed `tenant/principal/provider/account`, encrypted at rest, survives logout) and `session` (keyed by session id, TTL = session, for BYO API keys). Store only what is needed: tokens, expiry, scopes, account id, display name, provider metadata (`cloud_id`, tenant id). Never the authorization code or the PKCE verifier beyond `complete()`.
4. **`VaultCredentialResolver(provider)`** implements the existing `CredentialResolver` ABC: `resolve(principal) -> TokenSet | None` calls `ConnectionManager.get_credentials`; `None` → the toolkit raises `AuthorizationRequired(provider, scopes, auth_url=manager.start(...))`. Toolkits and MCP servers declare `requires_auth = AuthRequirement(provider="atlassian", scopes=[...])` so `/connections` can enumerate requirements without executing anything.
5. **MCP client adapter**: the MCP session's `token_supplier` becomes `lambda ctx: resolver.resolve(ctx.principal)`; a `None` surfaces the same `AuthorizationRequired`. `user_id` is no longer bound at `add_*_mcp_server` time.
6. **`ToolManager`** keeps the single catch: `AuthorizationRequired` → `ToolResult(status="authorization_required", metadata={provider, auth_url, scopes, tool_name})`. The system prompt instruction for that status stays as in FEAT-083. After `connection.completed`, the per-session resolver cache for that principal/provider is invalidated so the next call succeeds without a re-register (hot-swap is no longer needed when tools are declared once and resolve at call time — ⚠️ confirm against how FEAT-083 registers Jira tools today).
7. **Server routes** (`ai-parrot-server`): `GET /oauth/callback/{provider}` (unauthenticated, state-verified; renders a success/failure page that `postMessage`s to the opener and closes); `GET /api/v1/connections` ; `POST /api/v1/connections/{provider}/start` (`return_to` optional) ; `GET /api/v1/connections/{provider}` ; `DELETE /api/v1/connections/{provider}`. Principal always from the authenticated session; never from the body.
8. **Events**: `connection.completed`, `connection.revoked`, `connection.refresh_failed` on `navigator-eventbus`, payload `{tenant, principal_id, provider, account, channel, display_name}`. Web subscriber → `user_socket_manager.send(principal, {type: "connection", ...})`. Telegram subscriber → `bot.send_message`. Teams subscriber → proactive message. Audit: each event is also appended to the `AuditLedger` (connect / disconnect / refresh failure), without token material.
9. **`ConnectionChannel`** protocol (integrations): `principal(ctx) -> Principal`, `present(principal, link) -> None`, `notify(principal, event) -> None`. That is the entire per-channel surface.

### Edge Cases & Error Handling

- **Rotating refresh race**: Redis lock per vault key around refresh; losers re-read the vault after the lock. Lock TTL < provider token-endpoint timeout.
- **Refresh failure (`invalid_grant`)**: mark the connection `expired`, publish `connection.refresh_failed`, raise `AuthorizationRequired` on next use so the user is asked to reconnect; never silently fall back to a system account (FEAT-083 fallback policy: explicit, never identity-switching).
- **State expired or replayed**: callback renders failure, no vault write, audit entry. Nonce is single-use.
- **Popup blocked**: the start response also returns the URL for a manual link; completion still arrives through the WS event, so the popup is not load-bearing.
- **Principal mismatch**: the callback's `state.principal` must equal the current web session's principal when a web session is present; otherwise fail (prevents binding a stranger's account to a logged-in user).
- **Multi-account / multi-site** (two Atlassian sites, two M365 tenants): v1 stores one `account` per provider; the vault key has the dimension so v2 can add selection.
- **Legacy key present, principal key absent** (migration window): read legacy, rewrite under principal, keep legacy until cutover date, then delete.
- **Provider down during `complete()`**: no partial write; the user can retry the link while the state is valid.
- **Tenant policy**: PBAC decides which providers a tenant/user may connect and which scopes are allowed; `start()` refuses outside the allowlist.

## Spec Split

`/sdd-spec` produces four specs from this brainstorm, not one. The risk profile of each is different and so is its exit criterion.

| Spec | Scope | Depends on | Production touch | Exit criterion |
| --- | --- | --- | --- | --- |
| **S-1 Connections core** | `parrot.connections` (registry, manager, vault ABC + backend, resolver, unified `AuthorizationRequired`, `ConnectionChannel` protocol, `AuthRequirement` declaration); ToolManager catch alignment; MCP `token_supplier` adapter; server routes `/oauth/callback/{provider}` + `/api/v1/connections`; `connection.*` events; provider `atlassian`; audit entries | Spike S1 (vault), S2 (PKCE reuse) | None — Telegram untouched | Full flow runs end to end with a test channel (CLI or the e2e harness `botmanager` target): start → consent → callback → vault → `get_credentials` → refresh → revoke; `authorization_required` round-trips through ToolManager and through an MCP tool |
| **S-2 Telegram migration** | Telegram implements `ConnectionChannel` + subscribes to events; `/connect <provider>` (alias `/connect_jira`); `JiraToolkit` on `VaultCredentialResolver`; retire `JiraOAuthManager`, Jira routes and direct bot call from the callback; legacy key dual-read + rewrite + cutover + delete | S-1 | **Yes** (in production) | Functional parity on Telegram; zero users reconnect (verified by counting legacy keys rewritten vs. new authorizations during the window); legacy code deleted after cutover |
| **S-3a Web (AgentChat)** | Web `ConnectionChannel` (`user_socket_manager` subscriber, WS event); Svelte `ConnectionsPanel` + `ConnectionCard` + `connections.svelte.ts` store; inline A2UI block for `authorization_required` with ActionRouter action; callback success page `postMessage`; provider `microsoft` (O365 delegated) as second real provider; retire `/api/o365/oauth/*` | S-1 (S-2 not required) | Only new surfaces | A user connects Jira and O365 from the panel and from an inline card; status updates without reload; a connection made on web is used on Telegram once S-2 is live |
| **S-3b MS Teams** | Teams `ConnectionChannel` (Adaptive Card action + proactive message); `aadObjectId` → principal mapping | S-1, and `TeamsHumanChannel` or the existing Bot Framework wrapper (⚠️ VERIFY which offers proactive messaging) | Only new surfaces | A Teams user connects a provider and the agent uses it in the same conversation |

Ordering: S-1 → S-2 and S-3a in parallel → S-3b. S-3a before S-2 is acceptable if the Telegram window needs more planning; nothing in S-3a reads legacy keys.

What S-1 deliberately leaves out: Microsoft and NetSuite descriptors (S-3a / later), multi-account selection (v2), navigator-auth as a vault backend (Option C, later), tenant-level admin UI for provider configuration (later).

## Impact & Integration

Paths are expectations for `/sdd-proposal` to confirm; none were read in this session.

| Affected component (expected) | Impact | Spec | Notes |
| --- | --- | --- | --- |
| `packages/ai-parrot/src/parrot/connections/` (new) | new | S-1 | registry, manager, vault, resolver, exceptions, channel protocol |
| `parrot/tools/manager.py` (`ToolManager.execute_tool`) | modifies | S-1 | single `AuthorizationRequired` catch; resolver cache invalidation on `connection.completed` |
| `parrot/tools/toolkit.py` (`AbstractToolkit`) | extends | S-1 | \`requires\_auth: AuthRequirement |
| MCP client session / mixin (`add_*_mcp_server`, `token_supplier`) | modifies | S-1 | call-time resolution; remove add-time `user_id` binding |
| `parrot/interfaces/` | extends | S-1 | Pydantic contracts (`OAuthProvider`, `TokenSet`, `Connection`, `AuthRequirement`) importable without extras |
| `ai-parrot-server` `BotManager` routes + auth exclusions | extends | S-1 | `/oauth/callback/{provider}` unauthenticated; `/api/v1/connections*` authenticated |
| `navigator-eventbus` wiring in server and integrations | extends | S-1, S-2, S-3 | `connection.*` topics; ⚠️ VERIFY current bus usage |
| `AuditLedger` | extends | S-1 | connect / disconnect / refresh\_failed entries |
| `navconfig` settings | extends | S-1 | per-provider `OAUTH_<PROVIDER>_CLIENT_ID/SECRET/REDIRECT_URI`; vault key material |
| `ai-parrot-tools` `JiraToolkit` | modifies | S-2 | `VaultCredentialResolver`; delete static-mode-only assumptions where FEAT-083 already generalized |
| `ai-parrot-integrations` Telegram wrapper (`/connect_jira`) | modifies | S-2 | `ConnectionChannel` impl; `/connect <provider>`; event subscriber |
| `JiraOAuthManager`, Jira callback routes, `BotManager.jira_oauth_manager` | removes (after cutover) | S-2 | dual-read window first |
| Redis keys `jira:oauth:<channel>:<user_id>` | migrates | S-2 | rewrite under principal key; delete at cutover |
| AgentChat Svelte app (TROC UI) | extends | S-3a | `ConnectionsPanel`, `ConnectionCard`, store, WS handler, A2UI block |
| `parrot.outputs` A2UI catalog + ActionRouter | extends | S-3a | `AuthRequiredBlock` (or reuse a card block) with a `connect` action |
| `ai-parrot-tools` O365 tool (`O365AuthMode.DELEGATED`) | modifies | S-3a | token source = vault resolver; retire `/api/o365/oauth/*` |
| MS Teams wrapper / `TeamsHumanChannel` | extends | S-3b | `ConnectionChannel` impl; proactive message subscriber |
| Docs (`docs/`) | extends | all | provider onboarding guide; channel adapter guide |

Breaking changes: none for public APIs in S-1; S-2 removes `JiraOAuthManager` (internal) after cutover. New runtime dependencies: none expected beyond what is present (`httpx`, Redis client, `cryptography` if the vault backend needs it — ⚠️ VERIFY).

## Does NOT Exist / Must Not Be Assumed

This list is the brainstorm's best knowledge. `/sdd-proposal` rewrites it after the code research; items may move to §3 if they turn out to exist.

**Named in this document but believed NOT to exist yet (do not import, do not cite):**

- ~~`parrot.connections`~~ — new package proposed here
- ~~`OAuthProviderRegistry`, `OAuthProvider`, `ConnectionManager`, `CredentialVault`, `VaultCredentialResolver`, `AuthRequirement`, `ConnectionChannel`~~ — proposed names, nothing to grep for
- ~~`/oauth/callback/{provider}`, `/api/v1/connections*`~~ — proposed routes
- ~~`connection.completed` / `connection.revoked` / `connection.refresh_failed`~~ — proposed event names
- ~~`WebOAuthManager`, `StateStore`, `TokenStore`, `NeedsAuthorizationError`~~ — designed in the NetSuite session; assumed never implemented until proven otherwise
- ~~a generic `/connect <provider>` Telegram command~~ — only a Jira-specific one is believed to exist
- ~~a Svelte Connections panel or A2UI auth block~~ — nothing shipped as far as this session knows
- ~~`requires_auth` on `AbstractToolkit`~~ — proposed
- ~~a principal-keyed vault entry for OAuth tokens~~ — Jira tokens are believed to be channel-keyed

**Must NOT be assumed about existing code until read:**

- That `CredentialResolver` is generic (it may be typed to `JiraTokenSet`).
- That `AuthorizationRequired` is defined in core rather than in the Jira package.
- That `ToolManager` already catches it (FEAT-083 specified it; implementation unconfirmed).
- That the MCP `OAuthManager` implements PKCE S256 or supports public clients.
- That `user_socket_manager` can target a single principal across several sockets.
- That `navigator-eventbus` is wired into the Telegram bot process.
- That the "session vault" encrypts at rest or persists beyond the session.
- That Telegram's `user_id` in `PermissionContext` is the platform principal rather than the raw Telegram id.
- That the O365 Svelte page from Oct 2025 shipped anywhere.

**Out of scope (exists, do not touch):**

- `OAuthRoutesMixin` on `HttpMCPServer` and the OAuth 2.1 AS in navigator-auth — that is parrot as a *resource server* for inbound clients (claude.ai → parrot), the opposite direction of this feature.

## Parallelism Assessment

- **Across specs**: S-1 is the critical path. S-2 and S-3a are independent once S-1's contracts land (`ConnectionChannel`, `AuthorizationRequired` shape, event payload, `/connections` response schema); they can run in separate worktrees. S-3b waits on the Teams channel work.
- **Inside S-1**: three lanes after the interface task (TASK-1 = `parrot.interfaces` contracts + `CredentialVault` ABC): (1) registry + manager + atlassian descriptor; (2) vault backend + resolver + ToolManager/MCP adapters; (3) server routes + events + audit. Lane 2 is gated by spike S1; lanes 1 and 3 are not.
- **Inside S-2**: sequential — dual-read must land before the Telegram channel switch, which must land before legacy deletion. One worktree.
- **Inside S-3a**: backend subscriber + A2UI block (parrot repo) and Svelte panel (TROC UI repo) in parallel against the `/connections` schema; the microsoft descriptor is a small independent task.
- **Cross-feature**: touches `ToolManager.execute_tool` and the MCP mixin — check against in-flight work on the inter-agent protocol (tool catalog in ToolManager) and FEAT-MCP-AGENT-METHODS; touches `BotManager` route setup — serialize with any other server-route feature.
- **Recommended isolation**: `mixed` — S-1 TASK-1 sequential in the feature worktree, lanes in individual worktrees after it; S-2 single worktree; S-3a two repos, one worktree each.

## Open Questions & Spike Gates

- [x] Single core with channel consumers (web, Telegram, Teams) — *Owner: Jesus*: yes
- [x] Spec count — *Owner: Jesus*: one brainstorm, four specs (core, Telegram migration, web, Teams)
- [x] Telegram login links to a platform user — *Owner: Jesus*: confirmed in conversation; exact mapping to be located in R1
- [ ] **Spike S1 (gates S-1 data model)**: what the session vault is — API, key shape, persistence, encryption. Decide: extend it with a persistent per-principal scope, or introduce `CredentialVault` with the existing vault as the ephemeral backend and a new Postgres/Redis-encrypted backend for persistent — *Owner: Jesus / sdd-proposal*
- [ ] **Spike S2 (gates S-1 lane 1)**: can the MCP `OAuthManager` PKCE/exchange code be lifted into `ConnectionManager`, or is a rewrite cleaner? — *Owner: sdd-proposal*
- [ ] **Spike S3 (gates S-3a)**: path from a callback HTTP request to one principal's WebSocket(s) via `user_socket_manager`; does the manager live in the same process as the callback route? — *Owner: sdd-proposal*
- [ ] **Spike S4 (gates S-2)**: is `navigator-eventbus` consumable from the autonomous Telegram bot process today, or does S-2 add that wiring? — *Owner: sdd-proposal*
- [ ] Vault persistent backend: Postgres table (asyncpg, encrypted columns) vs Redis without TTL. Proposal: Postgres for persistent, Redis for ephemeral and locks — *Owner: Jesus*
- [ ] Encryption key management for the vault: navconfig secret vs KMS envelope; rotation story — *Owner: Jesus*
- [ ] Does `requires_auth` belong on the toolkit class or per tool? Proposal: toolkit-level default, tool-level override — *Owner: Jesus*
- [ ] Hot-swap after auth (FEAT-083) vs declare-once + call-time resolve: if Jira tools are currently registered only after auth, S-2 changes registration to always-on — *Owner: sdd-proposal (R2)*
- [ ] Legacy key cutover window length and the metric to decide deletion — *Owner: Jesus*
- [ ] PBAC shape for provider/scope allowlists: policy in navigator-auth vs tenant config in parrot — *Owner: Jesus*
- [ ] Multi-account (two Atlassian sites, two M365 tenants) — v2 confirmed; v1 stores one `account` per provider — *Owner: Jesus*
- [ ] Teams dependency: `TeamsHumanChannel` spec first, or S-3b on the existing Bot Framework wrapper's proactive messaging? — *Owner: Jesus*
- [ ] Name of the feature/module: `parrot.connections` vs `parrot.auth.delegated` — *Owner: Jesus*

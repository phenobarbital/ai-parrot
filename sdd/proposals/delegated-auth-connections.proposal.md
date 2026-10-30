---
id: FEAT-773
title: Delegated Auth Connections — principal-keyed, channel-neutral OAuth2 3LO connections built on the existing parrot.auth stack
slug: delegated-auth-connections
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-10-30
  summary_oneline: Generic OAuth2 3LO connections core with principal-keyed vault, consumed by web, Telegram and Teams channels
overall_confidence: medium
base_branch: dev
projects: [ai-parrot, ai-parrot-server, ai-parrot-integrations, ai-parrot-tools, admin-ui, docs]
tags: [oauth2, connections, credentials, identity-vault, telegram, msteams, slack, web-ui]
research_state: sdd/state/FEAT-773/
created: 2026-10-30
updated: 2026-10-30
---

# FEAT-773 — Delegated Auth Connections (principal-keyed, channel-neutral OAuth2 3LO)

> **Mode**: enrichment
> **Confidence**: medium (localization and constraints high; three medium items and one low item are verification work for the spec, see §4)
> **Source**: `file: artifacts/Brainstorm Delegated Auth Connections (OAuth2 3LO core + channel consumers).md` (brainstorm, 2026-10-30, Option B recommended, 4-spec split)
> **Audit**: [`sdd/state/FEAT-773/`](../state/FEAT-773/)

> **Note on the id**: `FEAT-773` was reserved per FEAT-387 via `scripts/sdd/reserve_ids.py` against `sdd/tasks/.id_ledger.json` on 2026-10-30.

> **What this document is.** The source brainstorm forbade `/sdd-spec` from trusting any of its code claims and mandated that `/sdd-proposal` rewrite its §3 ("Prior Work & Claimed References") as verified references and its §10 ("Does NOT Exist") as the real absence list. §2.4 and §3.4 below are those rewrites. The research found that **most of the proposed "connections core" already exists in `parrot.auth`**; the feature is therefore re-scoped from "build `parrot.connections`" to "make the existing stack principal-keyed and channel-neutral" (U4 resolved: evolve in place).

---

## 0. Origin

The full source is at `sdd/state/FEAT-773/source.md` (338 lines). Excerpt of the problem statement:

> Users cannot connect their own Office 365, Jira or any other OAuth2 (3LO) service from the AgentChat UI, and the delegated-auth logic that does exist is implemented three times, each tied to one channel. […] 1. No single place to add a provider or a channel. 2. Connections are channel-bound. A Jira account connected from Telegram is invisible to the same user on the web, because the vault key carries the channel, not the platform principal. 3. Two "needs auth" protocols. Toolkits raise `AuthorizationRequired`; the MCP path was designed around `NeedsAuthorizationError`.

**Initial signals** (extracted, not interpreted):
- Verbs: "connect", "add", "implement", "migrate", "retire", "verify" → additive, feature-shaped (enrichment)
- Named entities: `JiraOAuthManager`, `CredentialResolver`, `AuthorizationRequired`, `OAuthManager`, `WebOAuthManager`, `NeedsAuthorizationError`, `O365AuthMode`, `user_socket_manager`, `navigator-eventbus`, `PermissionContext`, `add_oauth_mcp_server`, `/connect_jira`, "session vault"
- Components: core (`ai-parrot`), server, integrations, tools, Svelte UI
- Acceptance criteria provided: yes — per-spec exit criteria in the brainstorm's §8 (S-1 … S-3b)
- Research mandate provided: yes — R1 (vault/identity), R2 (Jira path), R3 (MCP), R4 (server), R5 (UI), R6 (external provider facts)

---

## 1. Synthesis Summary

The brainstorm asks for one generic OAuth2 3LO "connections" implementation keyed by platform principal, consumed by web, Telegram and MS Teams, with one needs-auth contract and event-driven completion. The codebase already contains the generic engine (`parrot/auth/oauth2_base.py::AbstractOAuth2Manager` — PKCE S256, Redis nonce state, vault+Redis persistence, lock-protected rotating refresh), the provider registry (`parrot/auth/oauth2/registry.py::OAuth2ProviderRegistry`), a web connections service and its API contracts (`parrot/auth/oauth2/service.py::IntegrationsService`, `models.py`), a generic per-provider callback (`parrot/auth/oauth2_routes.py::make_oauth2_callback`), a per-user credential broker (`parrot/auth/broker/core.py::CredentialBroker`), a principal-keyed durable store for Jira (navigator-auth Identity Vault via `services/identity_credential_sink.py`, decided 2026-10-23), and channel commands plus notifiers for Telegram, Slack **and** Teams. What is genuinely missing is the *principal keying* (every hot cache and vault name still embeds the channel), the Jira manager sitting outside the generic engine, a user-level (not agent-scoped, not web-only) connections view, a single needs-auth conversion for both `AuthorizationRequired` and `CredentialRequired`, and a notification path that does not call channel code from the callback. With the five decisions taken in §5 (Navigator `user_id` as primary key with OID/email as secondary, full reversal of FEAT-144's per-agent model, forced re-connect for unlinked Telegram users, evolve `parrot.auth.oauth2` in place, notifier registry plus publish-only bus), the recommendation is to proceed to `/sdd-spec` with the four-spec split re-mapped onto the existing modules (§3).

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-773/findings/F001–F076` (85 lane digests merged to 76; originals in `findings/.audit/`). 282 citations were probed by `sdd-contract-probe` at HEAD `5fa785952`: 268 verified, 2 stale (tagged in F030/F076), 0 missing — see `citation_checks.md`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/auth/oauth2_base.py` | `AbstractOAuth2Manager` | 89-623 | generic 3LO engine: PKCE S256 pair, Redis nonce `oauth2:{p}:nonce:{n}` (10 min) carrying channel/user_id/extra, `handle_callback` → `_persist_token` (vault `oauth2_{p}_{c}_{u}` + Redis `oauth2:{p}:{c}:{u}` 90 d), `get_valid_token` cache→vault→locked `_refresh_tokens`, `revoke`, `setup()` mounts the callback; 4 abstract hooks | F044, F071 |
| 2 | `packages/ai-parrot/src/parrot/auth/jira_oauth.py` | `JiraOAuthManager`, `CredentialSink` | 231-800 | Jira-only manager: `jira:oauth:{channel}:{user_id}` (90 d), `jira:nonce:*`, `lock:jira:refresh:*`, no PKCE, `accessible-resources`→`cloud_id`; `CredentialSink` Protocol (`persist`, `persist_minted`) for the durable owner; docstring says it "intentionally stays untouched" by the generic module | F002, F059, F071 |
| 3 | `packages/ai-parrot/src/parrot/auth/o365_oauth.py` | `O365OAuthManager` | 55-165 | the one `AbstractOAuth2Manager` subclass (tenant-templated endpoints, `use_pkce=True`, `prompt=select_account`, Graph `/me` identity) | F041, F061 |
| 4 | `packages/ai-parrot/src/parrot/auth/oauth2/registry.py` | `OAuth2Provider`, `OAuth2ProviderRegistry` | 20-126 | descriptor ABC (`provider_id`, `display_name`, `icon`, `default_scopes`, `pbac_action_namespace`, `manager`, `toolkit_factory`) + singleton registry (`register/get/all`) | F037, F055, F007 |
| 5 | `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | `IntegrationsService` | 74-482 | web "ConnectionManager": `list_for_user(user_id, agent_id, request)`, `start_connect(user_id, agent_id, provider_id, return_origin)` (channel `"web"` hard-coded, origin allowlist), `confirm_enable`, `disconnect`, `persist_credential`; status probe = Identity Vault for jira, `VaultTokenSync` otherwise; PBAC fail-closed | F038, F075 |
| 6 | `packages/ai-parrot/src/parrot/auth/oauth2/models.py` | `IntegrationDescriptor`, `ConnectInitResponse`, `AuthRequiredEnvelope`, `UsersIntegrationRow` | 21-180 | the API contracts the brainstorm re-proposes as `Connection`/`ConnectionStatus`; `UsersIntegrationRow(user_id, provider, channel, status, account_id, display_name, scopes, cloud_id, …)` is principal-keyed metadata with channel as attribute | F036 |
| 7 | `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py` | `upsert_users_integration`, `upsert_user_agent_toolkit` | 42-191 | DocumentDB `users_integrations` keyed `(user_id, provider)` (metadata, no tokens) + `user_agent_toolkits` keyed `(user_id, agent_id, toolkit_id)` | F039 |
| 8 | `packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py` | `MCPOAuth2Provider` | 36-125 | MCP servers enumerate in the same registry as `mcp:{server_name}` (`toolkit_factory` → None) | F045 |
| 9 | `packages/ai-parrot/src/parrot/auth/oauth2_routes.py` | `make_oauth2_callback`, `setup_oauth2_routes`, `_handle_web_callback`, `handle_mcp_oauth2_callback` | 123-434 | generic per-provider callback `/api/auth/oauth2/{provider}/callback`, appended to `navigator_auth.conf.exclude_list`; web branch persists via `IntegrationsService.persist_credential` and renders `templates/web_oauth_success.html` (postMessage, validated `return_origin`); A2A resume hook; separate MCP callback | F005, F070, F064 |
| 10 | `packages/ai-parrot/src/parrot/auth/routes.py` | `jira_oauth_callback`, `setup_jira_oauth_routes` | 232-351 | legacy Jira-only `/api/auth/jira/callback`: dispatches on `state_payload["channel"]` ∈ {web, slack, msteams, telegram} with **direct in-process** notifier calls (`app['jira_oauth_notifier']`, `telegram_jira_session_stamper`, Slack/Teams handlers); core lazily imports integrations modules | F024, F073, F064 |
| 11 | `packages/ai-parrot/src/parrot/auth/broker/core.py` | `CredentialBroker` | 32-215 | FEAT-264 `provider_id → (resolver, auth_kind)` registry; `resolve(provider, channel, user_id)` → `ResolvedCredential | NeedsAuth`, fails closed, appends to the canonical audit ledger; no start/callback/refresh/revoke | F006, F054, F058 |
| 12 | `packages/ai-parrot/src/parrot/auth/credentials.py` | `CredentialResolver`, `OAuthCredentialResolver`, `NeedsAuth`, `CredentialRequired` | 82-202 | generic `(channel, user_id)` resolver ABC (not Jira-typed); FEAT-264 signal model + exception (`provider, auth_url, auth_kind, user_code, verification_uri, expires_in`) | F001 |
| 13 | `packages/ai-parrot/src/parrot/auth/exceptions.py` | `AuthorizationRequired` | 12-47 | FEAT-107 signal `(tool_name, message, auth_url, provider, scopes)` | F003 |
| 14 | `packages/ai-parrot/src/parrot/tools/manager.py` | `ToolManager.execute_tool` | 2273-2290 | catches `AuthorizationRequired` → `ToolResult(success=False, status="authorization_required", metadata={auth_url, provider, scopes, tool_name})`; **does not** catch `CredentialRequired` | F004 |
| 15 | `packages/ai-parrot/src/parrot/tools/abstract.py` | `AbstractTool.execute`, `current_credential` | 39-48, 1012-1045, 1182-1197 | FEAT-264 broker seam (`credential_provider` + `_broker`, fails closed without `_cred_user_id`) raising `CredentialRequired` before `_pre_execute`; both exceptions re-raised | F004, F033 |
| 16 | `packages/ai-parrot/src/parrot/tools/toolkit.py` | `AbstractToolkit.credential_provider`, `_pre_execute`, `_post_execute` | 315-331, 491-506, 717-718 | toolkit-level `credential_provider` (provider id only, propagated to generated tools); `requires_auth` does not exist | F033 |
| 17 | `packages/ai-parrot/src/parrot/tools/jira_connect_tool.py` | `JiraConnectTool._execute` | 70-92 | FEAT-083 placeholder tool hot-swapped once Jira tokens land (AgentTalk) — still live | F004 |
| 18 | `packages/ai-parrot/src/parrot/auth/identity.py` | `CanonicalIdentityMapper` | 57-100 | broker principal: Entra OID → lower-cased email → None (fail closed); **not** the Navigator bigint `user_id` | F042, F072 |
| 19 | `packages/ai-parrot/src/parrot/auth/permission.py` | `UserSession`, `PermissionContext`, `build_principal_context` | 21-205 | `channel` field exists; `user_id` is the raw channel id on Telegram and the session user on web | F014, F048 |
| 20 | `packages/ai-parrot-server/src/parrot/services/identity_mapping.py` | `IdentityMappingService.upsert_identity` | 44-268 | writes navigator-auth `auth.user_identities` (PK `(user_id, uid)`, partial UNIQUE `(user_id, auth_provider, provider_user_id)`): channel rows telegram/msteams/slack → bigint `nav_user_id` via raw SQL, token-bearing `jira` row via `IdentityStore.save_linked_identity` | F012, F056, F062 |
| 21 | `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py` | `IdentityVaultCredentialSink` | 24-171 | FEAT-735 durable Jira owner: `persist_minted` (link; resolves `nav_user_id` from `state.extra` or `find_user_by_provider_account`), `persist` (refresh → `update_tokens`) | F013, F059 |
| 22 | `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | `_build_jira_credential_sink` | 81-107, 372, 931 | wires the sink into both `JiraOAuthManager` construction sites (Protocol injection keeps core free of server imports) | F030 (probe-corrected) |
| 23 | `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py` | `VaultTokenSync`, `_synth_session_uuid` | 69-239 | the "session vault": navigator-session `SessionVault` made per-user by a deterministic synthetic `session_uuid`, encrypted, principal-keyed flat `{provider}:{field}`; serves fireflies/workiq/entra/o365; Jira retired | F010, F057 |
| 24 | `packages/ai-parrot/src/parrot/security/vault_utils.py` | `store_vault_credential`, `oauth2_vault_name`, `set_vault_credential_store` | 43-211 | third store: AES-GCM envelope v2 in DocumentDB/Postgres `user_credentials`; `oauth2_vault_name(provider, channel, user_id)` embeds the channel | F011, F057 |
| 25 | `packages/ai-parrot/src/parrot/mcp/oauth.py` | `TokenStore`, `RedisTokenStore`, `VaultTokenStore`, `NetSuiteM2MAuth` | 22-280 | fourth token store shape: `(user_id, server_name)`, Redis `mcp:oauth:{server}:{user_id}` | F019 |
| 26 | `packages/ai-parrot/src/parrot/mcp/client.py` | `MCPClientConfig`, `get_headers` | 174-290 | `token_supplier: Callable[[], Optional[str]]` (zero-arg), `header_provider(ReadonlyContext)` per call, `user_id` field bound on the config | F017, F063 |
| 27 | `packages/ai-parrot/src/parrot/mcp/integration.py` | `add_oauth_mcp_server`, `add_netsuite_mcp_server` | 1394-1442, 1706-1740 | add-time `user_id` binding confirmed | F018 |
| 28 | `packages/ai-parrot/src/parrot/mcp/oauth2_config.py` | `MCPOAuth2Config`, `MCPOAuth2Preset` | 27-204 | descriptor-as-data already used for MCP (public client / PKCE declared, presets `netsuite`, `fireflies`) | F020 |
| 29 | `packages/ai-parrot-server/src/parrot/handlers/integrations.py` | `IntegrationsHandler._get_user_id`, `_post_connect` | 43-160 | `/api/v1/agents/integrations/{agent_id}[/{provider}/connect|enable|DELETE]`; principal from `request['user_id']`/session, never the body; `return_origin` allowlist | F040, F024 |
| 30 | `packages/ai-parrot-server/src/parrot/manager/manager.py` | `BotManager._register_oauth2_providers`, `setup` | 2388, 2459-2472, 2789-2807 | registers only `JiraOAuth2Provider` at startup (boot warning when `jira_oauth_manager` unset); mounts `IntegrationsHandler`; O365 registration left to the host app | F016 |
| 31 | `packages/ai-parrot-server/src/parrot/handlers/user.py` | `UserSocketManager.send_direct_message`, `_validate_token` | 63-414 | per-process `user_sockets[username]` from JWT; Redis for user-info + channel pubsub; no cross-process send-to-user primitive | F021 |
| 32 | `packages/ai-parrot-server/src/parrot/handlers/agent.py` | AgentTalk handler | 1916-1927 | catches `AuthorizationRequired` → `AuthRequiredEnvelope` JSON (HTTP 200); `CredentialRequired` caught nowhere in server handlers | F047 |
| 33 | `packages/ai-parrot/src/parrot/observability/fanout.py` | `setup_event_fanout`, `_validate_bus` | 74-121 | sanctioned bus pattern: `EventBus(transport='streams', publish_only=True)`, redacted payloads, consumers outside parrot | F023, F066 |
| 34 | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py` | `connect_jira_handler`, `register_jira_commands`, `TelegramOAuthNotifier` | 50-233 | `/connect_jira`, `/disconnect_jira`, `/jira_status` with raw `telegram_id`; notifier invoked directly by the callback route | F015 |
| 35 | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py` | `JiraPostAuthProvider.build_auth_url`, `_write_identity_records` | 38-252 | combined `/login`+Jira flow: embeds `nav_user_id` in `extra_state`, writes `telegram` + `jira` identity rows; no longer writes tokens (FEAT-735) | F035, F073, F030 |
| 36 | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | `TelegramAgentWrapper._build_permission_context` | 1280-1300 | `PermissionContext(channel="telegram", user_id=telegram_id)` — the channel-bound key | F048, F002 |
| 37 | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py` | `BasicAuthStrategy`, `TelegramUserSession` | 477-495 | `/login` sets `nav_user_id` on the in-memory session; link persisted only through the combined Jira flow | F043, F035 |
| 38 | `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py` | `handle_msteams_jira_callback`, `MSTeamsOAuthNotifier` | 89-305 | Teams proactive notification (`ConversationReference` in `extra_state`) + `nav_user_id`-guarded identity write already exist | F035, F067 |
| 39 | `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/oauth2_providers.py` | `OAUTH2_PROVIDERS`, `OAuth2ProviderConfig` | 16-44 | login-IdP catalog (google) for channel sign-in — a *different* registry | F009, F055 |
| 40 | `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | `JiraToolkit._pre_execute` | 927-1345 | `oauth2_3lo` via `CredentialResolver` in `_pre_execute`, client cache `"{channel}:{user_id}" → (client, token_hash)`; **no** `credential_provider` → bypasses the broker seam | F029 |
| 41 | `packages/ai-parrot-tools/src/parrot_tools/o365/oauth_toolkit.py` | `Office365Toolkit` | 37-150 | delegated 3LO toolkit with `credential_provider="o365"` and legacy `_pre_execute` fallback raising `AuthorizationRequired` | F025 |
| 42 | `packages/ai-parrot-tools/src/parrot_tools/o365/base.py` | `O365AuthMode` | 22-26 | `DIRECT/OBO/DELEGATED(+CACHED)`; `DELEGATED` is interactive MSAL, not the vault path | F026 |
| 43 | `packages/ai-parrot-server/ui/src/lib/components/agents/integrations/IntegrationsMenu.svelte` (+ `ConnectIntegrationPill.svelte`, `ui/src/lib/oauth/popup.ts`, `ui/src/lib/api/integrations.ts`) | `IntegrationsMenu`, `ConnectIntegrationPill`, `awaitOAuthCallback` | 1-167 | admin UI already ships per-agent integrations menu, inline pill for `auth_required`, popup helper; no WS push, no cross-channel view, no auto-retry | F027, F046, F065 |
| 44 | `packages/ai-parrot/src/parrot/security/audit_ledger.py` | `AuditLedger` | 80-296 | canonical KMS-signed ledger (used by the broker); legacy `parrot/auth/audit.py` still imported once by `msagentsdk/wrapper.py` | F034, F076 |
| 45 | `docs/auth/jira-credential-ownership.md` | — | 1-80 | FEAT-735 decision record (2026-10-23) | F031 |

### 2.2 Constraints Discovered

- **The Jira credential already has a principal-keyed durable owner.** navigator-auth's Identity Vault (`auth.user_identities`, keyed by Navigator `user_id` + provider + account) owns the grant; Redis `jira:oauth:{channel}:{user_id}` is the live tool path (G4: no per-call Postgres decrypt). Decided 2026-10-23 (FEAT-735), one week before this research.
  *Implication*: build the principal-keyed vault **on** the Identity Vault; do not add a competing `CredentialVault`. The migration concerns the hot cache key and the generic manager's vault names, not the durable store.
  *Evidence*: F031, F059, F013, F049, F050

- **Core must not import server; server injects via Protocol.** `CredentialSink` on `JiraOAuthManager` is the sanctioned shape; `parrot/auth/routes.py` lazily importing integrations is existing debt.
  *Implication*: channel notification goes behind an in-core Protocol/registry; the Jira route's imports are removed, not copied.
  *Evidence*: F002, F059, F024, F030

- **`auth.user_identities.user_id` is a bigint FK; the Navigator id travels under its own `nav_user_id` state key; `state['user_id']` is the channel id.** The table's partial unique index already allows several accounts per provider per user.
  *Implication*: the `(principal, provider, account)` key matches the schema; the risk is principal *resolution*, never storage.
  *Evidence*: F012, F056, F062, F035

- **Two principal notions coexist.** `CanonicalIdentityMapper` (Entra OID → email) for broker/A2A/MSAgentSDK vs Navigator bigint `user_id` for identity/Telegram/Teams/web; FEAT-729 proved `provider_user_id == oid` at Teams login.
  *Implication*: resolved by U1 — Navigator `user_id` primary, OID/email secondary column.
  *Evidence*: F042, F072, F060

- **On Telegram the principal exists only after `/login`.** `PermissionContext.user_id` is the raw `telegram_id`; the link is session-held and persisted to `auth.user_identities` only as a side effect of the combined Jira flow.
  *Implication*: zero-reconnect holds only for linked users; U3 resolved as forced re-connect for the rest.
  *Evidence*: F048, F043, F035, F056

- **FEAT-144 recorded cross-channel credential sharing as a non-goal and chose per-(user, agent, toolkit) enablement.** `IntegrationsService` hard-codes `channel="web"` and is agent-scoped.
  *Implication*: this feature reverses a recorded product decision; U2 resolved as full reversal (one connection, all agents, all channels). The spec must state the reversal and retire `user_agent_toolkits`.
  *Evidence*: F065, F038, F075, F039

- **Every store still embeds the channel.** `AbstractOAuth2Manager` keys `oauth2:{p}:{c}:{u}` / vault `oauth2_{p}_{c}_{u}`; `JiraOAuthManager` keys `jira:oauth:{c}:{u}`; JiraToolkit's client cache is `{channel}:{user_id}`.
  *Implication*: re-keying is one base-class change plus the Jira migration onto it — not a new manager.
  *Evidence*: F044, F071, F011, F002, F029

- **Completion is a direct in-process dispatch.** The Jira callback branches on `state.channel` and calls notifiers held on the same `app`; `navigator-eventbus` is a live dependency used publish-only (Streams) and **no** channel wrapper subscribes to any topic.
  *Implication*: U5 resolved — notifier registry is the delivery path; bus publication is additive.
  *Evidence*: F024, F073, F064, F022, F023, F066

- **`UserSocketManager` is process-local and keyed by JWT username.** Redis pubsub exists for channels only.
  *Implication*: WS push of `connection.completed` needs a username↔principal map and a per-user Redis channel; popup `postMessage` remains load-bearing.
  *Evidence*: F021

- **Two needs-auth signals.** `AuthorizationRequired` → `ToolResult(status="authorization_required", metadata={auth_url, provider, scopes, tool_name})` in `ToolManager` and → `AuthRequiredEnvelope` in AgentTalk; `CredentialRequired` (broker seam) bubbles uncaught.
  *Implication*: unification is a `ToolManager` catch producing the same `ToolResult`, then retiring one raise site; both classes live in core.
  *Evidence*: F004, F047, F001, F003

- **JiraToolkit bypasses the broker seam** (no `credential_provider`) and keeps the hot-swap placeholder; `Office365Toolkit` is already on the seam.
  *Implication*: declaring `credential_provider="jira"` removes the hot-swap and aligns both toolkits.
  *Evidence*: F029, F004, F025

- **MCP binds the user at add-time** (`MCPClientConfig.user_id`, `add_oauth_mcp_server(user_id=…)`), although per-call injection via `header_provider(ReadonlyContext)` exists; the MCP auth surface has had zero commits in 120 days.
  *Implication*: small, isolated change with no concurrent-edit risk.
  *Evidence*: F017, F018, F063, F052

- **The web API already does principal-from-session and origin allowlisting; a generic callback with exclude_list, postMessage and A2A resume exists.**
  *Implication*: brainstorm items 7 (routes) and the callback are mostly present; the delta is a user-level listing and Jira route retirement.
  *Evidence*: F040, F005, F070, F064

- **Name collisions.** `OAuth2ProviderRegistry` (core) vs `OAUTH2_PROVIDERS` (integrations login catalog) vs the proposed `OAuthProviderRegistry`; two `setup_oauth2_routes` (core tool-credential callback vs Telegram WebApp login callback).
  *Implication*: reuse existing names; no third registry.
  *Evidence*: F055, F009, F048

- **O365 has three store paths and no `/api/o365/oauth/*`.** 3LO browser flow → `vault_utils` `oauth2_o365_web_{user_id}`; device-code CLI → `VaultTokenSync` `o365:*`; Gen-1 REST sessions deleted (FEAT-266).
  *Implication*: the "microsoft" descriptor already exists; S-3a's O365 work is store consolidation.
  *Evidence*: F061, F032, F024, F025, F041

- **Teams and Slack are already channels.** FEAT-729 user-auth lane (`MSTeamsAuthStrategy`, `TokenExchangeClient`, `/login`, `aad_object_id ↔ nav_user_id`) and FEAT-225 `/connect_jira` + DM/proactive notifiers; Slack first-link still has no owner.
  *Implication*: S-3b does not depend on `TeamsHumanChannel`; Slack is a fourth channel in scope.
  *Evidence*: F060, F035, F067, F031

- **Audit goes to `parrot.security.audit_ledger`**; legacy `parrot/auth/audit.py` still imported once (pre-existing debt).
  *Evidence*: F034, F076

- **Provider behaviour is code today** (manager subclass + metadata subclass); only MCP has descriptor-as-data; the broker has a YAML manifest loader for per-agent credential configs.
  *Implication*: "provider behaviour is data" is a genuine new capability layered on the manager hooks.
  *Evidence*: F037, F020, F058, F008

### 2.3 Recent History (Relevant)

Commits in the last 120 days on the affected paths (git lane, F049–F053):

| When | Scope | What landed | Why it matters |
|------|-------|-------------|----------------|
| 2026-10-23 | `parrot/auth/`, `server/services/` | **FEAT-735** services-vault-token-sync-tech-debt (TASK-4668–4672): `CredentialSink` Protocol on `JiraOAuthManager`, `IdentityVaultCredentialSink`, `IntegrationsService` reads the Identity Vault for jira, Session-Vault `jira:*` writer removed, `docs/auth/jira-credential-ownership.md` | the ownership decision this feature must build on |
| 2026-10-22/23 | `parrot/auth/token_exchange.py`, `msteams/` | **FEAT-729** msteams-user-auth-lane (TASK-4659–4667): `TokenExchangeClient`, `MSTeamsAuthStrategy`, `/login /logout /whoami`, `nav_user_id` in Teams OAuth state, bigint guard in `IdentityMappingService` | Teams principal mapping exists |
| 2026-10-16/17 | `parrot/auth/jira_oauth.py` | TASK-4418 3LO helpers extracted (`exchange_code`, `refresh_access_token`, `fetch_accessible_resources`, `fetch_myself`) | reusable pieces for porting Jira onto the generic manager |
| 2026-09-16 | `security/`, `oauth2/service.py` | vault-crypto-hardening: envelope v2, `IntegrationDescriptor.status` (connected / disconnected / needs_reconnect) | status model already exists |
| 2026-08-31 | `telegram/auth.py`, `login_multi.html` | Telegram multi-provider login page | the channel→principal link UI on Telegram |
| 2026-08-27 | `parrot/auth/broker` | BYOK per-user LLM keys resolver | broker in active use |
| 2026-07-20 | `telegram/wrapper.py` | "wip: event bus" (+9/−5) | eventbus wiring in Telegram exists only as WIP |
| — | `mcp/client.py`, `mcp/oauth2_config.py` | **zero commits**; last touch 2026-06-29 (TASK-1676) | MCP surface frozen; no concurrent-edit risk |
| 2026-07-03 → 09-26 | `parrot_tools/o365/` | SharePoint/contracts delta work only | O365 tool auth surface quiet |

No commit in the window created `parrot.connections`, a `ConnectionManager`, an `OAuthProviderRegistry` or `connection.*` events (F049).

### 2.4 Brainstorm §3 — Verified Codebase References (the rewrite the source requested)

| Claimed artifact (brainstorm §3) | Verdict | Where it actually is (grep anchor) | Evidence |
|---|---|---|---|
| `JiraOAuthManager` (state nonce in Redis, exchange, rotating refresh with lock, `accessible-resources` → `cloud_id`) | **EXISTS — in core**, not integrations/tools | `parrot/auth/jira_oauth.py` — `class JiraOAuthManager`, `_TOKEN_KEY_PREFIX = "jira:oauth"`, `_refresh_tokens`, `handle_callback`; plus `class CredentialSink(Protocol)` | F002 |
| `jira_oauth_manager` on `BotManager` (boot warning) | **EXISTS** — read from `app.get("jira_oauth_manager")` in `BotManager._register_oauth2_providers`; constructed by the integrations manager, not BotManager | `manager/manager.py` — `def _register_oauth2_providers`; `integrations/manager.py` — `JiraOAuthManager(` ×2 | F016, F030 |
| Jira OAuth callback routes | **EXISTS** — `GET /api/auth/jira/callback`, excluded via `navigator_auth.conf.exclude_list`, success/error templates | `parrot/auth/routes.py` — `def setup_jira_oauth_routes`, `async def jira_oauth_callback`; `parrot/auth/templates/web_oauth_success.html` | F024, F073, F064 |
| `/connect_jira` Telegram command | **EXISTS** as `/connect_jira`, `/disconnect_jira`, `/jira_status` (not `/connect`); also `/connect_office365`; Slack and Teams have the same Jira commands | `telegram/jira_commands.py` — `def register_jira_commands`; `telegram/office365_commands.py`; `slack/commands/jira_commands.py`; `msteams/commands/jira_commands.py` | F015, F043, F067 |
| `CredentialResolver` ABC + `OAuthCredentialResolver` + `StaticCredentialResolver` | **EXISTS — generic** `(channel, user_id)`, duck-typed manager | `parrot/auth/credentials.py` — `class CredentialResolver(ABC)`, `class OAuthCredentialResolver` | F001 |
| `AuthorizationRequired` → `ToolResult(status="authorization_required", metadata.auth_url)` in `ToolManager.execute_tool` | **EXISTS** — status literal and metadata `{auth_url, provider, scopes, tool_name}` confirmed; defined in core `parrot/auth/exceptions.py` | `parrot/tools/manager.py` — `except AuthorizationRequired as auth_exc` | F004, F003 |
| `AbstractToolkit._pre_execute` / `_post_execute` | **EXISTS** | `parrot/tools/toolkit.py` — `async def _pre_execute(self, tool_name: str, /, **kwargs)` | F033 |
| `PermissionContext.channel` | **EXISTS** | `parrot/auth/permission.py` — `class PermissionContext` | F014 |
| AgentTalk hot-swap of Jira tools after auth | **EXISTS** — placeholder `JiraConnectTool` + `hotswap_to_full_toolkit` | `parrot/tools/jira_connect_tool.py` | F004 |
| MCP `OAuthManager` (local callback `127.0.0.1:8765`, PKCE) | **REMOVED** (FEAT-262 TASK-1665); replaced by `MCPOAuth2Config` + presets + `oauth2_state.py` + `handle_mcp_oauth2_callback` | `parrot/mcp/oauth2_config.py` — `class MCPOAuth2Config`; `parrot/auth/oauth2_routes.py` — `async def handle_mcp_oauth2_callback` | F019, F020, F063, F052 |
| `WebOAuthManager`, `StateStore`, `TokenStore`, `NeedsAuthorizationError` | **3 of 4 ABSENT**; only `TokenStore` exists (`InMemory`/`Redis`/`Vault` backends) | `parrot/mcp/oauth.py` — `class TokenStore` | F019 |
| `add_oauth_mcp_server(name, url, client_id, client_secret, auth_url, token_url, scopes, user_id)` | **EXISTS** with that signature plus `oauth2=`; `user_id` bound at add-time | `parrot/mcp/integration.py` — `async def add_oauth_mcp_server` | F018 |
| `O365AuthMode` (`DIRECT`, `OBO`, `DELEGATED`) | **EXISTS** (+`CACHED`); `DELEGATED` = interactive MSAL. The vault-backed 3LO path is `Office365Toolkit` + `O365OAuthManager` | `parrot_tools/o365/base.py` — `class O365AuthMode`; `parrot_tools/o365/oauth_toolkit.py`; `parrot/auth/o365_oauth.py` | F026, F025, F041 |
| Svelte page for O365 (`/api/o365/oauth/initiate`, `/status/{user_id}`) | **DOES NOT EXIST** in this repo. What shipped: popup → `POST /api/v1/agents/integrations/{agent}/o365/connect` → `GET /api/auth/oauth2/o365/callback` (docs/integrations/office365-oauth2.md); Gen-1 REST sessions deleted | `handlers/integrations.py`; `docs/integrations/office365-oauth2.md` | F024, F032, F061 |
| `user_socket_manager` on `BotManager` | **EXISTS** (`app['user_socket_manager']`, read on startup) — `send_direct_message(to_username)` is process-local | `handlers/user.py` — `class UserSocketManager`, `async def send_direct_message` | F016, F021 |
| Per-session `ToolManager` + session credentials | **PARTIAL** — per-agent `user_agent_toolkits` enablement + cold-session hydration (FEAT-144); the broker is set on `ToolManager` via `set_broker` | `parrot/auth/oauth2/persistence.py`; FEAT-264 spec | F039, F065, F058 |
| "Session vault" per user | **EXISTS** — navigator-session `SessionVault` made per-user by a deterministic `session_uuid` (`VaultTokenSync`), encrypted, persistent; plus `vault_utils` DocumentDB/Postgres store and the navigator-auth Identity Vault | `services/vault_token_sync.py` — `def _synth_session_uuid`; `security/vault_utils.py` — `def oauth2_vault_name` | F010, F011, F057, F068 |
| `OAuthRoutesMixin` on `HttpMCPServer`; OAuth 2.1 AS in navigator-auth | not researched (out of scope per the brainstorm; opposite direction) | — | — |
| `TeamsHumanChannel` spec | **MOOT** — Teams already has a user-auth lane (FEAT-729) and proactive Jira notifications (FEAT-225) | `msteams/auth.py`; `msteams/oauth_callback.py` — `class MSTeamsOAuthNotifier` | F060, F035 |

Additional artifacts the brainstorm did not know about: `AbstractOAuth2Manager` (F044), `OAuth2Provider`/`OAuth2ProviderRegistry` (F037), `IntegrationsService` + models + persistence (F038, F036, F039), `make_oauth2_callback`/`setup_oauth2_routes` (F005), `CredentialBroker`/`CredentialRequired`/`NeedsAuth`/`CanonicalIdentityMapper` (F006, F001, F042), `IdentityMappingService`/`IdentityVaultCredentialSink` (F012, F013), `MCPOAuth2Provider` (F045), admin-UI `IntegrationsMenu`/`ConnectIntegrationPill`/`popup.ts` (F027, F046).

---

## 3. Probable Scope  *(mode = enrichment)*

> Option B of the brainstorm, re-mapped onto the existing modules after U1–U5. Spec split preserved (S-1 core → S-2 Telegram → S-3a web/Slack → S-3b Teams) but each spec's content changes substantially.

### What's New

- **Principal-keyed credential path** — `AbstractOAuth2Manager` keys Redis/vault entries by the Navigator `user_id` (U1 primary) with `channel` demoted to an attribute and the Entra OID/email stored as a secondary column; a `PrincipalResolver` Protocol (core) resolves `(channel, channel_user_id) → nav_user_id` through `auth.user_identities`, injected by the server like `CredentialSink`. *Evidence*: F044, F012, F013, F042
- **Channel-neutral connections service** — `IntegrationsService` gains `channel` as a parameter and a principal-level `list_for_principal`; new user-level routes `GET /api/v1/connections`, `POST /api/v1/connections/{provider}/start`, `GET|DELETE /api/v1/connections/{provider}` next to the agent-scoped routes (which lose their enable/disable semantics per U2). *Evidence*: F038, F075, F040
- **`ChannelNotifier` Protocol + registry (core)** — `notify(principal, event)` implemented by telegram, slack, msteams and web adapters; the generic callback and refresh paths call the registry instead of importing channel code. *Evidence*: F073, F015, F035, F067
- **`connection.completed` / `connection.revoked` / `connection.refresh_failed` events** — published via a publish-only Streams `EventBus` following `observability/fanout.py` (U5: additive, never load-bearing); each also appended to `parrot.security.audit_ledger.AuditLedger` without token material. *Evidence*: F023, F034
- **Unified needs-auth conversion** — `ToolManager.execute_tool` also catches `CredentialRequired` and produces the same `ToolResult(status="authorization_required", metadata={auth_url, provider, scopes, tool_name})`; AgentTalk's envelope path handles both. *Evidence*: F004, F047, F001
- **Generic channel commands** — `/connect <provider>`, `/disconnect <provider>`, `/connections` driven by `OAuth2ProviderRegistry`, with `/connect_jira` and `/connect_office365` as aliases. *Evidence*: F015, F043, F037
- **Descriptor-as-data layer** — `OAuth2Provider`/`AbstractOAuth2Manager` accept endpoints, PKCE flag, refresh policy (rotating, lifetimes), identity-probe JSON paths, extra authorize params and a post-exchange hook name from a Pydantic descriptor (optionally YAML), so Atlassian/Microsoft/NetSuite need no manager subclass. *Evidence*: F037, F041, F020, F008
- **Web push on completion** — a Redis-backed per-principal channel in `UserSocketManager` (username ↔ `nav_user_id` map) so the Connections panel flips without reload; an automatic retry hook after `ConnectIntegrationPill`. *Evidence*: F021, F046

### What Changes

- **`parrot/auth/oauth2_base.py`::`AbstractOAuth2Manager`** — principal-keyed key templates; `channel` attribute; provider-revoke hook; event publication + notifier dispatch after `handle_callback`/`_refresh_tokens`/`revoke`; descriptor-driven endpoints. *Evidence*: F044, F071
- **`parrot/auth/jira_oauth.py`::`JiraOAuthManager`** — becomes an `AbstractOAuth2Manager` subclass (`accessible-resources`→`cloud_id` as the post-exchange hook; TASK-4418 helpers reused), keeps `CredentialSink`; legacy `jira:oauth:{channel}:{user_id}` keys read for linked users only during the window, then deleted (U3). *Evidence*: F002, F059, F049
- **`parrot/auth/routes.py`::`jira_oauth_callback`** — retired in favour of `/api/auth/oauth2/jira/callback`; lazy integrations imports removed. *Evidence*: F024, F073
- **`parrot/auth/oauth2_routes.py`::`make_oauth2_callback`** — dispatches completion through the `ChannelNotifier` registry for every channel (web keeps the postMessage page). *Evidence*: F005, F070
- **`parrot/auth/oauth2/service.py`::`IntegrationsService`** — channel parameter, principal-level listing, one status path (`manager.is_connected` / Identity Vault) for every provider; `confirm_enable`/`user_agent_toolkits` retired (U2). *Evidence*: F038, F075, F039
- **`parrot/auth/oauth2/models.py`** — `UsersIntegrationRow` gains `canonical_identity` (OID/email) and `channels_seen`; `IntegrationDescriptor` gains `scopes_granted`, `expires_at`. *Evidence*: F036
- **`parrot/tools/manager.py`::`ToolManager.execute_tool`** — catch `CredentialRequired`; invalidate per-session resolver caches on `connection.completed`. *Evidence*: F004
- **`parrot_tools/jiratoolkit.py`::`JiraToolkit`** — declare `credential_provider="jira"`; client cache keyed by principal; hot-swap placeholder (`jira_connect_tool.py`) retired. *Evidence*: F029, F004
- **`parrot/mcp/client.py`::`MCPClientConfig`** and **`parrot/mcp/integration.py`::`add_oauth_mcp_server`** — remove add-time `user_id`; `token_supplier` resolves per call through the broker. *Evidence*: F017, F018, F063
- **`manager/manager.py`::`BotManager._register_oauth2_providers`** — register every configured provider from descriptors, not only Jira. *Evidence*: F016
- **`handlers/user.py`::`UserSocketManager`** — cross-process send-to-principal. *Evidence*: F021
- **`telegram/jira_commands.py`, `slack/commands/jira_commands.py`, `msteams/commands/jira_commands.py`** — generic commands + `ChannelNotifier` implementations; principal from `TelegramUserSession.nav_user_id` / Teams session / Slack identity. *Evidence*: F015, F043, F035, F067
- **`telegram/post_auth_jira.py`::`JiraPostAuthProvider`** — generalised to `post_auth_<provider>` on the registry. *Evidence*: F035
- **Admin UI `IntegrationsMenu.svelte`, `ConnectIntegrationPill.svelte`, `api/integrations.ts`** — user-level Connections panel (status, account, scopes, expiry) over `/api/v1/connections`, WS-driven refresh, auto-retry. *Evidence*: F027, F046
- **`services/vault_token_sync.py`** — O365 device-code and fireflies/workiq paths read through the same principal key (store consolidation, S-3a). *Evidence*: F010, F061

### What's Untouched (Non-Goals)

- `OAuthRoutesMixin` on `HttpMCPServer` and the navigator-auth OAuth 2.1 authorization server (parrot as resource server).
- The FEAT-735 ownership decision and `IdentityVaultCredentialSink` (built on, not replaced).
- `CredentialBroker` / `CredentialResolverFactory` / `CanonicalIdentityMapper` internals (consumed; the principal mapping wraps them).
- A2A suspend/resume (`SuspendedExecutionStore`, `register_a2a_resume_hook`) and the MSAgentSDK Adaptive/OAuth-card lane.
- BYOK per-user LLM keys and FEAT-063 DB credentials (`CredentialsHandler`).
- Multi-account selection UI (schema supports it; v2).
- navigator-auth as a remote token broker (brainstorm Option C; a later backend).
- External provider facts (R6) — to be re-verified at spec time (C23).

### Patterns to Follow

- Protocol injection from server into core (`CredentialSink`) for `PrincipalResolver` and `ChannelNotifier`. *Evidence*: F002, F059, F030
- Publish-only Streams `EventBus` with redacted payloads and outbox (`observability/fanout.py`). *Evidence*: F023, F066
- Principal from the authenticated session, never the body; `return_origin` allowlist (`IntegrationsHandler`, `IntegrationsService.start_connect`). *Evidence*: F040, F038
- Manager hooks (`_exchange_code`, `_refresh_request`, `_discover_identity`, `_build_token_set`, `authorization_url_extra_params`) as the extension seam. *Evidence*: F044, F041
- `nav_user_id` under its own `extra_state` key; callbacks fail closed on a non-numeric id. *Evidence*: F035, F062, F056
- Proactive notification keyed by serialized `ConversationReference` (Teams) / `chat_id` (Telegram) stored in `extra_state`. *Evidence*: F035, F015, F067

### Integration Risks

- **Reversing FEAT-144** (per-agent enablement, channel-separate credentials): without an explicit statement the change reads as a security regression. *Mitigation*: record the reversal (U2) in the spec; PBAC provider/scope allowlist on `start`. *Evidence*: F065
- **Two principal keys**: stranding A2A/MSAgentSDK if only the Navigator id is stored. *Mitigation*: U1 — both columns, Navigator primary, OID/email secondary; map through `auth.user_identities`. *Evidence*: F042, F072, F060
- **Unlinked Telegram users** lose their Jira connection at cutover. *Mitigation*: U3 accepted forced re-connect; count `jira:oauth:telegram:*` keys without a matching `telegram` identity row before cutover and announce. *Evidence*: F048, F043, F035
- **Re-keying live caches** (`jira:oauth:*`, `oauth2:*`, vault `oauth2_{p}_{c}_{u}`). *Mitigation*: read-new-then-legacy for linked users; rewrite on read; delete after a measured window. *Evidence*: F002, F044, F011
- **Notification topology**: a consuming bus in the bot process is not available today. *Mitigation*: U5 — notifier registry primary, bus additive. *Evidence*: F022, F023, F073
- **Web push** needs `UserSocketManager` changes. *Mitigation*: popup `postMessage` remains load-bearing; WS push additive. *Evidence*: F021
- **Name collisions** with existing registries/routes. *Mitigation*: reuse `OAuth2ProviderRegistry`, `setup_oauth2_routes`; no new registry names. *Evidence*: F055, F048, F009

### 3.4 Brainstorm §10 — Does NOT Exist (the rewrite the source requested)

Absent in `packages/` (probe `absent` checks at HEAD `5fa785952`, F019, `citation_checks.md`): `parrot.connections` (no `parrot/connections/__init__.py`), `ConnectionManager`, `OAuthProviderRegistry`, `VaultCredentialResolver`, `CredentialVault`, `ConnectionChannel`, `AuthRequirement`, `requires_auth`, `NeedsAuthorizationError`, `WebOAuthManager`, `StateStore`, `/oauth/callback/{provider}`, `/api/v1/connections*`, `connection.*` events, a generic `/connect <provider>` command, `/api/o365/oauth/*`.

Brainstorm §10 items that turned out to **exist** (moved to §2.4): a principal-keyed durable OAuth store (Identity Vault, Jira), `TokenStore`, a Svelte connect UI (admin UI, per agent), `AuthorizationRequired` in core and caught by `ToolManager`, generic `CredentialResolver`, PKCE S256 (in `AbstractOAuth2Manager`, not the removed MCP manager), Teams/Slack channel commands and notifiers.

Confirmed **true** cautions from §10: `user_socket_manager` cannot target one principal across processes (F021); `navigator-eventbus` is not consumed by the Telegram bot (F022); Telegram's `PermissionContext.user_id` is the raw Telegram id (F048).

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Generic 3LO manager (PKCE S256, Redis nonce, vault+Redis, locked rotating refresh) exists at `oauth2_base.py::AbstractOAuth2Manager` | F044, F071 | high | full read, line-anchored, wiki-corroborated |
| C2 | `JiraOAuthManager` is a parallel implementation (no PKCE, `jira:oauth:{channel}:{user_id}`), not a subclass; carries `CredentialSink` | F002, F059, F071 | high | read + grep + spec |
| C3 | `OAuth2ProviderRegistry` and web `IntegrationsService` (agent-scoped, `channel="web"`) exist with list/start/enable/disconnect/persist | F037, F038, F075, F036 | high | direct reads |
| C4 | Generic `/api/auth/oauth2/{provider}/callback` exists (exclude_list, postMessage, A2A resume); Jira still on its own route with direct dispatch | F005, F070, F024, F073 | high | both route modules read |
| C5 | FEAT-264 broker stack fully shipped (11/11 tasks) | F054, F058, F006, F004, F033, F042 | high | code + task index |
| C6 | Two needs-auth signals; `ToolManager` converts only `AuthorizationRequired`; `CredentialRequired` bubbles | F004, F047, F001, F003 | high | grep + reads |
| C7 | Identity Vault is the durable Jira owner (FEAT-735, 2026-10-23); Redis stays the live path | F031, F059, F013, F049, F050 | high | doc + spec + code + git |
| C8 | "Session vault" = navigator-session user vault via `VaultTokenSync` (persistent, encrypted); `vault_utils` and MCP `TokenStore` are further stores | F010, F011, F019, F057, F068 | high | reads of all three |
| C9 | Channel ids map to the Navigator principal via `auth.user_identities`; Telegram link created by `/login`, persisted only via the combined Jira flow; `PermissionContext.user_id` = telegram_id | F012, F056, F035, F043, F048, F062 | high | service + wrapper + auth reads |
| C10 | Broker canonical identity (OID/email) and Navigator bigint id are different principal keys; only the Teams lane bridges them | F042, F072, F060 | high | identity.py + FEAT-729 |
| C11 | `NeedsAuthorizationError`, `WebOAuthManager`, `StateStore`, `requires_auth`, `parrot.connections`, `ConnectionManager`, `ConnectionChannel`, `AuthRequirement` absent; `TokenStore` present | F019, F033 | high | negative greps + probe `absent` |
| C12 | MCP per-call injection via `header_provider` exists; `token_supplier` zero-arg; add-time `user_id` remains; MCP `OAuthManager` removed | F017, F018, F063, F052, F019 | high | greps + task + git |
| C13 | No `/api/o365/oauth/*`; admin UI ships menu/pill/popup without WS push, cross-channel view or auto-retry | F024, F027, F046, F065 | high | grep + UI reads (TROC AgentChat repo not inspected) |
| C14 | Completion is a direct in-process call; bus present but no channel subscriber | F024, F073, F064, F022, F023 | high | route reads + bus grep |
| C15 | `UserSocketManager` cannot target one principal across processes | F021 | medium | parent navigator `WebSocketManager` (external) not inspected |
| C16 | Teams user-auth lane + proactive Jira notifications exist; Slack has commands + DM; O365 has manager + provider; Gen-1 routes deleted | F060, F067, F035, F061, F041 | high | spec pages + code |
| C17 | FEAT-144 recorded cross-channel sharing as a non-goal; per-(user, agent, toolkit) enablement | F065, F039 | high | task/spec pages + persistence.py |
| C18 | `JiraToolkit` lacks `credential_provider` and keeps the hot-swap; `Office365Toolkit` declares it | F029, F004, F025 | high | greps + reads |
| C19 | Remaining delta = principal re-keying, Jira onto the generic manager, channel-neutral service/routes, notifier/event completion, generic commands, descriptor-as-data — not a new module | F044, F038, F005, F073, F015, F037 | medium → decided by U1/U2/U4 | inferred scope; decisions now taken (§5) |
| C20 | O365 3LO and device-code flows write different stores; no consolidation feature filed | F061, F032 | medium | spec + docs; follow-up searched only in the wiki |
| C21 | Legacy `jira:oauth:*` has a single writer/reader (`JiraOAuthManager`) | F002, F031 | high | grep over packages |
| C22 | Ledger `issue:e2221d566081` is stale-open (delivered by TASK-4671) | F074, F030, F051 | high | ledger show + code + git |
| C23 | External provider facts (Atlassian/Microsoft/NetSuite refresh lifetimes, rotation) were not verified | — | low | R6 is external; no web lookups made |

Distribution: **19** high, **3** medium, **1** low. Overall **medium**, bounded by C19 at synthesis time; with U1–U5 resolved the remaining medium/low items are verification work for `/sdd-spec` (C15 → read navigator `WebSocketManager`; C20 → confirm no O365 consolidation FEAT; C23 → provider docs).

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Which key is THE principal for the connections vault?** — *Resolved*: **Both columns, Navigator primary** — the connection row stores the navigator-auth bigint `user_id` (lookup key) and the Entra OID/email as a secondary index for Copilot/A2A/MSAgentSDK surfaces.
  *Resolves claims*: C10, C19
- [x] **U2 — Reverse FEAT-144's per-agent, channel-separate decision?** — *Resolved*: **Reverse fully: one connection, all agents** — a connected provider is available to every agent the principal can reach on every channel; per-agent enablement (`user_agent_toolkits`) is dropped.
  *Resolves claims*: C17, C19
- [x] **U3 — Telegram users who connected Jira without `/login`?** — *Resolved*: **Force re-connect** — they re-authorize once the principal key is live; no indefinite channel-keyed fallback. Users who linked via `/login` keep their Identity Vault copy and do not reconnect. (This narrows the brainstorm's "zero re-connect" constraint to linked users.)
  *Resolves claims*: C9, C19
- [x] **U4 — Where does the unified code live?** — *Resolved*: **Evolve `parrot.auth.oauth2` in place** — no new `parrot.connections` package, no renames; extend `AbstractOAuth2Manager`, `IntegrationsService`, `OAuth2ProviderRegistry` and `oauth2_routes` where they are.
  *Resolves claims*: C19
- [x] **U5 — Completion transport?** — *Resolved*: **Notifier registry + publish-only bus** — an in-core `ChannelNotifier` Protocol registry is the delivery path; `connection.*` events are also published on the Streams bus for audit/out-of-process consumers, never load-bearing.
  *Resolves claims*: C14, C15

### Unresolved (defer to spec / implementation)

- [ ] **Vault persistent backend for non-Jira providers**: Identity Vault for every OAuth provider (extending FEAT-735's `_IDENTITY_OWNED_PROVIDERS`) vs keep `vault_utils`/`VaultTokenSync` for O365/fireflies/workiq — *Owner*: Jesus. *Blocks*: C20. *Plausible*: a) Identity Vault for all 3LO providers · b) Identity Vault for 3LO, `VaultTokenSync` for static keys/device-code.
- [ ] **Legacy key cutover window and metric** (count of `jira:oauth:telegram:*` without a `telegram` identity row) — *Owner*: Jesus.
- [ ] **PBAC shape for provider/scope allowlists** (`pbac_action_namespace="integration"` already exists on `OAuth2Provider`): policy in navigator-auth vs tenant config — *Owner*: Jesus.
- [ ] **Encryption key management** for new vault columns (navconfig secret vs KMS envelope) — *Owner*: Jesus.
- [ ] **R6 provider facts** (Atlassian rotating refresh, Microsoft refresh lifetime, NetSuite 7-day rotation) — *Owner*: `/sdd-spec` (C23).

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-773`** — *Rationale*: localization and constraints are high-confidence, the architectural fork (Option B) was settled in the brainstorm and the five placement/product decisions are now recorded; the remaining medium/low items are spec-time verifications, not research gaps. Produce the four specs the brainstorm planned, re-scoped:

| Spec | Re-scoped content (built on existing modules) |
|---|---|
| **S-1 Connections core** | principal-keyed `AbstractOAuth2Manager` (+ `PrincipalResolver`, `ChannelNotifier` Protocols, descriptor-as-data, events + audit), `IntegrationsService` channel-neutral + `/api/v1/connections*`, `ToolManager` dual catch, MCP add-time `user_id` removal, `BotManager` provider registration from descriptors, Jira port onto the generic manager (`/api/auth/jira/callback` retired) |
| **S-2 Telegram migration** | generic `/connect <provider>` + notifier impl, principal resolution from `TelegramUserSession`, JiraToolkit on the broker seam, legacy-key read for linked users + forced re-connect for the rest, cutover + delete |
| **S-3a Web + Slack** | user-level Connections panel + WS push + auto-retry in the admin UI, `UserSocketManager` cross-process send, Slack notifier impl + first-link owner fix, O365 store consolidation |
| **S-3b MS Teams** | Teams `ChannelNotifier` over the existing `MSTeamsOAuthNotifier` and FEAT-729 principal mapping; generic commands |

### Alternatives

- **`/sdd-brainstorm FEAT-773`** — only if U2's full reversal of FEAT-144 needs a wider product discussion before the spec.
- **`/sdd-task FEAT-773`** — not applicable (multi-package, production migration).
- **Manual review** — not needed; research complete, lint passed first iteration, 0 missing citations.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-773/state.json` |
| Source (raw) | `sdd/state/FEAT-773/source.md` |
| Research plan | `sdd/state/FEAT-773/research_plan.json` (58 queries; 3 parallel lanes, FEAT-708) |
| Findings (digests) | `sdd/state/FEAT-773/findings/F001-*.md` … `F076-*.md` (lane originals FC/FG/FW in `findings/.audit/`) |
| Citation probe | `sdd/state/FEAT-773/probe_sheet.json`, `probe_group_*.json`, `citation_checks.md`, `citations_raw.json` |
| Synthesis (JSON) | `sdd/state/FEAT-773/synthesis.json` (with `unknowns[].user_answer`) |

**Budget consumed** (loose profile):
- Files read: 53 / 100
- Grep calls: 25 / 60
- Git calls: 11 / 20
- Wiki calls: 23 (free)
- Wall time: ~1330 s (longest lane) / 900 s per-lane cap not exceeded by any lane's own clock
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (additive verbs; explicit verification mandate).

**Lanes**: codebase 57 digests (36 planned + 21 follow-ups, depth ≤ 2) · git 5 · wiki 23 (17 planned + 6 follow-ups) → merged 85 → 76 (9 merges by `(path, symbol)` overlap).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` (FEAT-708 parallel lanes + citation probe) |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (with Claude Fable 5.1) |

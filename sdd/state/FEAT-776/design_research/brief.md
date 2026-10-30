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

### Constraints and goals
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

### Recommended option / probable scope
This work is S-2 (Telegram migration) of a five-spec split. It depends on S-1 (connections core, sdd/specs/delegated-auth-connections.spec.md) being merged; S-1 introduces Principal/PrincipalResolver, principal-keyed AbstractOAuth2Manager, ChannelNotifier registry + ConnectionEvent, a Telegram Jira notifier adapter, a '/login first' reply in /connect_jira, legacy-key dual-read until OAUTH2_LEGACY_KEYS_UNTIL, and JiraToolkit credential_provider='jira'.

S-2 scope (from the accepted proposal §6):
| **S-2 Telegram migration** | generic `/connect <provider>` + notifier impl, principal resolution from `TelegramUserSession`, JiraToolkit on the broker seam, legacy-key read for linked users + forced re-connect for the rest, cutover + delete |

Relevant proposal scope lines:
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

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py
packages/ai-parrot-integrations/src/parrot/integrations/telegram/office365_commands.py
packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py
packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py
packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
packages/ai-parrot-integrations/src/parrot/integrations/telegram/combined_callback.py
packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_callback.py
packages/ai-parrot-integrations/src/parrot/integrations/manager.py
packages/ai-parrot-server/src/parrot/services/identity_mapping.py
packages/ai-parrot/src/parrot/auth/oauth2/registry.py
packages/ai-parrot/src/parrot/auth/oauth2_base.py
packages/ai-parrot/src/parrot/auth/jira_oauth.py
packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
sdd/specs/delegated-auth-connections.spec.md

### Questions still open in the exploration document
- Legacy key cutover window and metric (count of jira:oauth:telegram:* without a telegram identity row).
- Legacy key cutover date (OAUTH2_LEGACY_KEYS_UNTIL) and acceptable unbound count.

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?

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
This is sub-spec S-3a (Web + Slack) of FEAT-773 'Delegated Auth Connections'. Parent exploration doc: sdd/proposals/delegated-auth-connections.proposal.md (accepted).

## 1. Synthesis Summary

The brainstorm asks for one generic OAuth2 3LO "connections" implementation keyed by platform principal, consumed by web, Telegram and MS Teams, with one needs-auth contract and event-driven completion. The codebase already contains the generic engine (`parrot/auth/oauth2_base.py::AbstractOAuth2Manager` — PKCE S256, Redis nonce state, vault+Redis persistence, lock-protected rotating refresh), the provider registry (`parrot/auth/oauth2/registry.py::OAuth2ProviderRegistry`), a web connections service and its API contracts (`parrot/auth/oauth2/service.py::IntegrationsService`, `models.py`), a generic per-provider callback (`parrot/auth/oauth2_routes.py::make_oauth2_callback`), a per-user credential broker (`parrot/auth/broker/core.py::CredentialBroker`), a principal-keyed durable store for Jira (navigator-auth Identity Vault via `services/identity_credential_sink.py`, decided 2026-10-23), and channel commands plus notifiers for Telegram, Slack **and** Teams. What is genuinely missing is the *principal keying* (every hot cache and vault name still embeds the channel), the Jira manager sitting outside the generic engine, a user-level (not agent-scoped, not web-only) connections view, a single needs-auth conversion for both `AuthorizationRequired` and `CredentialRequired`, and a notification path that does not call channel code from the callback. With the five decisions taken in §5 (Navigator `user_id` as primary key with OID/email as secondary, full reversal of FEAT-144's per-agent model, forced re-connect for unlinked Telegram users, evolve `parrot.auth.oauth2` in place, notifier registry plus publish-only bus), the recommendation is to proceed to `/sdd-spec` with the four-spec split re-mapped onto the existing modules (§3).


The full source is at `sdd/state/FEAT-773/source.md` (338 lines). Excerpt of the problem statement:

> Users cannot connect their own Office 365, Jira or any other OAuth2 (3LO) service from the AgentChat UI, and the delegated-auth logic that does exist is implemented three times, each tied to one channel. […] 1. No single place to add a provider or a channel. 2. Connections are channel-bound. A Jira account connected from Telegram is invisible to the same user on the web, because the vault key carries the channel, not the platform principal. 3. Two "needs auth" protocols. Toolkits raise `AuthorizationRequired`; the MCP path was designed around `NeedsAuthorizationError`.

### Constraints and goals
Constraints from the parent proposal §2.2 that bear on S-3a:

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


Resolved decisions (U1-U5):
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

### Recommended option / probable scope
S-3a scope (parent proposal §6 table row):
| **S-3a Web + Slack** | user-level Connections panel + WS push + auto-retry in the admin UI, `UserSocketManager` cross-process send, Slack notifier impl + first-link owner fix, O365 store consolidation |

S-1 (FEAT-773 core, a prerequisite spec) defers these items to S-3a: user-level Connections panel, WS push on completion (cross-process UserSocketManager), automatic retry after connect, Slack notifier impl + Slack first-link owner fix, O365 store consolidation (device-code VaultTokenSync o365:*), removal of the FEAT-083 AgentTalk hot-swap placeholder jira_connect_tool.py, removal of the admin-UI /enable call.

Relevant parent proposal §3 items:
| 23 | `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py` | `VaultTokenSync`, `_synth_session_uuid` | 69-239 | the "session vault": navigator-session `SessionVault` made per-user by a deterministic synthetic `session_uuid`, encrypted, principal-keyed flat `{provider}:{field}`; serves fireflies/workiq/entra/o365; Jira retired | F010, F057 |
| 31 | `packages/ai-parrot-server/src/parrot/handlers/user.py` | `UserSocketManager.send_direct_message`, `_validate_token` | 63-414 | per-process `user_sockets[username]` from JWT; Redis for user-info + channel pubsub; no cross-process send-to-user primitive | F021 |
| `/connect_jira` Telegram command | **EXISTS** as `/connect_jira`, `/disconnect_jira`, `/jira_status` (not `/connect`); also `/connect_office365`; Slack and Teams have the same Jira commands | `telegram/jira_commands.py` — `def register_jira_commands`; `telegram/office365_commands.py`; `slack/commands/jira_commands.py`; `msteams/commands/jira_commands.py` | F015, F043, F067 |
| `user_socket_manager` on `BotManager` | **EXISTS** (`app['user_socket_manager']`, read on startup) — `send_direct_message(to_username)` is process-local | `handlers/user.py` — `class UserSocketManager`, `async def send_direct_message` | F016, F021 |
| "Session vault" per user | **EXISTS** — navigator-session `SessionVault` made per-user by a deterministic `session_uuid` (`VaultTokenSync`), encrypted, persistent; plus `vault_utils` DocumentDB/Postgres store and the navigator-auth Identity Vault | `services/vault_token_sync.py` — `def _synth_session_uuid`; `security/vault_utils.py` — `def oauth2_vault_name` | F010, F011, F057, F068 |
- **Channel-neutral connections service** — `IntegrationsService` gains `channel` as a parameter and a principal-level `list_for_principal`; new user-level routes `GET /api/v1/connections`, `POST /api/v1/connections/{provider}/start`, `GET|DELETE /api/v1/connections/{provider}` next to the agent-scoped routes (which lose their enable/disable semantics per U2). *Evidence*: F038, F075, F040
- **`ChannelNotifier` Protocol + registry (core)** — `notify(principal, event)` implemented by telegram, slack, msteams and web adapters; the generic callback and refresh paths call the registry instead of importing channel code. *Evidence*: F073, F015, F035, F067
- **`connection.completed` / `connection.revoked` / `connection.refresh_failed` events** — published via a publish-only Streams `EventBus` following `observability/fanout.py` (U5: additive, never load-bearing); each also appended to `parrot.security.audit_ledger.AuditLedger` without token material. *Evidence*: F023, F034
- **Web push on completion** — a Redis-backed per-principal channel in `UserSocketManager` (username ↔ `nav_user_id` map) so the Connections panel flips without reload; an automatic retry hook after `ConnectIntegrationPill`. *Evidence*: F021, F046
- **`handlers/user.py`::`UserSocketManager`** — cross-process send-to-principal. *Evidence*: F021
- **`telegram/jira_commands.py`, `slack/commands/jira_commands.py`, `msteams/commands/jira_commands.py`** — generic commands + `ChannelNotifier` implementations; principal from `TelegramUserSession.nav_user_id` / Teams session / Slack identity. *Evidence*: F015, F043, F035, F067
- **Admin UI `IntegrationsMenu.svelte`, `ConnectIntegrationPill.svelte`, `api/integrations.ts`** — user-level Connections panel (status, account, scopes, expiry) over `/api/v1/connections`, WS-driven refresh, auto-retry. *Evidence*: F027, F046
- **`services/vault_token_sync.py`** — O365 device-code and fireflies/workiq paths read through the same principal key (store consolidation, S-3a). *Evidence*: F010, F061

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot-server/src/parrot/handlers/user.py
packages/ai-parrot-server/ui/src/lib/components/agents/integrations/IntegrationsMenu.svelte
packages/ai-parrot-server/ui/src/lib/components/agents/integrations/ConnectIntegrationPill.svelte
packages/ai-parrot-server/ui/src/lib/oauth/popup.ts
packages/ai-parrot-server/ui/src/lib/api/integrations.ts
packages/ai-parrot-server/src/parrot/services/vault_token_sync.py
packages/ai-parrot/src/parrot/auth/o365_oauth.py
packages/ai-parrot/src/parrot/security/vault_utils.py
packages/ai-parrot-tools/src/parrot_tools/o365/oauth_toolkit.py
packages/ai-parrot/src/parrot/tools/jira_connect_tool.py
packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py
packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/jira_commands.py
packages/ai-parrot-server/src/parrot/handlers/integrations.py
packages/ai-parrot/src/parrot/auth/oauth2/service.py
packages/ai-parrot/src/parrot/auth/oauth2_routes.py
packages/ai-parrot/src/parrot/observability/fanout.py

### Questions still open in the exploration document
- [ ] **Vault persistent backend for non-Jira providers**: Identity Vault for every OAuth provider (extending FEAT-735's `_IDENTITY_OWNED_PROVIDERS`) vs keep `vault_utils`/`VaultTokenSync` for O365/fireflies/workiq — *Owner*: Jesus. *Blocks*: C20. *Plausible*: a) Identity Vault for all 3LO providers · b) Identity Vault for 3LO, `VaultTokenSync` for static keys/device-code.
- [ ] **Legacy key cutover window and metric** (count of `jira:oauth:telegram:*` without a `telegram` identity row) — *Owner*: Jesus.
- [ ] **PBAC shape for provider/scope allowlists** (`pbac_action_namespace="integration"` already exists on `OAuth2Provider`): policy in navigator-auth vs tenant config — *Owner*: Jesus.
- [ ] **Encryption key management** for new vault columns (navconfig secret vs KMS envelope) — *Owner*: Jesus.
- [ ] **R6 provider facts** (Atlassian rotating refresh, Microsoft refresh lifetime, NetSuite 7-day rotation) — *Owner*: `/sdd-spec` (C23).

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?

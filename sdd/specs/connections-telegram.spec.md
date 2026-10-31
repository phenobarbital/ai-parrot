---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server, ai-parrot-integrations, docs]
tags: [oauth2, connections, telegram, principal, credentials, pbac]
---

# Feature Specification: Connections on Telegram — S-2 of Delegated Auth Connections (persisted principal link, generic `/connect`, Telegram `ChannelNotifier`, needs-auth surfacing, legacy cutover)

**Feature ID**: FEAT-776
**Date**: 2026-10-30
**Author**: Jesus Lara (with Claude Opus 5.5)
**Status**: approved
**Target version**: 1.3.0

**Implementation gate**: FEAT-773 is merged (PR #1897). FEAT-775 M3/M7 owns the shared
`permission_context` service API, evaluator wiring and channel-aware disconnect. FEAT-776 M3 verifies that
contract; dependent modules wait for it. The production PDP adapter parity gate in §8 Q1 remains explicit.

> **Source**: proposal `sdd/proposals/delegated-auth-connections.proposal.md` (FEAT-773, `accepted`) §6 row
> "S-2 Telegram migration", and `sdd/specs/delegated-auth-connections.spec.md` (FEAT-773, S-1) §1 Non-Goals
> ("Generic `/connect <provider>` channel commands, `ConnectionChannel` protocol work and the Telegram legacy-key
> cutover — **S-2**"). No S-2-specific brainstorm exists; the FEAT-773 proposal is the exploration document.
> **Prerequisite satisfied: FEAT-773 merged (PR #1897).** Everything below consumes FEAT-773's `Principal`, `PrincipalResolver`,
> principal-keyed `AbstractOAuth2Manager`, `IntegrationsService` (channel parameter), `ChannelNotifier` registry,
> `ConnectionEvent`, `AuthRequiredPayload` and `legacy_audit`. Sibling consumer spec **FEAT-775**
> (`connections-msteams`, S-3b) shares two pieces with this one — see §2 "Shared with FEAT-775".

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-773 makes every OAuth2 connection principal-keyed and channel-neutral, and gives Telegram the minimum for
parity: a Jira notifier adapter, a "/login first" reply in `/connect_jira`, and a date-gated dual read of
`jira:oauth:telegram:<telegram_id>`. Five gaps remain on Telegram (original investigation at `370a62d9b`; shared contracts rechecked 2026-10-31 at `70b0fb7d2b`):

1. **The principal link is not persisted by `/login`.** Every auth strategy (`BasicAuthStrategy.handle_callback`,
   telegram/auth.py:456-506, and the Azure/Google/OAuth2 strategies) only sets `TelegramUserSession.nav_user_id`
   in memory. The `telegram` row in `auth.user_identities` — which FEAT-773's `IdentityPrincipalResolver` reads —
   is written only as a side effect of the combined `/login`+Jira flow (`JiraPostAuthProvider._write_identity_records`,
   post_auth_jira.py:206-231). A user who ran plain `/login` has no resolvable principal, so every connection
   lookup fails closed. `/logout` (wrapper.py:2310-2327) clears only the in-memory session; once the row exists it
   would keep resolving after logout. The upsert's conflict target is `(user_id, auth_provider, provider_user_id)`
   (identity_mapping.py:43-53), so one Telegram id can end up linked to two Navigator users.
2. **Commands are provider-specific.** `/connect_jira`, `/disconnect_jira`, `/jira_status` (jira_commands.py:156-189)
   and `/connect_office365` (office365_commands.py:106-123) are hand-written per provider; nothing lists or connects
   the providers in `OAuth2ProviderRegistry`. `/connect_office365` does not run OAuth at all: it copies the
   Microsoft `/login` token into the in-memory session (office365_commands.py:59-63) — lost on restart, invisible
   on the web.
3. **Telegram cannot see a needs-auth tool result.** `AbstractClient._execute_tool` unwraps a `ToolResult` to
   `result.result` for every non-error status (clients/base.py:1661-1667). For
   `status="authorization_required"` that is `None`: the LLM is told the tool returned `None`, and the Telegram
   wrapper never learns that a connection is needed. No Telegram code handles `authorization_required`.
4. **PBAC cannot run from a chat command.** `IntegrationsService._check_pbac` returns `False` when
   `request is None` (service.py:509-511) and evaluates through `app['abac'].is_allowed(request, ctx)`. A Telegram
   command has no aiohttp request, so routing `/connect` through the service (FEAT-773 S4) would deny every call.
5. **Completion and post-auth are Jira-only.** FEAT-773 wraps `TelegramOAuthNotifier` (Jira text, Jira fields) in
   `TelegramJiraNotifierAdapter`; `revoked` and `refresh_failed` events have no Telegram delivery; the combined
   login flow (`post_auth_actions`) supports only `jira` (`_KNOWN_POST_AUTH_PROVIDERS`, models.py:16;
   `_init_post_auth_providers`, wrapper.py:557-632).

### Goals

- **G1 — Persisted, exclusive principal link.** A successful Telegram `/login` (any strategy, single-step or
  combined) writes exactly one `telegram` identity row for the Telegram id, owned by the logged-in Navigator user;
  `/logout` removes it. Sessions that logged in before this feature are backfilled lazily, once.
- **G2 — Generic connection commands.** `/connect [<provider>]`, `/disconnect <provider>`, `/connections`, driven
  by `OAuth2ProviderRegistry` through `IntegrationsService(channel="telegram", principal=…)`. Only connectable
  providers are offered (manager present, not `mcp:*`, optional per-bot allowlist). Scopes are server-owned.
  `/connect_jira`, `/disconnect_jira`, `/jira_status` remain as aliases; `/connect_office365`,
  `/disconnect_office365`, `/office365_status` alias the generic commands **only when an `o365` provider is
  registered** — otherwise the existing session-copy handlers stay unchanged.
- **G3 — PBAC from chat, fail closed.** Connect and disconnect from Telegram are evaluated against the Navigator
  principal through a request-less PBAC path. No PDP, or no matching policy, refuses the command with a clear
  message — the same rule as the web (FEAT-773 S4). Shipping the `integration:connect` /
  `integration:disconnect` policy is a deploy precondition.
- **G4 — Needs-auth reaches both the LLM and the user.** The LLM receives a short, channel-neutral instruction
  instead of `None`; the Telegram wrapper collects needs-auth payloads during `ask()` and answers with a Connect
  button (or the device-code instructions) after the agent's reply.
- **G5 — One Telegram `ChannelNotifier` for every provider and event.** `connection.completed`, `connection.revoked`
  and `connection.refresh_failed` reach the user's chat for any provider, through the bot that issued the flow.
  Provider-specific session effects (the Jira `<jira>` prompt block) become registered session hooks.
- **G6 — Generic combined login.** `post_auth_actions` accepts any registered provider; `JiraPostAuthProvider`
  becomes a preset of the generic provider. Primary authentication precedes provider authorization; required
  secondary steps gate identity publication and session activation.
- **G7 — Telegram legacy cutover.** After `OAUTH2_LEGACY_KEYS_UNTIL` (FEAT-773), a guarded purge deletes the
  Telegram legacy keys; the raw-`telegram_id` credential paths and comments are removed.

### Non-Goals (explicitly out of scope)

- Anything FEAT-773 owns: the principal-keyed engine, `IntegrationsService` channel parameter and
  `list_for_principal`, `/api/v1/connections*`, `AuthRequiredPayload`, the generic callback, the legacy dual-read
  window, `IdentityPrincipalResolver`, `JiraToolkit` on the broker seam (FEAT-773 M7 — the proposal's S-2 row
  listed it, the S-1 spec absorbed it).
- Teams (FEAT-775), web panel / WS push / auto-retry / Slack / O365 store consolidation (S-3a), CLI and local MCP
  (S-4). This spec does not migrate Teams onto the channel-neutral command core it creates (FEAT-775 §8 Q2 records the decision).
- Removing the generic legacy dual-read code from `AbstractOAuth2Manager` / `JiraOAuthManager` — Slack and Teams
  legacy keys still need it; the last consumer spec deletes it. S-2 purges only Telegram keys.
- Changing how `TelegramAgentWrapper._build_permission_context` builds `UserSession(user_id=telegram_id)`
  (wrapper.py:1310-1314): FEAT-773's `OAuthCredentialResolver` already resolves `("telegram", telegram_id)` to the
  principal. Using the Navigator id in Layer-2 tool PBAC is a separate decision.
- Multi-account selection, group-chat connections (commands reply "use a private chat with the bot"), a
  Telegram-side consumer of the `connection.*` bus.

---

## 2. Architectural Design

### Overview

All Telegram code stays in `ai-parrot-integrations/…/telegram/`. Core gains the needs-auth collector (shared with
FEAT-775) and the `_execute_tool` message fix; request-less PBAC is consumed from FEAT-775; the server identity service gains
link/unlink; the channel-neutral half of the commands lands in `integrations/core/auth/` so other channels can reuse it.

**Principal link (M4).** `IdentityMappingService.link_channel_identity()` writes the channel row in one
transaction: acquire the channel-account transaction lock defined in M4, delete every
`(auth_provider, provider_user_id)` row owned by a *different* Navigator user, then the existing upsert.
`unlink_channel_identity(auth_provider, provider_user_id)` takes the same lock before deleting by channel id.
The wrapper calls `_persist_principal_link(session)` only at final login success — after primary authentication
for single-step login, and after **all required secondary actions succeed** for combined login — and `unlink`
in `handle_logout` before `session.clear_auth()`. A
`principal_link_persisted` flag on `TelegramUserSession` makes `_ensure_principal_link(session)` a once-per-session
backfill, called from the connection commands and `_invoke_agent`. Pending combined-login candidates are not
eligible for backfill, command principals, or agent execution. A failed write never fails the login: the user
is told connections are unavailable, and resolution fails closed. `principal_for_session` absorbs the existing async `_telegram_principal` (jira_commands.py:102):
prefer a finalized authenticated session, otherwise call `resolve_principal("telegram", str(telegram_id))`.
Preserve the stored identity fallback after restart; a persisted link resolves identity without fabricating
roles or an authenticated login session. Pending/failed candidates cannot override that link. An unlinked
user resolves to `None`; logout removes the stored fallback before clearing the session.
The Telegram identity write in the combined flow moves from `JiraPostAuthProvider` to this path.

**Request-less PBAC (M3).** Consume FEAT-775 M3/M7's `permission_context: PermissionContext` and
injected `permission_evaluator`. FEAT-775 is the sole owner of the four `IntegrationsService` methods and
factory wiring; Telegram adds no `permission_app` or `check_integration_access` API. Context identity is the
Navigator principal; roles/groups come only from validated session claims (empty when unavailable, including
persisted-link-only resolution). Require matching target user, principal, tenant and channel identity.
Preserve FEAT-773's action/provider/scopes policy inputs and fail-closed behavior. The merged HTTP call is
`abac.is_allowed(request, ctx)` at service.py:509; the agent-handler resource mapping is not its contract.
Production adapter parity must be proved by the shared allow/deny fixtures described in FEAT-775 M3.
Disconnect passes `channel="telegram"` and `principal` through to `manager.revoke`; default web behavior remains.

**Command core (M5).** `integrations/core/auth/connections.py::ConnectionCommandService` is channel-neutral:
`connectable_providers()` filters `OAuth2ProviderRegistry.all()` to providers with a manager, not `mcp:*`, and in
the optional allowlist; `connect()`, `disconnect()` and `statuses()` return typed `ConnectOutcome` /
`ConnectionStatusLine` values (`needs_login`, `denied`, `unknown_provider`,
`already_connected`, `auth_url`, `unavailable`, `disconnected`) and never send messages. Scopes for explicit commands are provider defaults; automatic offers use the sorted union of trusted
needs-auth payload scopes per provider (defaults only for an empty union). User input never chooses scopes.
Skip consent only when the active grant covers all requested scopes. M5 returns `auth_url`, never device-code
instructions: `start_connect` returns `ConnectInitResponse`, with no device-code producer. M8 alone renders
existing device-code payloads; M9 rejects unsupported modes as required-step failures. Scope-upgrade
consent is gated on FEAT-775’s wire-level scope propagation check, not merely ConnectInitResponse.scopes.

**Telegram commands (M6).** `telegram/connection_commands.py::register_connection_commands(router, *, commands,
principal_source, extra_state_factory)` registers `/connect`, `/disconnect`, `/connections` and the inline-picker
callback (`callback_data="conn:<provider_id>"`). Every handler: private chat only; principal or the "/login
first" reply (no OAuth state created); `ConnectionCommandService`; render the outcome — `auth_url` as an inline
URL button, `denied` as "Connecting <Provider> is not allowed for your account.".
`extra_state` carries `chat_id` and `bot_id` (the issuing bot). `jira_commands.py` keeps the public name
`register_jira_commands(router, …)` and only registers the three aliases. `office365_commands.py` registers
aliases when `o365` is connectable, else its current handlers. `TelegramAgentConfig.connection_providers:
Optional[List[str]]` is the allowlist (default `None` = all connectable). The command menu lists `connect`,
`disconnect`, `connections` plus any alias already shown today.

**Notifier (M7).** `telegram/connection_notifier.py::TelegramConnectionNotifier` implements FEAT-773's
`ChannelNotifier` (`channel = "telegram"`): one instance per aiohttp app at
`app["telegram_connection_notifier"]`, registered once in `ChannelNotifierRegistry` (replacing
`TelegramJiraNotifierAdapter`); each wrapper calls `attach(bot_id, bot)`. Target: `state_payload["extra"]
["chat_id"]` + `["bot_id"]` when present (callback path), else the Telegram id from the principal's `telegram`
identity row (private chat id == user id), sent through the only attached bot or the bot recorded by the latest
`/connect` for that principal; unknown ⇒ warning, no send. Texts per kind: completed → "<Provider> connected as
<display_name>."; revoked → "<Provider> disconnected."; refresh_failed → "<Provider> access expired — /connect
<id> to reconnect.". Sends use `parse_mode=None` (Markdown breaks on `_` in command names, jira_commands.py:57-61).
Session hooks: `register_session_hook(provider_id, on_completed, on_revoked)`; the wrapper registers the Jira hook
(today's stamper, wrapper.py:439-473, and `clear_jira_auth`) so the `<jira>` prompt block keeps working.
Failures are logged, never raised. Remove `TelegramOAuthNotifier`, `app["telegram_jira_session_stamper"]`
and the dead `app["jira_oauth_notifier"]` lookup (never assigned in production).

**Needs-auth (M1, M2, M8).** M1 is FEAT-775 M5's `parrot/auth/pending.py` contract, verbatim. M2 changes
`AbstractClient._execute_tool`: for `status == "authorization_required"` it returns a channel-neutral string —
"The user must connect their <provider> account before this tool can run. Do not retry this tool in this turn;
tell the user a connection is required." — never the `auth_url` (single-use state must not be echoed by the
model). M8 wraps all six `ask` call sites listed in M8 in `collect_auth_requirements()`; after the reply is sent, for each
distinct provider it runs the M6 connect routine (fresh state with this chat's `chat_id` / `bot_id` — the tool's
`auth_url` is not used) and sends the button; `auth_kind == "device_code"` renders `user_code` +
`verification_uri`; no principal ⇒ one "/login first" line per turn.

**Combined login (M9).** `telegram/post_auth_connection.py::ConnectionPostAuthProvider(provider_id, …)`
implements the existing `PostAuthProvider` Protocol (post_auth.py:34-90) for any registered provider:
`/login` first shows the primary login WebApp without constructing a provider URL. Its successful, validated
primary callback creates a **pending candidate**, separate from the active user session. Only then does
`build_auth_url` call `start_connect` with that candidate's Navigator principal and send the secondary Connect
button. This intentionally replaces the pre-authentication `next_auth_url` redirect with a staged interaction;
YAML and provider names remain compatible. Provider callback completion advances the pending attempt; it does
not independently authenticate the active Telegram session. After every required action succeeds, the wrapper
publishes the identity link and activates the candidate. Failure, cancellation or expiry discards the candidate
without publishing, deleting or replacing an identity link. M9 defines callback correlation and finalization.
`JiraPostAuthProvider` becomes a thin preset (`provider_name = "jira"`). `_init_post_auth_providers` resolves
any provider from the registry; the `_KNOWN_POST_AUTH_PROVIDERS` warning becomes "not a registered provider at startup".

**Cutover (M10).** FEAT-773's `legacy_audit` gains `purge_legacy_keys(redis, *, channel, providers, dry_run=True)`
and CLI flags `--purge --channel telegram [--confirm] [--force]`. It deletes `jira:oauth:telegram:*` and
`oauth2:<p>:telegram:*` only after `OAUTH2_LEGACY_KEYS_UNTIL` (or `--force`), prints counts only, and is
dry-run unless `--confirm`. The cutoff is already fixed: S-1 production deploy + 30 days, set via
`OAUTH2_LEGACY_KEYS_UNTIL`. Reuse `parrot.auth.oauth2_base._legacy_window_open(now)` (:79), including its
inclusive cutoff boundary. Reject a missing or malformed cutoff for destructive purge unless explicitly
forced; the helper's malformed-date `False` must never imply permission to delete.
This command purges **Redis only**. Old vault secrets `oauth2_{p}_telegram_{u}` are excluded; the docs must
state that residual vault cleanup is a separate operation, with the same expiry gate, not claim full erasure.
Runbook: audit → announce to the unbound users (U3: forced re-connect) → date passes
→ purge.

### Shared with FEAT-775 (connections-msteams)

| Piece | Owner | Rule |
|---|---|---|
| `parrot/auth/pending.py` (`collect_auth_requirements`, `record_auth_requirement`) + one call in `ToolManager` | FEAT-775 M5 **and** FEAT-776 M1, identical contract | Whichever feature merges first creates it; the other's task re-verifies the contract and only adds tests. Never two modules. |
| Request-less PBAC, evaluator wiring and channel-aware disconnect | FEAT-775 M3/M7 only | FEAT-776 M3 verifies and consumes `permission_context`; dependent tasks wait for the shared contract. |
| `clients/base.py::_execute_tool` needs-auth message | FEAT-776 M2 | Answers FEAT-775 §8 Q3 (decided here 2026-10-30). |
| Channel-neutral command core (`integrations/core/auth/connections.py`) | FEAT-776 M5 | Offered for FEAT-775 §8 Q2; S-2 does not migrate Teams. |

### Component Diagram

```
/login ─► primary callback ─► pending secondary actions (if configured) ─► final success ─► persist link + activate    [M4, M9]
/logout               ─► unlink_channel_identity("telegram", tg_id) ─► session.clear_auth()                                [M4]

/connect [p] | /connect_jira | conn:<p> button
   └─► connection_commands handler (private chat only)                                                                     [M6]
        ├─ principal_for_session / _ensure_principal_link ── None ─► "/login first" (no OAuth state)                      [M4]
        └─► ConnectionCommandService.connect(principal, p, extra_state={chat_id, bot_id})                                  [M5]
              └─► IntegrationsService.start_connect(channel="telegram", principal, permission_context=context)   (FEAT-775 API)
                    └─► _check_pbac → injected permission_evaluator(context, {action, provider, scopes})          [M3]
              ◄── ConnectOutcome(auth_url | denied | already_connected | …) ─► inline button / text

agent turn: _invoke_agent ─► with collect_auth_requirements() as pending: agent.ask(...)                                    [M8, M1]
              ToolManager.execute_tool ─ needs-auth ─► record_auth_requirement(payload) + ToolResult(authorization_required)
              AbstractClient._execute_tool ─► LLM gets "user must connect <provider>…" (not None)                          [M2]
           after reply: for provider in pending ─► M6 connect routine ─► Connect button

IdP consent ─► FEAT-773 callback ─► ConnectionEventPublisher ─► ChannelNotifierRegistry.get("telegram")
                                       └─► TelegramConnectionNotifier.notify ─► bot.send_message(chat_id) + session hook   [M7]
ops: python -m parrot.auth.oauth2.legacy_audit --purge --channel telegram --confirm                                        [M10]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `telegram/wrapper.py::TelegramAgentWrapper` | modifies | final-success link/logout unlink; `_ensure_principal_link`; staged login and pending-attempt finalization; generic commands; notifier attach + session hooks; needs-auth collector; generic `_init_post_auth_providers` |
| `telegram/auth.py::TelegramUserSession` | extends | `principal_link_persisted: bool` (non-repr, non-compare, like `post_login_ran`) |
| `telegram/jira_commands.py` | modifies (reduce) | aliases only; `TelegramOAuthNotifier` deleted |
| `telegram/office365_commands.py` | modifies | alias registration when `o365` is connectable |
| `telegram/post_auth_jira.py::JiraPostAuthProvider` | modifies (reduce) | preset of `ConnectionPostAuthProvider`; no identity writes |
| `telegram/models.py::TelegramAgentConfig`, `TelegramBotsConfig.validate` | extends / modifies | `connection_providers`; soft warning no longer tied to `{"jira"}` |
| `integrations/core/auth/post_auth.py::PostAuthProvider` | uses | Protocol unchanged |
| `integrations/core/auth/notifiers.py` *(created by FEAT-773 M8)* | modifies | drop `TelegramJiraNotifierAdapter` |
| `integrations/manager.py` *(FEAT-773 `_register_channel_notifiers`)* | modifies | create + register `TelegramConnectionNotifier` once per app |
| `parrot/auth/oauth2/service.py::IntegrationsService` *(FEAT-773 signatures)* | uses | consumes FEAT-775-owned context API; no Telegram service edits |
| `parrot/tools/manager.py::ToolManager.execute_tool` | modifies | `record_auth_requirement(payload)` in the FEAT-773 unified needs-auth branch |
| `parrot/clients/base.py::AbstractClient._execute_tool` | modifies | needs-auth message instead of `None` (user-approved change to the foundation file, 2026-10-30) |
| `ai-parrot-server services/identity_mapping.py::IdentityMappingService` | extends | `link_channel_identity`, `unlink_channel_identity` |
| `parrot/auth/oauth2/legacy_audit.py` *(created by FEAT-773 M10)* | extends | purge mode |

### Data Models

```python
# packages/ai-parrot-integrations/src/parrot/integrations/core/auth/connections.py  (new, M5)
class ConnectableProvider(BaseModel):
    provider_id: str
    display_name: str
    icon: Optional[str] = None

OutcomeKind = Literal["needs_login", "denied", "unknown_provider", "unavailable",
                      "already_connected", "auth_url", "disconnected"]

class ConnectOutcome(BaseModel):
    kind: OutcomeKind
    provider_id: str
    display_name: str = ""
    auth_url: Optional[str] = None            # kind == "auth_url"
    account_display_name: str = ""            # kind == "already_connected"
    message: str = ""                         # channel-neutral plain text (no Markdown)

class ConnectionStatusLine(BaseModel):
    provider_id: str
    display_name: str
    status: Literal["connected", "disconnected", "needs_reconnect"]
    account_display_name: str = ""

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py  (M6)
#   TelegramAgentConfig.connection_providers: Optional[List[str]] = None    # None = every connectable provider
```

### New Public Interfaces

```python
# core
from parrot.auth.pending import collect_auth_requirements, record_auth_requirement          # M1 (shared with FEAT-775 M5)
from parrot.auth.permission import PermissionContext                                      # M3 consumer
# server
IdentityMappingService.link_channel_identity(*, nav_user_id, auth_provider, provider_user_id, auth_data,
                                             display_name=None, email=None) -> None         # M4
IdentityMappingService.unlink_channel_identity(auth_provider, provider_user_id) -> int      # M4
# integrations
from parrot.integrations.core.auth.connections import ConnectionCommandService, ConnectOutcome, ConnectionStatusLine, ConnectableProvider  # M5
from parrot.integrations.telegram.connection_commands import register_connection_commands    # M6
from parrot.integrations.telegram.connection_notifier import TelegramConnectionNotifier      # M7
from parrot.integrations.telegram.post_auth_connection import ConnectionPostAuthProvider     # M9
# ops
python -m parrot.auth.oauth2.legacy_audit --purge --channel telegram [--confirm] [--force]   # M10
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Core needs-auth collector | yes | FEAT-775 M5 skeleton verbatim; ContextVar holding a shared list; no-op when unbound | — |
| M2: `_execute_tool` needs-auth message | yes | one branch before `return result.result`; message text fixed in §2; never the URL | — |
| M3: Request-less PBAC | no | — | consumer gated on FEAT-775 M3/M7 and shared production policy parity evidence |
| M4: Principal link lifecycle | no | — | transaction semantics across users, backfill and logout ordering are security decisions |
| M5: Channel-neutral command core | yes | models in §2; filter rules fixed (manager present, not `mcp:*`, allowlist); explicit commands use defaults; needs-auth offers union trusted payload scopes | — |
| M6: Telegram generic commands + aliases | no | — | private-chat rule, alias/O365 fallback and rendering of every outcome across providers |
| M7: Telegram `ChannelNotifier` + session hooks | yes | Protocol from FEAT-773; target-resolution order and texts fixed in §2; failures logged | — |
| M8: Needs-auth rendering in Telegram | yes | wrap both `_invoke_agent` branches and four direct calls listed in M8; dedupe by provider; reuse M6 routine | — |
| M9: Generic combined login | no | — | callback ordering with `handle_callback` and rollback semantics (`required`) |
| M10: Telegram legacy purge | yes | dry-run default; date gate; counts only; key patterns fixed in §2 | — |
| M11: Docs | yes | outline in M11 | — |

### Module 1: Core needs-auth collector (shared with FEAT-775 M5)
- **Path**: `packages/ai-parrot/src/parrot/auth/pending.py` (new); `packages/ai-parrot/src/parrot/tools/manager.py` (modify)
- **Responsibility**: FEAT-775 §2 "Needs-auth collector". If FEAT-775 has merged, this module only re-verifies the
  contract and adds `test_collector_*` tests that are missing.
- **Depends on**: FEAT-773 M5 (`AuthRequiredPayload`, unified needs-auth branch in `execute_tool`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/pending.py  (new — identical to FEAT-775 M5)
  _PENDING_AUTH: ContextVar[Optional[List[AuthRequiredPayload]]] = ContextVar("parrot_pending_auth", default=None)
  @contextmanager
  def collect_auth_requirements() -> Iterator[List[AuthRequiredPayload]]:
      """Bind a fresh list; reset the ContextVar token on exit."""
  def record_auth_requirement(payload: AuthRequiredPayload) -> None:
      """Append when bound; otherwise no-op."""
  # packages/ai-parrot/src/parrot/tools/manager.py — inside the FEAT-773 unified needs-auth branch
  #   (merged: `except (AuthorizationRequired, CredentialRequired) as auth_exc:`, manager.py:2274)
  #   record_auth_requirement(payload)   # before returning the ToolResult
  ```

### Module 2: LLM-facing needs-auth message
- **Path**: `packages/ai-parrot/src/parrot/clients/base.py` (modify)
- **Responsibility**: in `AbstractClient._execute_tool`, a `ToolResult` with `status == "authorization_required"`
  returns the §2 message built from `result.metadata["provider"]` (fallback "the required service") instead of
  `result.result`. Other statuses unchanged; the `status == "error"` branch (base.py:1662-1666) is untouched.
- **Depends on**: none (works with today's and FEAT-773's metadata shape: both carry `provider`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/clients/base.py  (modifies)
  _NEEDS_AUTH_TOOL_MESSAGE = ("The user must connect their {provider} account before this tool can run. "
                              "Do not retry this tool in this turn; tell the user a connection is required.")
  async def _execute_tool(self, tool_name: str, parameters: Dict[str, Any],
                          tool_context: Optional[Dict[str, Any]] = None) -> Any:     # verified: base.py:1619-1624
      # if isinstance(result, ToolResult):                                          # verified: base.py:1661
      #     if result.status == "error": ...                                       # unchanged
      #     if result.status == "authorization_required":                           # new
      #         return _NEEDS_AUTH_TOOL_MESSAGE.format(provider=(result.metadata or {}).get("provider") or "the required service")
      #     return result.result
  ```

### Module 3: Consume the shared request-less PBAC API
- **Path**: Telegram consumer tests; no ownership of `service.py`, a new PBAC module or server factory.
- **Responsibility**: verify FEAT-775 M3/M7's shared interface below, then use it in M5/M9. FEAT-775 owns
  implementation and shared policy parity tests. No duplicate implementation if Telegram is scheduled first.
- **Depends on**: FEAT-775 M3/M7, including production evaluator compatibility evidence; FEAT-773 is merged.
- **Interface Skeleton** (additions owned by FEAT-775; existing positional arguments preserved):
  ```python
  class IntegrationsService:
      def __init__(self, vault_token_sync: Any = None, *, permission_evaluator: Any = None) -> None: ...
      async def start_connect(self, user_id: str, provider_id: str, return_origin: Optional[str] = None, *,
                              channel: str = "web", principal: Optional[Principal] = None,
                              scopes: Optional[List[str]] = None, request: Any = None,
                              extra_state: Optional[Dict[str, Any]] = None,
                              permission_context: Optional[PermissionContext] = None) -> ConnectInitResponse: ...
      async def disconnect(self, user_id: str, provider_id: str, request: Any = None, *,
                           channel: str = "web", principal: Optional[Principal] = None,
                           permission_context: Optional[PermissionContext] = None) -> DisconnectResponse: ...
      async def status(self, user_id: str, provider_id: str, request: Any = None, *,
                       principal: Optional[Principal] = None,
                       permission_context: Optional[PermissionContext] = None) -> IntegrationDescriptor: ...
      async def list_for_principal(self, user_id: str, request: Any = None, *,
                                   principal: Optional[Principal] = None,
                                   permission_context: Optional[PermissionContext] = None) -> List[IntegrationDescriptor]: ...
      async def _check_pbac(self, request: Any, action: str, provider_id: Optional[str] = None,
                            scopes: Optional[List[str]] = None, *,
                            principal: Optional[Principal] = None,
                            permission_context: Optional[PermissionContext] = None) -> bool: ...
  ```
  `scopes` stays positional-compatible: existing connect/disconnect calls already pass it positionally.
  Only `start_connect` currently takes a principal; the other three principal parameters above are additions.
  Validate target `user_id` before `_check_pbac`; denial returns `[]` for list, and raises `PermissionError`
  for status/connect/disconnect. Unknown providers raise `ValueError`. No context denial falls back to HTTP.
  Inject the existing PDP through the FEAT-775 adapter; no fake HTTP request or second policy store.

### Module 4: Telegram principal link lifecycle
- **Path**: `packages/ai-parrot-server/src/parrot/services/identity_mapping.py` (modify); `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` (modify); `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py` (modify)
- **Responsibility**: §2 "Principal link". The DB pool is resolved as today in `_init_post_auth_providers`
  (`app.get("authdb") or app.get("database")`, wrapper.py:583). No pool ⇒ one warning at startup, link writes are
  skipped, connection commands reply "Connections are not available on this bot".
- **Depends on**: FEAT-773 M1 (`Principal`).
- **Concurrency contract**: every channel link/unlink takes `pg_advisory_xact_lock` on the same stable key
  derived from the namespaced, unambiguous encoding of `(auth_provider, provider_user_id)`, on the same DB
  connection and transaction as the delete/upsert. Use a deterministic digest-to-signed-bigint conversion,
  never Python's process-randomized `hash()`. Acquire the lock before reading or mutating rows; it must also
  serialize first links when no row exists. All Telegram identity writers, including legacy combined-login
  paths, must delegate here. A transaction alone or `SELECT FOR UPDATE` on a possibly absent row is insufficient.
  Link and unlink share the protocol; the existing user-inclusive unique constraint remains unchanged.
  Real-DB tests with separate connections must prove one owner after competing first links and relinks,
  rollback of a failed replacement, and serialized link/unlink outcomes.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/services/identity_mapping.py  (modifies)
  _DELETE_CHANNEL_OTHERS_SQL = """DELETE FROM auth.user_identities
      WHERE auth_provider = $1 AND provider_user_id = $2 AND user_id <> $3::text::bigint"""
  _DELETE_CHANNEL_SQL = "DELETE FROM auth.user_identities WHERE auth_provider = $1 AND provider_user_id = $2"
  class IdentityMappingService:                                                # verified: identity_mapping.py:136
      async def link_channel_identity(self, *, nav_user_id: str, auth_provider: str, provider_user_id: str,
                                      auth_data: Dict[str, Any], display_name: Optional[str] = None,
                                      email: Optional[str] = None) -> None:
          """One transaction: acquire channel-account lock, then _DELETE_CHANNEL_OTHERS_SQL and _UPSERT_SQL.
          Same validation as upsert_identity (numeric nav_user_id, non-empty provider_user_id, no secrets in
          auth_data, identity_mapping.py:207-225). Token-bearing providers are rejected (ValueError) — channel rows only."""
      async def unlink_channel_identity(self, auth_provider: str, provider_user_id: str) -> int:
          """Acquire the same channel-account lock in the deletion transaction; delete rows and return count; absent → 0."""

  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py  (modifies)
  @dataclass
  class TelegramUserSession:                                                   # verified: auth.py:44
      principal_link_persisted: bool = field(default=False, repr=False, compare=False)   # next to post_login_ran (auth.py:91)

  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py  (modifies)
  async def principal_for_session(session: TelegramUserSession, *, tenant_id: Optional[str] = None) -> Optional[Principal]:
      """Absorb jira_commands._telegram_principal: finalized authenticated session first, then
      await resolve_principal("telegram", str(session.telegram_id)); preserve restart resolution.
      Never expose a pending candidate. Navigator identity only; no raw Telegram credential fallback."""

  class TelegramAgentWrapper:
      def _identity_service(self) -> Optional["IdentityMappingService"]: ...   # cached; None without a pool
      async def _persist_principal_link(self, session: TelegramUserSession) -> bool:
          """link_channel_identity(nav_user_id, "telegram", str(telegram_id), {"telegram_id", "username"}, display_name, email);
          sets session.principal_link_persisted on success; logs and returns False on any failure."""
      async def _ensure_principal_link(self, session: TelegramUserSession) -> bool:
          """Only finalized active sessions may backfill; pending/failed candidates never write a link.
          No-op when principal_link_persisted or not authenticated; else _persist_principal_link."""
      # Single-step: persist after validated primary success; combined: persist only at M9 final success.
      # Never persist immediately after `basic_ok` (wrapper.py:2404) while required steps remain.
      # handle_logout (wrapper.py:2310): before session.clear_auth() → unlink_channel_identity("telegram", str(telegram_id))
      # clear_auth resets principal_link_persisted; cancellation also invalidates any pending login attempt.
  ```

### Module 5: Channel-neutral connection command core
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/connections.py` (new); `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/__init__.py` (export)
- **Responsibility**: §2 "Command core". Uses `IntegrationsService` (FEAT-773) with M3's `permission_context`;
  maps `PermissionError` from status/connect/disconnect to `denied`; list denial returns `[]`;
  `unavailable` when the provider's manager is missing at call time; plain-text messages only.
- **Depends on**: M3; FEAT-773 M6, `OAuth2ProviderRegistry` (registry.py:69).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/core/auth/connections.py  (new)
  class ConnectionCommandService:
      def __init__(self, *, service: "IntegrationsService", app: Mapping[str, Any], channel: str,
                   allowlist: Optional[Sequence[str]] = None,
                   registry: Optional["OAuth2ProviderRegistry"] = None) -> None: ...
      def connectable_providers(self) -> List[ConnectableProvider]:
          """registry.all() where provider.manager is not None, not provider_id.startswith("mcp:"), and in allowlist (if set)."""
      def resolve_provider(self, name: str) -> Optional[ConnectableProvider]:
          """Case-insensitive match on provider_id; aliases {"office365": "o365"} applied first."""
      async def connect(self, principal: Optional[Principal], provider_id: str, *,
                        extra_state: Dict[str, Any], permission_context: PermissionContext,
                        scopes: Optional[List[str]] = None) -> ConnectOutcome:
          """None → needs_login; unknown → unknown_provider; status() connected with sufficient scopes_granted → already_connected;
          start_connect(principal.user_id, provider_id, channel=self.channel, principal=principal,
          extra_state=extra_state, scopes=requested_scopes, permission_context=permission_context) → auth_url; PBAC denial → denied."""
      async def disconnect(self, principal: Optional[Principal], provider_id: str, *,
                           permission_context: PermissionContext) -> ConnectOutcome:
          """service.disconnect(..., channel=self.channel, principal=principal, permission_context=permission_context)."""
      async def statuses(self, principal: Optional[Principal], *,
                         permission_context: PermissionContext) -> List[ConnectionStatusLine]: ...
  ```

### Module 6: Telegram generic commands and aliases
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_commands.py` (new); `telegram/jira_commands.py` (modify → aliases); `telegram/office365_commands.py` (modify); `telegram/models.py` (modify); `telegram/wrapper.py` (modify)
- **Responsibility**: §2 "Telegram commands". Group/supergroup/channel chats get "Please use a private chat with
  the bot to manage connections." `/connect` without argument shows an inline keyboard of connectable providers.
  Every reply uses `parse_mode=None`. `_register_connection_commands` replaces `_register_jira_commands` and
  `_register_office365_commands` (wrapper.py:400-504) and is skipped when the registry has no connectable provider
  and no `o365` fallback applies.
- **Depends on**: M4 (`principal_for_session`, `_ensure_principal_link`, trusted context builder), M5, M7 (removal of
  `TelegramOAuthNotifier` waits for its replacement).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_commands.py  (new)
  PrincipalSource = Callable[[Message | CallbackQuery], Awaitable[Optional[Principal]]]
  # The wrapper also builds a fresh PermissionContext from this principal and validated session claims.
  # All service calls, including status/list and pending-candidate connect, receive that context.
  # Persisted-link-only sessions have no claims: roles/groups stay empty; identity remains usable.
  ExtraStateFactory = Callable[[Message | CallbackQuery], Dict[str, Any]]      # {"chat_id": …, "bot_id": …}
  async def connect_handler(message: Message, provider_arg: str, *, commands: ConnectionCommandService,
                            principal_source: PrincipalSource, extra_state_factory: ExtraStateFactory) -> None: ...
  async def disconnect_handler(message: Message, provider_arg: str, *, commands: ConnectionCommandService,
                               principal_source: PrincipalSource,
                               on_disconnected: Optional[Callable[[int, str], None]] = None) -> None: ...
  async def connections_handler(message: Message, *, commands: ConnectionCommandService,
                                principal_source: PrincipalSource) -> None: ...
  def render_connect_outcome(outcome: ConnectOutcome) -> Tuple[str, Optional[InlineKeyboardMarkup]]: ...
  def register_connection_commands(router: Router, *, commands: ConnectionCommandService,
                                   principal_source: PrincipalSource, extra_state_factory: ExtraStateFactory,
                                   on_disconnected: Optional[Callable[[int, str], None]] = None) -> List[Tuple[str, str]]:
      """Registers /connect, /disconnect, /connections and the "conn:" callback; returns menu entries."""

  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py  (modifies)
  def register_jira_commands(router: Router, *, commands: ConnectionCommandService, principal_source: PrincipalSource,
                             extra_state_factory: ExtraStateFactory,
                             on_disconnected: Optional[Callable[[int, str], None]] = None) -> None:
      """/connect_jira → connect_handler(…, "jira"); /disconnect_jira → disconnect_handler(…, "jira");
      /jira_status → connections_handler filtered to jira."""                 # verified: jira_commands.py:156 (signature changes)
  # REMOVED: connect_jira_handler (:50), disconnect_jira_handler (:90), jira_status_handler (:128), TelegramOAuthNotifier (:192)

  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/office365_commands.py  (modifies)
  def register_office365_commands(router: Router, session_provider: SessionProvider, *,
                                  commands: Optional[ConnectionCommandService] = None, ...) -> None:
      """commands and commands.resolve_provider("o365") → aliases to the generic handlers;
      else today's session-copy handlers unchanged."""                         # verified: office365_commands.py:106

  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py  (modifies)
  #   TelegramAgentConfig.connection_providers: Optional[List[str]] = None ; from_dict reads "connection_providers"
  ```

### Module 7: Telegram `ChannelNotifier` and session hooks
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_notifier.py` (new); `integrations/core/auth/notifiers.py` *(FEAT-773)* (drop `TelegramJiraNotifierAdapter`); `integrations/manager.py` (register once); `telegram/wrapper.py` (attach + Jira hook)
- **Responsibility**: §2 "Notifier". `_start_telegram_bot` must explicitly call notifier registration after
  obtaining the app and before accepting updates, then attach the bot. Today only Teams/Slack startup reaches
  the registration path. Repeated bot starts reuse one app registry/notifier; Telegram-only startup must work.
  Update `packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py` and
  `tests/integration/oauth2/test_e2e_telegram_regression.py` for the new notifier path.
  The adapter unit test currently supplies the dead key; the end-to-end test currently uses a notifier double.
  For `extra_state.combined=True`, dispatch completion to M9's attempt coordinator before ordinary session
  hooks; defer those hooks until final login success. Correlation failure never stamps an active session.
- **Depends on**: FEAT-773 M4 (`ChannelNotifier`, `ConnectionEvent`, `ChannelNotifierRegistry`), M4 (identity row
  lookup via `IdentityMappingService.get_identity`, identity_mapping.py:270).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_notifier.py  (new)
  SessionHook = Callable[[int, ConnectionEvent], Awaitable[None] | None]      # (telegram_id, event)
  class TelegramConnectionNotifier:
      channel: str = "telegram"
      def __init__(self, *, identity_service: Optional["IdentityMappingService"] = None) -> None: ...
      def attach(self, bot_id: str, bot: "Bot") -> None: ...
      def register_session_hook(self, provider_id: str, *, on_completed: Optional[SessionHook] = None,
                                on_revoked: Optional[SessionHook] = None) -> None: ...
      async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None:
          """Resolve (chat_id, bot) per §2; send the per-kind text (parse_mode=None); run the provider's session hook
          for completed / revoked+refresh_failed; log every failure, never raise."""
  def get_or_create_telegram_notifier(app: MutableMapping[str, Any]) -> TelegramConnectionNotifier:
      """app["telegram_connection_notifier"]; registers in ChannelNotifierRegistry on first creation."""
  ```

### Module 8: Needs-auth rendering in Telegram
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` (modify)
- **Responsibility**: §2 "Needs-auth" (wrapper half). Cover both `agent.ask` branches in `_invoke_agent`
  and the direct calls in `handle_tool` (wrapper.py:1950), `handle_skill` (:2124, :2132), and
  `handle_question` (:2230). Preserve their tool/skill arguments and reply ordering. All six call sites must
  use one invocation-local collector helper; never store pending payloads on the shared session or wrapper.
  Return `(response, pending)` from the helper, render the response, then send prompts once. Reset collectors
  on exception/cancellation and test concurrent turns for isolation. Group OAuth requirements by provider and
  union their scopes; device-code payloads are rendered directly after the same private-chat/principal guard.
- **Depends on**: M1, M4, M5, M6 (`render_connect_outcome`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py  (modifies)
  class TelegramAgentWrapper:
      async def _invoke_agent(self, session: TelegramUserSession, question: str, *, memory: Any,
                              output_mode: OutputMode = OutputMode.TELEGRAM, message: Optional[Message] = None,
                              attachments: Optional[List[str]] = None) -> Tuple[Any, List[AuthRequiredPayload]]:          # verified: wrapper.py:1464-1473
          """Return (response, pending) from the helper below; update every caller to unpack, render, then prompt."""
      async def _ask_with_auth_requirements(self, agent: Any, *args: Any, **kwargs: Any) -> Tuple[Any, List[AuthRequiredPayload]]:
          """Run one ask inside collect_auth_requirements; return response and local pending list."""
      async def _send_auth_prompts(self, message: Message, session: TelegramUserSession,
                                   pending: Sequence[AuthRequiredPayload]) -> None:
          """Union OAuth scopes by provider; retain one complete device challenge; principal None → "/login first"; device_code → text; else M5 connect → render_connect_outcome."""
  ```

### Module 9: Generic combined login (`post_auth_actions`)
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_connection.py` (new);
  `telegram/post_auth_jira.py` (modify → preset); `telegram/wrapper.py` (modify login, callbacks, pending attempts,
  finalization and `_init_post_auth_providers`); `telegram/auth.py` (separate primary validation from eager
  post-auth execution); `telegram/connection_notifier.py` (correlated completion dispatch); `telegram/models.py`
  (modify validation).
- **Responsibility**: §2 "Combined login". `ConnectionPostAuthProvider` writes no identity rows or tokens;
  FEAT-773 persists connections and M4 publishes the Telegram link only at final login success.
- **Depends on**: M4, M5, M7 (completion dispatch), FEAT-773 M2/M7 (callback persistence and events).
- **Lifecycle contract**:
  1. `handle_login` must not call `_build_next_auth_url` on an unauthenticated session. Show primary login
     first. After its validated callback, store a candidate separately from `_user_sessions`; strategies must
     not execute secondary providers eagerly. Apply this ordering to Basic, Azure, Google and composite paths.
  2. A pending attempt has an unpredictable `attempt_id`, issuing `bot_id`, Telegram user/private chat,
     validated Navigator principal, configured action order, completion set and expiry. Bind it to the primary
     login attempt; never accept a Navigator user id solely because it appears in WebApp JSON. Re-verify the
     primary credential-to-user validation seam during decomposition; if unavailable, implementing that
     verification is part of M9 before any provider state is minted.
  3. Construct provider state only after primary verification, using M3 PBAC and server-owned scopes. Send
     the next Connect button (URL-based authorization only) in the private chat. A missing required provider,
     denied request, URL construction failure or unsupported auth mode is a required-step failure, never an
     implicit skip. Existing connections may satisfy a step only after checking the candidate principal.
  4. Store `attempt_id`, `bot_id`, `chat_id` and `combined=True` in OAuth `extra_state`. The normal FEAT-773
     callback is the sole code exchanger. Its completion dispatch correlates the stored attempt, principal,
     provider and issuing bot before advancing the chain; duplicate, stale or mismatched callbacks cannot
     activate a session. Do not exchange the same code again through `handle_result` after that callback.
     Retained WebApp code/state submissions must use the same single-consumer callback path.
  5. Once all required steps succeed and optional steps have completed or been skipped, finalize exactly once:
     M4 persists the link, the wrapper promotes the candidate to the active session, then applies deferred
     session hooks and initializes user context. A link-write failure follows AC-3 for this finalized session.
     Notifier delivery errors cannot prevent finalization: dispatch lifecycle handling independently of sending
     the notification. Session hooks must never stamp an unrelated active session during the pending phase.
     Serialize finalization with cancellation/logout for the same attempt, including the awaited link write;
     recheck attempt validity before publication so an in-flight completion cannot revive a cancelled login.
  6. Required failure, cancellation, timeout, logout or superseding `/login` invalidates the pending attempt and
     clears its candidate without publishing a link. It must neither delete nor restore an existing DB link:
     a different login may have legitimately moved ownership. Set attempt expiry to no later than the earliest
     outstanding OAuth state expiry; after restart, missing attempts fail closed and require a new `/login`.
     A late callback cannot promote a discarded candidate. No pending candidate is visible to command principal
     lookup, `_ensure_principal_link`, `_invoke_agent` or eager user-context initialization.
  7. Already completed provider grants remain principal-owned if a later required step fails; do not revoke
     pre-existing or concurrently updated connections as compensation. The rollback guarantee concerns this
     login's session and identity publication. Document that distinction and test it explicitly.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_connection.py  (new)
  class ConnectionPostAuthProvider:                                            # implements PostAuthProvider (post_auth.py:34)
      provider_name: str
      def __init__(self, provider_id: str, *, service: "IntegrationsService", app: Mapping[str, Any],
                   session_hook: Optional[SessionHook] = None) -> None: ...
      async def build_auth_url(self, session: Any, config: Any, callback_base_url: str) -> str:
          """Called only with a verified pending candidate; start_connect(..., channel="telegram",
          principal=candidate_principal, extra_state={chat_id, bot_id, attempt_id, combined=True}, permission_context=trusted_candidate_context).
          Return auth_url; unsupported modes fail the required step. Device-code display belongs only to M8."""
      async def handle_result(self, data: Dict[str, Any], session: Any, primary_auth_data: Dict[str, Any]) -> bool:
          """Compatibility entry for an unconsumed code/state: route through the single callback consumer.
          Verify attempt/principal/provider correlation; never re-exchange a completed callback or publish a link."""

  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py  (modifies)
  class JiraPostAuthProvider(ConnectionPostAuthProvider):                      # verified: post_auth_jira.py:38
      provider_name = "jira"
      def __init__(self, *, service: "IntegrationsService", app: Mapping[str, Any],
                   session_hook: Optional[SessionHook] = None) -> None: ...  # oauth_manager/identity_service/vault_sync params removed (:55-60)
  # REMOVED: _write_identity_records (:206) — M4 owns the telegram row; FEAT-773 owns the token
  ```

### Module 10: Telegram legacy purge
- **Path**: `packages/ai-parrot/src/parrot/auth/oauth2/legacy_audit.py` *(created by FEAT-773 M10)* (modify); Telegram comments/docstrings that describe `jira:oauth:telegram:<telegram_id>` (wrapper.py:1284-1294) (modify)
- **Responsibility**: §2 "Cutover". `SCAN` with `MATCH` (never `KEYS`); batch `UNLINK`; output = counts per
  provider; exit code 2 when the date gate refuses.
- **Depends on**: FEAT-773 M10.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/oauth2/legacy_audit.py  (modifies)
  async def purge_legacy_keys(redis: Any, *, channel: str, providers: Sequence[str], dry_run: bool = True,
                              force: bool = False, now: Optional[datetime] = None) -> Dict[str, int]:
      """Patterns: jira:oauth:{channel}:* and oauth2:{p}:{channel}:* per provider. Refuses (PermissionError) before
      OAUTH2_LEGACY_KEYS_UNTIL unless force; reuse oauth2_base._legacy_window_open(now). Returns {pattern: count}; deletes only when not dry_run."""
  def main(argv: Optional[Sequence[str]] = None) -> int:
      """Existing audit flags + --purge --channel <c> [--confirm] [--force]."""
  ```

### Module 11: Docs
- **Path**: `docs/integrations/telegram-connections.md` (new); `docs/auth/connections.md` *(created by FEAT-773 M10)* (modify)
- **Responsibility**: user commands and aliases; `connection_providers`; the `/login` link and `/logout` unlink;
  PBAC deploy precondition (policy for action/provider/scopes plus the §8 Q1 adapter parity prerequisite);
  needs-auth behaviour; cutover runbook (audit → announce → date → purge); `post_auth_actions` for any provider;
  staged primary-then-secondary login, required-step failure/expiry and the distinction between discarding a
  login attempt and revoking principal-owned connections. `connections.md` gains the Telegram adapter row.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_collector_unbound_is_noop` | M1 | `record_auth_requirement` without a bound collector does nothing |
| `test_collector_sees_appends_from_child_tasks` | M1 | `asyncio.gather` children append into the bound list |
| `test_toolmanager_records_needs_auth` | M1 | both needs-auth exceptions append one payload while bound |
| `test_execute_tool_needs_auth_message` | M2 | `ToolResult(status="authorization_required", metadata={"provider": "jira"})` → message names jira, contains no URL |
| `test_execute_tool_other_statuses_unchanged` | M2 | success → `result.result`; error → `ValueError` as today |
| `test_channel_pbac_fails_closed` | M3 | missing injected evaluator, missing context, identity mismatch, evaluator raises → `False` |
| `test_channel_pbac_uses_navigator_principal` | M3 | `EvalContext` username/user_id = `principal.user_id`, never the Telegram id |
| `test_service_request_less_pbac_branch` | M3 | `request=None` + `permission_context` + `principal` → evaluator consulted; without them → denied |
| `test_link_channel_identity_moves_ownership` | M4 | telegram id linked to user A, then linked to B → only B's row remains |
| `test_channel_identity_lock_shared_by_mutations` | M4 | link/unlink acquire the same deterministic channel-account lock before SQL mutations, on the transaction connection |
| `test_link_channel_identity_rejects_bad_input` | M4 | non-numeric nav id, empty provider id, secret in auth_data → `ValueError` |
| `test_unlink_channel_identity_counts` | M4 | returns deleted rows; 0 when absent |
| `test_login_persists_link_both_paths` | M4 | single-step success and final combined success call `link_channel_identity` once; primary-only combined success does not |
| `test_login_succeeds_when_link_write_fails` | M4 | DB error → login message still sent, flag stays false, warning logged |
| `test_logout_unlinks_before_clear` | M4 | `/logout` calls `unlink_channel_identity("telegram", id)` then clears the session |
| `test_ensure_principal_link_backfills_once` | M4 | authenticated session without flag → one write; second call no-op |
| `test_pending_login_never_backfills` | M4/M9 | pending, failed and expired candidates cannot invoke link backfill, agent execution or command principal lookup |
| `test_connectable_providers_filter` | M5 | MCP providers, manager `None`, and non-allowlisted providers excluded |
| `test_connect_outcomes` | M5 | needs_login / unknown_provider / already_connected / auth_url / denied mapping; service never manufactures device-code instructions |
| `test_scopes_never_from_user` | M5 | explicit commands use defaults; automatic offers union trusted payload scopes; insufficient grants enter consent |
| `test_connect_requires_private_chat` | M6 | group chat → private-chat reply, no service call |
| `test_connect_without_principal_creates_no_state` | M6 | no session principal and no persisted link → "/login first", `start_connect` never called |
| `test_connect_picker_and_callback` | M6 | `/connect` → keyboard of connectable providers; `conn:jira` callback runs the connect routine |
| `test_jira_aliases_route_to_generic` | M6 | `/connect_jira`, `/disconnect_jira`, `/jira_status` hit the generic handlers with provider jira |
| `test_office365_alias_only_when_registered` | M6 | `o365` registered → generic; not registered → today's session-copy handler |
| `test_extra_state_carries_chat_and_bot` | M6 | `extra_state == {"chat_id": …, "bot_id": …}` |
| `test_command_menu_entries` | M6 | menu has connect/disconnect/connections; parity tests updated |
| `test_notifier_targets_state_chat_then_identity_row` | M7 | chat from state; else telegram id from the identity row; unknown bot → warning, no send |
| `test_notifier_texts_per_kind_plain_text` | M7 | completed/revoked/refresh_failed texts, `parse_mode=None`, no token material |
| `test_notifier_never_raises` | M7 | send failure, hook failure, missing identity → logged only |
| `test_jira_session_hook_stamps_and_clears` | M7 | completed → `set_jira_authenticated`; revoked → `clear_jira_auth` |
| `test_invoke_agent_collects_and_prompts` | M8 | tool needs-auth during `ask` → reply sent, then one Connect button per provider |
| `test_auth_prompt_device_code_and_no_principal` | M8 | device_code → code + URI text; no principal → one "/login first" |
| `test_connection_post_auth_build_and_handle` | M9 | provider state starts after validated primary auth; callback exchanged once; correlated completion advances attempt; hooks wait for final success |
| `test_combined_login_required_failure` | M9 | required denial, missing provider, callback failure or expiry discards candidate without link writes; optional failure permits final success |
| `test_combined_login_callback_correlation` | M9 | wrong principal/provider/bot/attempt rejected; duplicate completion idempotent; late completion after logout/restart cannot promote a session |
| `test_combined_login_notifier_send_failure` | M7/M9 | completion still finalizes once when Telegram notification delivery raises |
| `test_jira_post_auth_preset_compat` | M9 | `JiraPostAuthProvider.provider_name == "jira"`; YAML `post_auth_actions: [{provider: jira}]` still registers |
| `test_post_auth_any_registered_provider` | M9 | `post_auth_actions: [{provider: o365}]` registers when `o365` is in the registry; unknown → warning |
| `test_purge_dry_run_and_date_gate` | M10 | dry run deletes nothing; before the date → refused unless `--force`; counts only, no values |
| `test_purge_deletes_only_channel_keys` | M10 | `jira:oauth:telegram:*` and `oauth2:*:telegram:*` deleted; `…:web:*`, `…:msteams:*` untouched |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_telegram_login_link_resolves` | plain `/login` → `telegram` row → FEAT-773 `IdentityPrincipalResolver.resolve("telegram", id)` returns the principal; `/logout` → `None` |
| `test_db_concurrent_channel_identity_links` | real DB, separate connections: competing first links and relinks leave exactly one owner; failed replacement rolls back; link/unlink serialize |
| `test_e2e_combined_login_from_unauthenticated` | fresh session → primary WebApp (no provider state) → validated primary callback → secondary authorization → callback → one link and active session; cover Basic/Azure/Google/composite and rejection of unsupported authorization modes |
| `test_e2e_combined_required_failure_no_link` | primary success followed by required failure/expiry → no new resolver-visible identity, no active candidate; pre-existing or concurrently moved link untouched; completed grants remain principal-owned |
| `test_e2e_telegram_connect_any_provider` | `/connect <dummy descriptor provider>` → callback with the state → `TelegramConnectionNotifier` message in the issuing chat → tool resolves |
| `test_e2e_telegram_jira_parity` | (FEAT-773 test, updated) `/connect_jira` alias → callback → notifier → Jira tool resolves; `<jira>` prompt block present |
| `test_e2e_needs_auth_button` | Jira tool without connection → LLM sees the needs-auth message → Telegram reply then Connect button |
| `test_e2e_cross_channel_from_telegram` | connect on Telegram, listed by `list_for_principal` and resolved on web for the same principal |
| `test_e2e_unlinked_user_forced_reconnect` | legacy `jira:oauth:telegram:<id>` with no identity row → no resolution; "/login first" on `/connect` |

| `test_telegram_restart_retains_link` | clear in-memory sessions, retain DB identity: connection commands resolve the same Navigator principal without /login; roles remain empty unless validated claims exist |
| `test_telegram_only_startup_registers_notifier` | start only Telegram; registry has one Telegram notifier, repeated starts attach without duplicate registration |
| `test_telegram_disconnect_routes_revoked` | real service with shared evaluator → manager.revoke(channel="telegram", principal=...) → Telegram notifier and Jira session clear; web default still works |
| `test_all_telegram_ask_paths_collect` | both _invoke_agent branches, handle_tool, both handle_skill branches and handle_question surface one prompt after reply; concurrent turns and cancellation do not leak payloads |
| `test_telegram_scope_union_upgrade` | automatic payloads union scopes; insufficient active grant requires consent; explicit commands use defaults |

### Validation Contract

The runners below are the existing regression baseline. Task decomposition must additionally bind every new
test named above to a package-local test path and include those paths in the feature validation contract.
The M4 concurrency and M9 fresh-login/rollback integration tests are mandatory evidence, not optional mocks;
missing DB fixtures or credentials must be reported as blocked validation, never counted as a pass.

runners:
- kind: pytest
  tests:
  - packages/ai-parrot/tests/unit/test_telegram_jira_commands.py
  - packages/ai-parrot/tests/unit/test_telegram_office365_commands.py
  - packages/ai-parrot/tests/unit/test_post_auth_jira.py
  - packages/ai-parrot/tests/unit/test_wrapper_combined_auth.py
  - packages/ai-parrot/tests/unit/test_identity_mapping.py
  - packages/ai-parrot/tests/unit/test_auth_required.py
  - packages/ai-parrot/tests/unit/clients/test_tool_error_message.py
  - packages/ai-parrot-integrations/tests/integrations/telegram/test_wrapper_register_command_menu.py
  - packages/ai-parrot-integrations/tests/integrations/telegram/test_integration_menu_parity.py
  - packages/ai-parrot-integrations/tests/test_telegram_integration.py
  - tests/unit/integrations/oauth2/test_service.py
  - tests/integration/oauth2/test_e2e_telegram_regression.py
  - packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py
  markers: none

### Test Data / Fixtures
```python
@pytest.fixture
def tg_session() -> TelegramUserSession:   # authenticated, nav_user_id="1042", telegram_id=88123
    ...

@pytest.fixture
def fake_identity_service():               # in-memory rows {(provider, provider_user_id): nav_user_id}; link/unlink/get_identity
    ...

@pytest.fixture
def fake_integrations_service():           # records start_connect/disconnect/status calls; configurable outcome / PBAC denial
    ...

@pytest.fixture
def provider_registry():                    # OAuth2ProviderRegistry._reset(); jira + dummy descriptor + an "mcp:x" provider + one with manager None
    ...

@pytest.fixture
def fake_bot():                             # aiogram Bot double recording send_message(chat_id, text, parse_mode, reply_markup)
    ...

@pytest.fixture
def fake_permission_evaluator():            # async callable(context, attributes); allow/deny/raise modes; not production parity evidence
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC-1 (G1)** After a successful Telegram `/login` (single-step or combined, any strategy), `auth.user_identities` holds exactly one `telegram` row for that Telegram id, owned by the logged-in Navigator user; linking the same Telegram id to another user moves the row. Real-DB tests prove exclusive ownership under competing first links/relinks and serialized unlink, using the M4 shared transaction-lock protocol.
- [ ] **AC-2 (G1)** `/logout` deletes the `telegram` row before clearing the session; afterwards FEAT-773's resolver returns `None` for that Telegram id and no connection resolves from Telegram.
- [ ] **AC-3 (G1)** A failed link write never fails the login; the session flag stays false and the next connection command or agent turn retries once (`_ensure_principal_link`).
- [ ] **AC-4 (G2)** `/connect [<provider>]`, `/disconnect <provider>`, `/connections` work for every connectable provider; MCP providers, providers without a manager, and providers outside `connection_providers` are never offered or accepted; user input never sets scopes.
- [ ] **AC-5 (G2)** `/connect_jira`, `/disconnect_jira`, `/jira_status` behave as aliases; `/connect_office365` family aliases the generic commands only when `o365` is registered, otherwise behaves exactly as today.
- [ ] **AC-6 (G2)** No connection command creates OAuth state for a user without a resolvable principal, or in a non-private chat.
- [ ] **AC-7 (G3)** Telegram connect/disconnect are evaluated by the FEAT-775 shared context API against the Navigator principal; with no PDP, no evaluator, or an evaluator error the command is refused with the "not allowed" message and no OAuth state is created.
- [ ] **AC-8 (G4)** `AbstractClient._execute_tool` returns the needs-auth message (provider named, no URL) for `status="authorization_required"`; all other statuses behave as before.
- [ ] **AC-9 (G4)** When a tool needs auth during a Telegram turn, the agent's reply is sent first, then one Connect button per distinct provider (fresh OAuth state carrying this `chat_id`/`bot_id`); device-code payloads show code and URI; unlinked users get one "/login first" line.
- [ ] **AC-10 (G5)** `connection.completed`, `connection.revoked`, `connection.refresh_failed` for any provider produce one plain-text Telegram message through the issuing bot; a notifier failure never fails the callback; `TelegramOAuthNotifier`, `TelegramJiraNotifierAdapter` and the app keys `telegram_jira_session_stamper` / `jira_oauth_notifier` no longer exist in `packages/`.
- [ ] **AC-11 (G5)** The `<jira>` user-context block appears after a Jira connection and disappears after disconnect/revoke, through the registered session hook.
- [ ] **AC-12 (G6)** `post_auth_actions` registers any provider present in `OAuth2ProviderRegistry`; `JiraPostAuthProvider` is a preset of `ConnectionPostAuthProvider` and writes no identity rows or tokens. A fresh unauthenticated login completes the staged flow without pre-primary provider state. All required actions succeed before link publication/session promotion; required failure, cancellation or expiry never publishes a link or backfills the candidate and leaves any pre-existing/concurrently moved link untouched. Callback correlation and duplicate/late handling satisfy M9.
- [ ] **AC-13 (G7)** `python -m parrot.auth.oauth2.legacy_audit --purge --channel telegram` is a dry run without `--confirm`, refuses before `OAUTH2_LEGACY_KEYS_UNTIL` without `--force`, deletes only the documented Telegram Redis legacy keys, excludes vault secrets, rejects invalid/missing cutoff for destructive execution unless forced, and prints counts only.
- [ ] **AC-14** `parrot/auth/pending.py` exists once with the FEAT-775 M5 contract; `grep -rn "def collect_auth_requirements" packages/` matches one definition.
- [ ] **AC-15** `docs/integrations/telegram-connections.md` exists and documents the PBAC deploy precondition and the cutover runbook.
- [ ] **AC-16** The Validation Contract passes; `ruff check` clean on touched files; no `print`, no `requests`/`httpx`; Telegram replies built by this feature use `parse_mode=None`.

- [ ] **AC-16** A bot restart retains persisted Telegram principal resolution without another login; unlinked users still fail closed and no roles are fabricated.
- [ ] **AC-17** Telegram-only startup registers the generic notifier once. Disconnect propagates Telegram channel/principal through revoke and clears the Jira session hook.
- [ ] **AC-18** All six ask sites listed in M8 collect requirements; concurrent turns and cancellation cannot share pending prompts. Automatic scope requests match FEAT-775's union/upgrade rules.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified 2026-10-30 against `dev` @ `370a62d9b`, i.e. **before**
> FEAT-773 lands. FEAT-773 modifies `jira_commands.py`, `integrations/manager.py`, `service.py`,
> `tools/manager.py` and creates `core/auth/notifiers.py`, `legacy_audit.py`, `principal.py`, `events.py`:
> `/sdd-task` MUST re-verify every anchor below after FEAT-773 merges. Symbols marked *(FEAT-773)* exist only
> once FEAT-773 is merged — their contract is `sdd/specs/delegated-auth-connections.spec.md` §2/§3.

### Verified Imports
```python
from parrot.clients.base import AbstractClient                                   # verified: clients/base.py (_execute_tool :1619)
from parrot.tools.abstract import ToolResult                                     # verified: clients/base.py:55 imports it from ..tools.abstract
from parrot.tools.manager import ToolManager                                     # verified: tools/manager.py (needs-auth branch :2273-2290)
from parrot.auth.exceptions import AuthorizationRequired                         # verified: auth/exceptions.py:12
from parrot.auth.permission import PermissionContext, UserSession, to_eval_context  # verified: permission.py:81, :21, :209
from parrot.auth.oauth2.registry import OAuth2Provider, OAuth2ProviderRegistry   # verified: registry.py:20, :69 (all() :117)
from parrot.auth.oauth2.service import IntegrationsService                       # verified: service.py:74 (_check_pbac :490)
from parrot.services.identity_mapping import IdentityMappingService              # verified: identity_mapping.py:136 (ai-parrot-server)
from parrot.integrations.core.auth.post_auth import PostAuthProvider, PostAuthRegistry  # verified: post_auth.py:34, :92
from parrot.integrations.telegram.auth import TelegramUserSession                # verified: telegram/auth.py:44
from parrot.integrations.telegram.models import TelegramAgentConfig, PostAuthAction  # verified: telegram/models.py:42, :23
from parrot.integrations.telegram.jira_commands import register_jira_commands, TelegramOAuthNotifier  # verified: jira_commands.py:156, :192
from parrot.integrations.telegram.office365_commands import register_office365_commands  # verified: office365_commands.py:106
from parrot.integrations.telegram.post_auth_jira import JiraPostAuthProvider     # verified: post_auth_jira.py:38
from aiogram import Router, Bot                                                   # verified: jira_commands.py:20, :26
from aiogram.filters import Command                                               # verified: jira_commands.py:21
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message     # verified: jira_commands.py:22
# external (navigator-auth 0.28.7, .venv)
# FEAT-773 (merged in PR #1897)
from parrot.auth.principal import Principal, resolve_principal                   # (FEAT-773 M1)
from parrot.auth.credentials import AuthRequiredPayload                          # (FEAT-773 M5)
from parrot.auth.oauth2.events import ChannelNotifier, ChannelNotifierRegistry, ConnectionEvent  # (FEAT-773 M4)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/clients/base.py
async def _execute_tool(self, tool_name: str, parameters: Dict[str, Any], tool_context: Optional[Dict[str, Any]] = None) -> Any  # :1619
#   :1660 result = await self.tool_manager.execute_tool(tool_name, merged, permission_context=perm_ctx)
#   :1661 if isinstance(result, ToolResult):  :1662 if result.status == "error": raise ValueError(...)  :1667 return result.result

# packages/ai-parrot/src/parrot/tools/manager.py
#   :2274 except (AuthorizationRequired, CredentialRequired) as auth_exc:
#   :2290 metadata=payload.model_dump(); M1 records that payload before return.

# packages/ai-parrot/src/parrot/auth/oauth2/service.py (current, before FEAT-775 additions)
# list_for_principal(self, user_id, request=None) :81; start_connect(..., *, channel, principal, scopes, request, extra_state) :288
# status(self, user_id, provider_id, request=None) :360; disconnect(self, user_id, provider_id, request=None) :371
# _check_pbac(self, request, action, provider_id=None, scopes=None) :471; scopes is positional-compatible.
# revoke(channel=_WEB_CHANNEL, user_id=user_id) :393; FEAT-775 adds principal/channel propagation.
# await abac.is_allowed(request, ctx) :509; ctx = action + optional provider/scopes.

# packages/ai-parrot-server/src/parrot/services/identity_mapping.py
_UPSERT_SQL  # :43-53  ON CONFLICT (user_id, auth_provider, provider_user_id) WHERE provider_user_id IS NOT NULL
_DELETE_SQL  # :92-95  WHERE user_id = $1::text::bigint AND auth_provider = $2
class IdentityMappingService:                                                    # :136
    def __init__(self, db_pool: Any, identity_store: Optional["IdentityStore"] = None) -> None  # :156
    async def upsert_identity(self, *, nav_user_id, auth_provider, provider_user_id, auth_data, display_name=None,
                              email=None, token=None) -> None                     # :173  validation :207-225
    async def get_identity(...)                                                   # :270
    async def delete_identity(self, nav_user_id: str, auth_provider: str) -> None # :307

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py
@dataclass class TelegramUserSession:                                            # :44  telegram_id (:47), nav_user_id (:52), nav_email,
    #   authenticated, jira_account_id/jira_email/jira_display_name/jira_cloud_id (:72-76), post_login_ran (:91)
    def set_jira_authenticated(...) / clear_jira_auth() / set_o365_authenticated(...) / clear_o365_auth() / clear_auth()  # :139, :170, :180, :192, :199
class BasicAuthStrategy(AbstractAuthStrategy): async def handle_callback(self, data, session) -> bool  # :377, :456 (no identity write)

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py
async def connect_jira_handler(message, oauth_manager) -> None                  # :50  raw telegram id (:66), extra_state={"chat_id"} (:79-82)
async def disconnect_jira_handler(message, oauth_manager, session_clearer=None)  # :90
async def jira_status_handler(message, oauth_manager)                            # :128
def register_jira_commands(router, oauth_manager, session_clearer=None) -> None  # :156  Command("connect_jira") :187
class TelegramOAuthNotifier: notify_connected(chat_id, display_name, site_url) / notify_failure(chat_id, reason)  # :192

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/office365_commands.py
SessionProvider = Callable[[int], TelegramUserSession]                           # :18
def register_office365_commands(router, session_provider) -> None                # :106  connect copies /login token (:59-63)

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py
class JiraPostAuthProvider:  provider_name = "jira" (:53); __init__(oauth_manager, identity_service, vault_sync) (:55-60);
    async def build_auth_url(...) (:68, nav_user_id → extra_state :102-107); async def handle_result(...) (:123, handle_callback :156);
    async def _write_identity_records(...) (:206, telegram row :218-231)

# packages/ai-parrot-integrations/src/parrot/integrations/core/auth/post_auth.py
class PostAuthProvider(Protocol): provider_name; build_auth_url(session, config, callback_base_url) -> str; handle_result(data, session, primary_auth_data) -> bool  # :34-90
class PostAuthRegistry: register / get / providers / __contains__ / __len__      # :92-153

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py
_KNOWN_POST_AUTH_PROVIDERS = frozenset({"jira"})                                 # :16  (warning at :410-415)
class TelegramAgentConfig: tenant (:77), auth_methods (:97), post_auth_actions (:111), from_dict (:235)  # :42

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper:
    self._platform_commands (:176); self._user_sessions (:178); self._post_auth_registry (:198)
    def _add_platform_commands(self, entries) -> None                            # :387
    def _register_jira_commands(self) -> None                                    # :400  app["jira_oauth_manager"] gate :408; stamper :439-473
    def _register_office365_commands(self) -> None                               # :475  gated on "oauth2" in auth_methods :481-482
    def _init_post_auth_providers(self) -> None                                  # :557  db_pool = app.get("authdb") or app.get("database") :583
    def _get_user_session(self, message) -> TelegramUserSession                  # :1099
    def _build_permission_context(session, chat_id=None, bot_id=None, tenant_id=None)  # :1277  UserSession(user_id=str(telegram_id)) :1310-1314
    async def _invoke_agent(self, session, question, *, memory, output_mode=OutputMode.TELEGRAM, message=None, attachments=None) -> Any  # :1464 (agent.ask :1533, :1560)
    async def handle_login(self, message) -> None                                # :2244
    async def handle_logout(self, message) -> None                               # :2310  session.clear_auth() :2323
    async def handle_web_app_data(self, message) -> None                         # :2329  single-step success :2362
    async def _handle_combined_auth(self, message, data, session) -> None        # :2379  basic_ok :2404
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_persist_principal_link` | `IdentityMappingService.link_channel_identity` | method call | `identity_mapping.py:136` (class) |
| FEAT-775 context API | injected PDP adapter | action/provider/scopes parity | `service.py:471–510`; FEAT-775 §2 gate |
| `ConnectionCommandService` | `IntegrationsService.start_connect/disconnect/status/list_for_principal` *(FEAT-773 signatures)* | method call | `service.py:74` |
| `TelegramConnectionNotifier` | `ChannelNotifierRegistry` *(FEAT-773)* | `register(notifier)` | FEAT-773 §3 M4 |
| `_invoke_agent` collector | `collect_auth_requirements` | context manager | M1 |
| `ConnectionPostAuthProvider` | `PostAuthRegistry.register` | Protocol | `post_auth.py:109` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.auth.pending`, `collect_auth_requirements`, `record_auth_requirement`~~ — created by FEAT-775 M5 or this spec's M1, whichever merges first.
- `permission_context` / injected evaluator do not exist yet: FEAT-775 owns them; FEAT-776 consumes them. No `channel_pbac.py` is created.
- ~~`IdentityMappingService.link_channel_identity` / `unlink_channel_identity` / a delete-by-`provider_user_id` query~~ — only `delete_identity(nav_user_id, auth_provider)` exists (identity_mapping.py:307).
- ~~`ResourceType.INTEGRATION`~~ — not in navigator-auth 0.28.7 (§8 Q1).
- ~~A Telegram identity write in any auth strategy's `handle_callback`~~ — none (auth.py:456-506 et al.); only `JiraPostAuthProvider._write_identity_records`.
- ~~Telegram handling of `authorization_required` / `AuthorizationRequired`~~ — none anywhere under `integrations/telegram/` (grep, 2026-10-30).
- ~~`AIMessage.tool_calls[*].result` carrying the needs-auth `ToolResult`~~ — `_execute_tool` returns `result.result` (`None`); `ToolCall` (models/basic.py:23) has `result`/`error` only.
- ~~Telegram commands `/connect`, `/disconnect`, `/connections`~~ — no `Command("connect")` etc. under `integrations/telegram/` today.
- ~~`ConnectionCommandService`, `ConnectOutcome`, `TelegramConnectionNotifier`, `ConnectionPostAuthProvider`, `register_connection_commands`, `purge_legacy_keys`, `TelegramAgentConfig.connection_providers`, `TelegramUserSession.principal_link_persisted`~~ — new here.
- ~~`ConnectionChannel` protocol~~ — absent (FEAT-773 proposal §3.4); this spec does not create it: FEAT-773's `ChannelNotifier` plus M5's command core cover the role.

### Edit Sites (Blueprint Anchors)

Verified against `70b0fb7d2b` (2026-10-31, FEAT-773 merged). These full-line anchors supersede historical
line references in the original narrative; re-verify after FEAT-775 lands. Shared service and PDP adapter
changes are FEAT-775-owned prerequisites, not Telegram edit sites.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/auth/pending.py` | CREATE (or verify, if FEAT-775 merged) | — | — | — |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | `        except (AuthorizationRequired, CredentialRequired) as auth_exc:` | `packages/ai-parrot/src/parrot/tools/manager.py:2274` | 1 |
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | `            if isinstance(result, ToolResult):` | `packages/ai-parrot/src/parrot/clients/base.py:1661` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/legacy_audit.py` | MODIFY | `def main(argv: Optional[Sequence[str]] = None) -> int:` | `packages/ai-parrot/src/parrot/auth/oauth2/legacy_audit.py:79` | 1 |
| `packages/ai-parrot-server/src/parrot/services/identity_mapping.py` | MODIFY | `    async def delete_identity(` | `packages/ai-parrot-server/src/parrot/services/identity_mapping.py:307` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/connections.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py` | MODIFY | `class TelegramJiraNotifierAdapter(_JiraAdapterBase):` | `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py:38` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | `    async def _start_telegram_bot(self, name: str, config: TelegramAgentConfig):` | `packages/ai-parrot-integrations/src/parrot/integrations/manager.py:331` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_commands.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_notifier.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_connection.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py` | MODIFY | `def register_jira_commands(` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py:192` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/office365_commands.py` | MODIFY | `def register_office365_commands(` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/office365_commands.py:106` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py` | MODIFY | `class JiraPostAuthProvider:` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py:39` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py` | MODIFY | `    post_login_ran: bool = field(default=False, repr=False, compare=False)` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py:91` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` | MODIFY | `    post_auth_actions: List[PostAuthAction] = field(default_factory=list)` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py:111` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` | MODIFY | `_KNOWN_POST_AUTH_PROVIDERS = frozenset({"jira"})` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py:16` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `    def _register_jira_commands(self) -> None:` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:400` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `    def _register_office365_commands(self) -> None:` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:480` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `    def _init_post_auth_providers(self) -> None:` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:562` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY (M9: remove pre-primary provider URL creation) | `            next_url, required = await self._build_next_auth_url(session)` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:2281` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `    async def _invoke_agent(` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:1469` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `        old_name = session.display_name` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:2327` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `        success = await self._auth_strategy.handle_callback(data, session)` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:2367` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY (M9: candidate only; no link publication here) | `        basic_ok = await self._auth_strategy.handle_callback(basic_data, session)` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:2409` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY (M9: discard candidate, preserve DB link) | `        if failures_required:` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:2450` | 1 |
| `docs/integrations/telegram-connections.md` | CREATE | — | — | — |
| `docs/auth/connections.md` | MODIFY | `# Delegated OAuth2 connections` | `docs/auth/connections.md:1` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `    async def handle_tool(self, message: Message) -> None:` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:1895` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `    async def handle_skill(self, message: Message) -> None:` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:2051` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `    async def handle_question(self, message: Message) -> None:` | `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:2203` | 1 |
| `packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py` | MODIFY | `async def test_notifier_adapters_delegate() -> None:` | `packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py:29` | 1 |
| `tests/integration/oauth2/test_e2e_telegram_regression.py` | MODIFY | `async def test_e2e_telegram_jira_parity() -> None:` | `tests/integration/oauth2/test_e2e_telegram_regression.py:22` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Principal from trusted session or persisted identity, never message text.** Absorb `_telegram_principal`
  with the restart fallback; a provider argument is the only user input, and it
  is matched against the connectable list.
- **Fail closed everywhere a principal or PDP is missing** — no OAuth state, no Telegram-id-keyed fallback (U3).
- **Channel ids are delivery data only.** `chat_id` / `bot_id` travel in `extra_state` for the notifier; they are
  never keys (codex S2).
- **Plain text in Telegram** (`parse_mode=None`) for every reply this feature builds (jira_commands.py:57-61).
- **Lazy imports of server services from integrations** (pattern: wrapper.py:600-611) so bots without the server
  package still import.
- **Notifier contract**: log, never raise (FEAT-773 publisher contract); idempotent on duplicate events.

### Known Risks / Gotchas
- **PBAC deploy precondition (G3).** Deploying S-2 without an `integration:connect` / `integration:disconnect`
  policy disables `/connect` and `/connect_jira` on Telegram. The docs and the release note must say so; the
  refusal message points to an administrator.
- **Logout semantics change.** Today `/logout` can leave Jira usable through the persisted identity link. After S-2
  `/logout` unlinks, so connections stop resolving from that Telegram account until the next `/login` — intended.
- **Same Telegram id, different Navigator user.** `link_channel_identity` moves the row; the previous user's
  connections become unreachable from that Telegram account (they remain on other channels). All channel
  mutations must use M4's shared lock, including absent-row cases; SQL transaction atomicity alone is insufficient.
- **Combined-login publication boundary.** Primary success creates a pending candidate, not a resolver-visible
  link. Required failure discards only that attempt; it must not unlink a newer owner. No lazy backfill or
  session hook may bypass this boundary. The staged UI replaces the pre-authentication secondary redirect.
- **Unlinked legacy users (U3).** Users who connected Jira without `/login` lose it at cutover; run
  `legacy_audit` before the date and announce.
- **Multi-bot deployments.** The notifier must send through the bot that issued the flow (`bot_id` in state);
  revoke/refresh events have no state — the notifier falls back to the bot recorded at the last `/connect` for
  the principal, else the only attached bot, else warns.
- **`refresh_failed` and `revoked` are dispatched by `event.channel`** (FEAT-773): a refresh that fails during a
  web call is not announced on Telegram. Accepted for v1.
- **`clients/base.py` is the foundation file.** M2 is a single new branch approved by the user on 2026-10-30;
  any wider change there is out of scope.
- **Concurrent edits.** FEAT-773 (prerequisite) and FEAT-775 both touch `tools/manager.py`; FEAT-775 also adds
  `pending.py`. Re-verify anchors at task time; never create a second collector.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `navigator-auth` | ≥ 0.28.7 (in `.venv`) | shared PDP adapter (FEAT-775); `auth.user_identities` |
| `aiogram` | existing | commands, inline keyboards, callback queries |

---

## 8. Open Questions

- [x] **Q1 — Shared permission API and policy inputs.** FEAT-775 M3/M7 owns `permission_context` plus
  injected evaluator, preserving FEAT-773 action/provider/scopes semantics; FEAT-776 consumes it. No new
  integration resource type or agent-handler policy mapping is selected here.
  **Validation gate:** installed navigator-auth `abac/pdp.py:549` accepts `(request, session, ...)`, whereas
  merged `service.py:509` passes the attributes dict as the second positional argument. FEAT-775 must verify
  the deployed adapter and prove web/channel parity with real allow/deny policies before dependent tasks
  start. Do not mistake mocked `is_allowed` tests for that evidence or silently choose a resource mapping.

- [ ] **Q2 — Codex S3: legacy rollback.** Should the Telegram purge keep a rollback path (e.g. export the
  `jira:oauth:telegram:*` keys to an encrypted backup before deletion) or is the date gate + dry run enough? —
  *Owner: Jesus*.
- [x] **Q3 — Legacy cutoff.** FEAT-773 settled `OAUTH2_LEGACY_KEYS_UNTIL` at S-1 production deploy + 30 days.
  M10 reuses `_legacy_window_open`; operators record the actual deploy timestamp and audit counts. No new
  date decision or acceptable-unbound threshold blocks spec decomposition.

- [x] **Telegram `/connect` without a PDP** — *Resolved at spec time (2026-10-30)*: fail closed, same as web;
  shipping the policy is a deploy precondition (G3, AC-7, §7).
- [x] **`/connect_office365`** — *Resolved at spec time*: alias of `/connect o365` only when an `o365` provider is
  registered; otherwise the session-copy handlers stay unchanged (G2, AC-5).
- [x] **Needs-auth surfacing** — *Resolved at spec time*: request-scoped collector **and** fix
  `AbstractClient._execute_tool` so the LLM receives a needs-auth message instead of `None` (M1, M2, AC-8/9).
  This also answers FEAT-775 §8 Q3.
- [x] **U3 unlinked Telegram users** — *Resolved in proposal*: force re-connect; no channel-keyed fallback.
- [x] **Telegram login links to a platform user** — *Resolved in brainstorm/FEAT-773*: `TelegramUserSession.nav_user_id`;
  S-2 persists it on every login (M4).
- [x] **JiraToolkit on the broker seam** — *Resolved by FEAT-773*: owned by FEAT-773 M7, not S-2.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration doc** (the FEAT-773 proposal,
> S-2 row). Model: `gpt-5.6-luna` · Status: completed · Transcript: `sdd/state/FEAT-776/design_research/`.
> The reviewer answered at the scale of the whole FEAT-773 initiative; suggestions that belong to S-1 are
> rejected here as out of scope (FEAT-773's own §9 already disposed of the same points).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make Jira persistence an explicit principal-aware store adapter (architecture) | REJECT | S-1 scope; FEAT-773 M2/M7/M8 adopt `CredentialStore` with durable-first writes. | — |
| S2 | Resolve a typed principal once; keep channel identity separately (architecture) | CONFIRM | Commands, needs-auth prompts and post-auth build one `Principal` from the session; `chat_id`/`bot_id` are delivery data only. | §2 M4/M6, §7 |
| S3 | Specify migration semantics, metric and rollback before cutover (risk) | CONFIRM (partly) / ESCALATE | Date gate, dry run, counts, channel-only patterns and exclusive relink adopted; "don't make forced reconnect the only recovery" rejected (U3 resolved); rollback backup escalated. | §2 M10, M4; §8 Q2 |
| S4 | FEAT-144 reversal is a session-hydration migration (architecture) | REJECT | S-1 scope (FEAT-773 M6 hydration from connections). | — |
| S5 | Don't expose the whole OAuth registry through channel commands (api) | CONFIRM | Connectable filter (manager present, not `mcp:*`, allowlist), PBAC before state, server-owned scopes. | §2 M5, AC-4 |
| S6 | Centralize needs-auth mapping, keep device-code fields (api) | CONFIRM | Mapping stays FEAT-773 M5; the Telegram renderer consumes `AuthRequiredPayload` incl. device-code fields. | §2 M8, AC-9 |
| S7 | Adapt JiraToolkit to the broker seam as client construction (architecture) | REJECT | Owned by FEAT-773 M7. | — |
| S8 | Keep provider behaviour in subclasses until stable (alternative) | REJECT | S-1 decision (FEAT-773 §9 S10); S-2 consumes whatever the registry holds. | — |
| S9 | Request-scoped MCP credential resolution (risk) | REJECT | S-1 / S-4 scope. | — |
| S10 | Event ordering and delivery failure semantics (risk) | CONFIRM | Telegram notifier logs, never raises, idempotent; event emission order stays FEAT-773's. | §2 M7, §7 |
| S11 | Cross-channel migration matrix before deleting legacy routes (testing) | CONFIRM | Telegram rows of the matrix: link/unlink, unlinked forced reconnect, cross-channel reuse, purge isolation. | §4 Integration Tests |

Summary: **6** confirmed (one partly) · **5** rejected · **1** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-776-connections-telegram` off `origin/dev` **after FEAT-773 is
  merged**; the `sdd-coder` engine gives each task its own sub-worktree.
- **Module dependency graph** (edge = imports / needs):
  - M5 → M3 (consumes FEAT-775 `permission_context` API).
  - M6 → M4 (`principal_for_session`, `_ensure_principal_link`, trusted context builder), M5 (`ConnectionCommandService`), M7 (deletes
    `TelegramOAuthNotifier` only after the notifier replaces the FEAT-773 adapter).
  - M8 → M1 (`collect_auth_requirements`), M4, M5, M6 (`render_connect_outcome`).
  - M9 → M4 (identity row moves to the link path), M5.
    M9 also depends on M7 for correlated completion dispatch; final identity publication belongs to M4/M9 together.
  - M11 → all.
  - M1, M2, M3, M4 and M10 have no module edges between them; M3 remains gated on Q1. M7 follows M4 as
    declared in its module contract. M9 must not land early link publication while awaiting completion wiring.
- **Shared files** (tasks serialized): `telegram/wrapper.py` (M4, M6, M7, M8, M9); `telegram/models.py` (M6, M9);
  `telegram/auth.py` (M4, M9); `telegram/connection_notifier.py` (M7, M9);
  `telegram/jira_commands.py` (M6, M7 via the notifier removal — M6 owns the edit).
- **Exclusive resources**: none (no migrations: `auth.user_identities` is unchanged; no lockfile change).
- **Cross-feature dependencies**: **FEAT-773 merged** (hard). FEAT-775 (S-3b) shares `parrot/auth/pending.py`
  — whichever merges first creates it (§2 "Shared with FEAT-775"); FEAT-776 M3 depends on FEAT-775 M3/M7; FEAT-775 consumes the M2 message behavior after it lands.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-30 | Jesus Lara (with Claude Opus 5.5) | Initial draft — S-2 of FEAT-773 |
| 0.2 | 2026-10-30 | Codex | Review corrections: serialized channel ownership, staged combined login, deferred link publication/rollback isolation, mandatory regression evidence and explicit Q1 gate. Addresses design issues `b5a13e2c4c23`, `aff9e16ebca9`, `b8c17b33af2a`; runtime implementation remains future work. |
| 0.3 | 2026-10-31 | Codex | Reconcile merged FEAT-773 contracts; choose FEAT-775-owned permission context API; fix Telegram revoke routing, persisted identity fallback, scope union, device-code boundary, all ask paths, startup registration and Redis-only cutover. |

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
**Status**: draft
**Target version**: 1.3.0

> **Source**: proposal `sdd/proposals/delegated-auth-connections.proposal.md` (FEAT-773, `accepted`) §6 row
> "S-2 Telegram migration", and `sdd/specs/delegated-auth-connections.spec.md` (FEAT-773, S-1) §1 Non-Goals
> ("Generic `/connect <provider>` channel commands, `ConnectionChannel` protocol work and the Telegram legacy-key
> cutover — **S-2**"). No S-2-specific brainstorm exists; the FEAT-773 proposal is the exploration document.
> **Hard prerequisite: FEAT-773 merged.** Everything below consumes FEAT-773's `Principal`, `PrincipalResolver`,
> principal-keyed `AbstractOAuth2Manager`, `IntegrationsService` (channel parameter), `ChannelNotifier` registry,
> `ConnectionEvent`, `AuthRequiredPayload` and `legacy_audit`. Sibling consumer spec **FEAT-775**
> (`connections-msteams`, S-3b) shares two pieces with this one — see §2 "Shared with FEAT-775".

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-773 makes every OAuth2 connection principal-keyed and channel-neutral, and gives Telegram the minimum for
parity: a Jira notifier adapter, a "/login first" reply in `/connect_jira`, and a date-gated dual read of
`jira:oauth:telegram:<telegram_id>`. Five gaps remain on Telegram (verified 2026-10-30 at `370a62d9b`):

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
  becomes a preset of the generic provider.
- **G7 — Telegram legacy cutover.** After `OAUTH2_LEGACY_KEYS_UNTIL` (FEAT-773), a guarded purge deletes the
  Telegram legacy keys; the raw-`telegram_id` credential paths and comments are removed.

### Non-Goals (explicitly out of scope)

- Anything FEAT-773 owns: the principal-keyed engine, `IntegrationsService` channel parameter and
  `list_for_principal`, `/api/v1/connections*`, `AuthRequiredPayload`, the generic callback, the legacy dual-read
  window, `IdentityPrincipalResolver`, `JiraToolkit` on the broker seam (FEAT-773 M7 — the proposal's S-2 row
  listed it, the S-1 spec absorbed it).
- Teams (FEAT-775), web panel / WS push / auto-retry / Slack / O365 store consolidation (S-3a), CLI and local MCP
  (S-4). This spec does not migrate Teams onto the channel-neutral command core it creates (FEAT-775 §8 Q2 may).
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
FEAT-775), a request-less PBAC entry point and the `_execute_tool` message fix; the server identity service gains
link/unlink; the channel-neutral half of the commands lands in `integrations/core/auth/` so other channels can reuse it.

**Principal link (M4).** `IdentityMappingService.link_channel_identity()` writes the channel row in one
transaction: delete every `(auth_provider, provider_user_id)` row owned by a *different* Navigator user, then the
existing upsert. `unlink_channel_identity(auth_provider, provider_user_id)` deletes by the channel id. The wrapper
calls a single `_persist_principal_link(session)` after both login success sites (single-step wrapper.py:2362,
combined wrapper.py:2404) — strategy-agnostic — and `unlink` in `handle_logout` before `session.clear_auth()`. A
`principal_link_persisted` flag on `TelegramUserSession` makes `_ensure_principal_link(session)` a once-per-session
backfill, called from the connection commands and `_invoke_agent`. A failed write never fails the login: the user
is told connections are unavailable, and resolution fails closed. `principal_for_session(session)` builds the
FEAT-773 `Principal(user_id=nav_user_id, channel="telegram", channel_user_id=str(telegram_id), …)` or `None`.
The Telegram identity write in the combined flow moves from `JiraPostAuthProvider` to this path.

**Request-less PBAC (M3).** `parrot/auth/oauth2/channel_pbac.py::check_integration_access(app, principal, action,
provider_id, scopes)` evaluates through the same PDP the web uses (`app['abac']`, its `_evaluator.check_access`
pattern at handlers/agent.py:184-200 and bots.py:49-59) with an `EvalContext` built from the **Navigator
principal** — never the Telegram id. No PDP, no evaluator, or an evaluator error ⇒ `False`. `IntegrationsService`
gains keyword `permission_app` on `start_connect` / `disconnect` / `status` / `list_for_principal`; when
`request is None` and `permission_app` and `principal` are given, `_check_pbac` delegates to
`check_integration_access`. FEAT-775's Teams commands inherit the same path.

**Command core (M5).** `integrations/core/auth/connections.py::ConnectionCommandService` is channel-neutral:
`connectable_providers()` filters `OAuth2ProviderRegistry.all()` to providers with a manager, not `mcp:*`, and in
the optional allowlist; `connect()`, `disconnect()` and `statuses()` return typed `ConnectOutcome` /
`DisconnectOutcome` / `ConnectionStatusLine` values (`needs_login`, `denied`, `unknown_provider`,
`already_connected`, `auth_url`, `device_code`, `unavailable`, `disconnected`) and never send messages. Scopes are
always the provider's defaults; user input never chooses scopes.

**Telegram commands (M6).** `telegram/connection_commands.py::register_connection_commands(router, *, commands,
principal_source, extra_state_factory)` registers `/connect`, `/disconnect`, `/connections` and the inline-picker
callback (`callback_data="conn:<provider_id>"`). Every handler: private chat only; principal or the "/login
first" reply (no OAuth state created); `ConnectionCommandService`; render the outcome — `auth_url` as an inline
URL button, `device_code` as text, `denied` as "Connecting <Provider> is not allowed for your account.".
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
Failures are logged, never raised. `TelegramOAuthNotifier` and `app["telegram_jira_session_stamper"]` are deleted.

**Needs-auth (M1, M2, M8).** M1 is FEAT-775 M5's `parrot/auth/pending.py` contract, verbatim. M2 changes
`AbstractClient._execute_tool`: for `status == "authorization_required"` it returns a channel-neutral string —
"The user must connect their <provider> account before this tool can run. Do not retry this tool in this turn;
tell the user a connection is required." — never the `auth_url` (single-use state must not be echoed by the
model). M8 wraps `_invoke_agent`'s `agent.ask` in `collect_auth_requirements()`; after the reply is sent, for each
distinct provider it runs the M6 connect routine (fresh state with this chat's `chat_id` / `bot_id` — the tool's
`auth_url` is not used) and sends the button; `auth_kind == "device_code"` renders `user_code` +
`verification_uri`; no principal ⇒ one "/login first" line per turn.

**Combined login (M9).** `telegram/post_auth_connection.py::ConnectionPostAuthProvider(provider_id, …)`
implements the existing `PostAuthProvider` Protocol (post_auth.py:34-90) for any registered provider:
`build_auth_url` calls `start_connect` with the principal from the in-progress session; `handle_result` calls
`manager.handle_callback(code, state)` (FEAT-773 persists durably and publishes `connection.completed`) and runs
the provider's session hook. `JiraPostAuthProvider` becomes a thin preset (`provider_name = "jira"`) so imports
and YAML keep working. `_init_post_auth_providers` resolves any provider from the registry; the
`_KNOWN_POST_AUTH_PROVIDERS` warning becomes "not a registered provider at startup".

**Cutover (M10).** FEAT-773's `legacy_audit` gains `purge_legacy_keys(redis, *, channel, providers, dry_run=True)`
and CLI flags `--purge --channel telegram [--confirm] [--force]`. It deletes `jira:oauth:telegram:*` and
`oauth2:<p>:telegram:*` only after `OAUTH2_LEGACY_KEYS_UNTIL` (or `--force`), prints counts only, and is
dry-run unless `--confirm`. Runbook: audit → announce to the unbound users (U3: forced re-connect) → date passes
→ purge.

### Shared with FEAT-775 (connections-msteams)

| Piece | Owner | Rule |
|---|---|---|
| `parrot/auth/pending.py` (`collect_auth_requirements`, `record_auth_requirement`) + one call in `ToolManager` | FEAT-775 M5 **and** FEAT-776 M1, identical contract | Whichever feature merges first creates it; the other's task re-verifies the contract and only adds tests. Never two modules. |
| Request-less PBAC (`check_integration_access`, `IntegrationsService(permission_app=…)`) | FEAT-776 M3 | FEAT-775 commands call `start_connect` without a request; they need this. |
| `clients/base.py::_execute_tool` needs-auth message | FEAT-776 M2 | Answers FEAT-775 §8 Q3 (decided here 2026-10-30). |
| Channel-neutral command core (`integrations/core/auth/connections.py`) | FEAT-776 M5 | Offered for FEAT-775 §8 Q2; S-2 does not migrate Teams. |

### Component Diagram

```
/login (any strategy) ─► handle_web_app_data ─► _persist_principal_link ─► IdentityMappingService.link_channel_identity   [M4]
/logout               ─► unlink_channel_identity("telegram", tg_id) ─► session.clear_auth()                                [M4]

/connect [p] | /connect_jira | conn:<p> button
   └─► connection_commands handler (private chat only)                                                                     [M6]
        ├─ principal_for_session / _ensure_principal_link ── None ─► "/login first" (no OAuth state)                      [M4]
        └─► ConnectionCommandService.connect(principal, p, extra_state={chat_id, bot_id})                                  [M5]
              └─► IntegrationsService.start_connect(channel="telegram", principal, permission_app=app)   (FEAT-773)
                    └─► _check_pbac → check_integration_access(app, principal, "integration:connect", p, scopes)          [M3]
              ◄── ConnectOutcome(auth_url | device_code | denied | already_connected | …) ─► inline button / text

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
| `telegram/wrapper.py::TelegramAgentWrapper` | modifies | link/unlink at login/logout; `_ensure_principal_link`; `_register_connection_commands` replaces `_register_jira_commands` / `_register_office365_commands`; notifier `attach` + Jira session hook; collector around `agent.ask` in `_invoke_agent` + Connect buttons; generic `_init_post_auth_providers` |
| `telegram/auth.py::TelegramUserSession` | extends | `principal_link_persisted: bool` (non-repr, non-compare, like `post_login_ran`) |
| `telegram/jira_commands.py` | modifies (reduce) | aliases only; `TelegramOAuthNotifier` deleted |
| `telegram/office365_commands.py` | modifies | alias registration when `o365` is connectable |
| `telegram/post_auth_jira.py::JiraPostAuthProvider` | modifies (reduce) | preset of `ConnectionPostAuthProvider`; no identity writes |
| `telegram/models.py::TelegramAgentConfig`, `TelegramBotsConfig.validate` | extends / modifies | `connection_providers`; soft warning no longer tied to `{"jira"}` |
| `integrations/core/auth/post_auth.py::PostAuthProvider` | uses | Protocol unchanged |
| `integrations/core/auth/notifiers.py` *(created by FEAT-773 M8)* | modifies | drop `TelegramJiraNotifierAdapter` |
| `integrations/manager.py` *(FEAT-773 `_register_channel_notifiers`)* | modifies | create + register `TelegramConnectionNotifier` once per app |
| `parrot/auth/oauth2/service.py::IntegrationsService` *(FEAT-773 signatures)* | modifies | `permission_app` keyword; `_check_pbac` request-less branch |
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
                      "already_connected", "auth_url", "device_code", "disconnected"]

class ConnectOutcome(BaseModel):
    kind: OutcomeKind
    provider_id: str
    display_name: str = ""
    auth_url: Optional[str] = None            # kind == "auth_url"
    user_code: Optional[str] = None           # kind == "device_code"
    verification_uri: Optional[str] = None
    expires_in: Optional[int] = None
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
from parrot.auth.oauth2.channel_pbac import check_integration_access                        # M3
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
| M3: Request-less PBAC | no | — | which `ResourceType`/resource name the evaluator receives is §8 Q1; fail-closed rules touch every channel |
| M4: Principal link lifecycle | no | — | transaction semantics across users, backfill and logout ordering are security decisions |
| M5: Channel-neutral command core | yes | models in §2; filter rules fixed (manager present, not `mcp:*`, allowlist); scopes = provider defaults | — |
| M6: Telegram generic commands + aliases | no | — | private-chat rule, alias/O365 fallback and rendering of every outcome across providers |
| M7: Telegram `ChannelNotifier` + session hooks | yes | Protocol from FEAT-773; target-resolution order and texts fixed in §2; failures logged | — |
| M8: Needs-auth rendering in Telegram | yes | wrap `agent.ask` at the `_invoke_agent` call sites listed in §6; dedupe by provider; reuse M6 routine | — |
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
  #   (today: `except AuthorizationRequired as auth_exc:`, manager.py:2273)
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

### Module 3: Request-less PBAC for channel surfaces
- **Path**: `packages/ai-parrot/src/parrot/auth/oauth2/channel_pbac.py` (new); `packages/ai-parrot/src/parrot/auth/oauth2/service.py` (modify)
- **Responsibility**: evaluate `integration:connect` / `integration:disconnect` / `integration:list` for a
  `Principal` without an aiohttp request, fail closed; wire it into `IntegrationsService` via `permission_app`.
- **Depends on**: FEAT-773 M1 (`Principal`), FEAT-773 M6 (`IntegrationsService` signatures).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/oauth2/channel_pbac.py  (new)
  async def check_integration_access(app: Mapping[str, Any], principal: Principal, action: str, *,
                                     provider_id: Optional[str] = None, scopes: Sequence[str] = ()) -> bool:
      """PDP = app.get("abac"); evaluator = getattr(pdp, "_evaluator", None) (pattern: handlers/agent.py:184-200).
      Missing PDP/evaluator, ImportError of navigator_auth.abac, or any evaluator exception → False (logged).
      EvalContext from PermissionContext(session=UserSession(user_id=principal.user_id, tenant_id=principal.tenant_id
      or "default", roles=frozenset()), channel=principal.channel) via to_eval_context (permission.py:209);
      check_access(ctx=…, resource_type=<§8 Q1>, resource_name=<§8 Q1>, action=action, env=Environment())
      (signature verified: navigator_auth 0.28.7 PolicyEvaluator.check_access)."""

  # packages/ai-parrot/src/parrot/auth/oauth2/service.py  (modifies FEAT-773 signatures)
  class IntegrationsService:                                                   # verified: service.py:74
      async def start_connect(self, user_id: str, provider_id: str, return_origin: Optional[str] = None, *,
                              channel: str = "web", principal: Optional[Principal] = None,
                              scopes: Optional[List[str]] = None, request: Any = None,
                              extra_state: Optional[Dict[str, Any]] = None,
                              permission_app: Optional[Mapping[str, Any]] = None) -> ConnectInitResponse: ...
      async def disconnect(self, user_id: str, provider_id: str, request: Any = None, *,
                           principal: Optional[Principal] = None,
                           permission_app: Optional[Mapping[str, Any]] = None) -> DisconnectResponse: ...
      async def status(self, user_id: str, provider_id: str, request: Any = None, *,
                       principal: Optional[Principal] = None,
                       permission_app: Optional[Mapping[str, Any]] = None) -> IntegrationDescriptor: ...
      async def list_for_principal(self, user_id: str, request: Any = None, *,
                                   principal: Optional[Principal] = None,
                                   permission_app: Optional[Mapping[str, Any]] = None) -> List[IntegrationDescriptor]: ...
      async def _check_pbac(self, request: Any, action: str, provider_id: Optional[str] = None, *,
                            scopes: Sequence[str] = (), principal: Optional[Principal] = None,
                            permission_app: Optional[Mapping[str, Any]] = None) -> bool:
          """request is not None → unchanged web path (service.py:490-530).
          request is None and permission_app and principal → check_integration_access(...).
          otherwise → False (fail closed, unchanged)."""                       # verified: service.py:490, :509-511
  ```

### Module 4: Telegram principal link lifecycle
- **Path**: `packages/ai-parrot-server/src/parrot/services/identity_mapping.py` (modify); `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` (modify); `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py` (modify)
- **Responsibility**: §2 "Principal link". The DB pool is resolved as today in `_init_post_auth_providers`
  (`app.get("authdb") or app.get("database")`, wrapper.py:583). No pool ⇒ one warning at startup, link writes are
  skipped, connection commands reply "Connections are not available on this bot".
- **Depends on**: FEAT-773 M1 (`Principal`).
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
          """One transaction: _DELETE_CHANNEL_OTHERS_SQL then _UPSERT_SQL (identity_mapping.py:43-53).
          Same validation as upsert_identity (numeric nav_user_id, non-empty provider_user_id, no secrets in
          auth_data, identity_mapping.py:207-225). Token-bearing providers are rejected (ValueError) — channel rows only."""
      async def unlink_channel_identity(self, auth_provider: str, provider_user_id: str) -> int:
          """Delete every row for (auth_provider, provider_user_id); return the count. No-op → 0."""

  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py  (modifies)
  @dataclass
  class TelegramUserSession:                                                   # verified: auth.py:44
      principal_link_persisted: bool = field(default=False, repr=False, compare=False)   # next to post_login_ran (auth.py:91)

  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py  (modifies)
  def principal_for_session(session: TelegramUserSession, *, tenant_id: Optional[str] = None) -> Optional[Principal]:
      """authenticated and nav_user_id.isdigit() → Principal(user_id=nav_user_id, canonical_identity=nav_email lower-cased
      or None, tenant_id=tenant_id, channel="telegram", channel_user_id=str(telegram_id)); else None."""
  class TelegramAgentWrapper:
      def _identity_service(self) -> Optional["IdentityMappingService"]: ...   # cached; None without a pool
      async def _persist_principal_link(self, session: TelegramUserSession) -> bool:
          """link_channel_identity(nav_user_id, "telegram", str(telegram_id), {"telegram_id", "username"}, display_name, email);
          sets session.principal_link_persisted on success; logs and returns False on any failure."""
      async def _ensure_principal_link(self, session: TelegramUserSession) -> bool:
          """No-op when principal_link_persisted or not authenticated; else _persist_principal_link."""
      # handle_web_app_data: after `success = await self._auth_strategy.handle_callback(data, session)` (wrapper.py:2362)
      #   and after `basic_ok = …` (wrapper.py:2404) succeed → await self._persist_principal_link(session)
      # handle_logout (wrapper.py:2310): before session.clear_auth() → unlink_channel_identity("telegram", str(telegram_id))
  ```

### Module 5: Channel-neutral connection command core
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/connections.py` (new); `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/__init__.py` (export)
- **Responsibility**: §2 "Command core". Uses `IntegrationsService` (FEAT-773) with M3's `permission_app`;
  maps the service's PBAC denial (FEAT-773 raises/returns it — re-verify the exact shape after merge) to `denied`;
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
                        extra_state: Dict[str, Any]) -> ConnectOutcome:
          """None → needs_login; unknown → unknown_provider; status() connected → already_connected;
          start_connect(principal.user_id, provider_id, channel=self.channel, principal=principal,
          extra_state=extra_state, permission_app=self.app) → auth_url | device_code; PBAC denial → denied."""
      async def disconnect(self, principal: Optional[Principal], provider_id: str) -> ConnectOutcome: ...
      async def statuses(self, principal: Optional[Principal]) -> List[ConnectionStatusLine]: ...
  ```

### Module 6: Telegram generic commands and aliases
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_commands.py` (new); `telegram/jira_commands.py` (modify → aliases); `telegram/office365_commands.py` (modify); `telegram/models.py` (modify); `telegram/wrapper.py` (modify)
- **Responsibility**: §2 "Telegram commands". Group/supergroup/channel chats get "Please use a private chat with
  the bot to manage connections." `/connect` without argument shows an inline keyboard of connectable providers.
  Every reply uses `parse_mode=None`. `_register_connection_commands` replaces `_register_jira_commands` and
  `_register_office365_commands` (wrapper.py:400-504) and is skipped when the registry has no connectable provider
  and no `o365` fallback applies.
- **Depends on**: M4 (`principal_for_session`, `_ensure_principal_link`), M5, M7 (removal of
  `TelegramOAuthNotifier` waits for its replacement).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_commands.py  (new)
  PrincipalSource = Callable[[Message | CallbackQuery], Awaitable[Optional[Principal]]]
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
- **Responsibility**: §2 "Notifier".
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
- **Responsibility**: §2 "Needs-auth" (wrapper half). The collector wraps the `agent.ask` calls inside
  `_invoke_agent` (wrapper.py:1464-1565) so every caller (wrapper.py:1661, 2634, 2808, 3166, 3270, 3527, 4109)
  is covered; `_invoke_agent` returns the collected list next to the response via a new attribute on the session
  turn (no signature break) or a helper — the task decides, the rule is one place. Buttons are sent after the
  agent's reply, deduplicated by `provider`, at most one "/login first" line per turn.
- **Depends on**: M1, M4, M5, M6 (`render_connect_outcome`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py  (modifies)
  class TelegramAgentWrapper:
      async def _invoke_agent(self, session: TelegramUserSession, question: str, *, memory: Any,
                              output_mode: OutputMode = OutputMode.TELEGRAM, message: Optional[Message] = None,
                              attachments: Optional[List[str]] = None) -> Any:          # verified: wrapper.py:1464-1473
          """Unchanged contract; agent.ask runs inside collect_auth_requirements(); the list is kept for _send_auth_prompts."""
      async def _send_auth_prompts(self, message: Message, session: TelegramUserSession,
                                   pending: Sequence[AuthRequiredPayload]) -> None:
          """Dedupe by provider; principal None → "/login first"; device_code → text; else M5 connect → render_connect_outcome."""
  ```

### Module 9: Generic combined login (`post_auth_actions`)
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_connection.py` (new); `telegram/post_auth_jira.py` (modify → preset); `telegram/wrapper.py` (modify `_init_post_auth_providers`); `telegram/models.py` (modify validation)
- **Responsibility**: §2 "Combined login". The Telegram identity row is written by M4 after the primary auth
  succeeds — `ConnectionPostAuthProvider` writes no identity rows and no tokens (FEAT-773 persists them).
  Rollback semantics of `_handle_combined_auth` (wrapper.py:2379-2450) are unchanged.
- **Depends on**: M4, M5 (provider resolution), FEAT-773 M2/M7 (`handle_callback` persists + publishes).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_connection.py  (new)
  class ConnectionPostAuthProvider:                                            # implements PostAuthProvider (post_auth.py:34)
      provider_name: str
      def __init__(self, provider_id: str, *, service: "IntegrationsService", app: Mapping[str, Any],
                   session_hook: Optional[SessionHook] = None) -> None: ...
      async def build_auth_url(self, session: Any, config: Any, callback_base_url: str) -> str:
          """principal_for_session(session) (None → ValueError); start_connect(..., channel="telegram",
          extra_state={"chat_id": session.telegram_id, "combined": True}, permission_app=app).auth_url."""
      async def handle_result(self, data: Dict[str, Any], session: Any, primary_auth_data: Dict[str, Any]) -> bool:
          """manager.handle_callback(data["code"], data["state"]); session_hook on success; False on any exception (logged)."""

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
      OAUTH2_LEGACY_KEYS_UNTIL unless force. Returns {pattern: count}; deletes only when not dry_run."""
  def main(argv: Optional[Sequence[str]] = None) -> int:
      """Existing audit flags + --purge --channel <c> [--confirm] [--force]."""
  ```

### Module 11: Docs
- **Path**: `docs/integrations/telegram-connections.md` (new); `docs/auth/connections.md` *(created by FEAT-773 M10)* (modify)
- **Responsibility**: user commands and aliases; `connection_providers`; the `/login` link and `/logout` unlink;
  PBAC deploy precondition (policy for `integration:connect` / `integration:disconnect` with the §8 Q1 resource);
  needs-auth behaviour; cutover runbook (audit → announce → date → purge); `post_auth_actions` for any provider.
  `connections.md` gains the Telegram row in the channel adapter table.

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
| `test_channel_pbac_fails_closed` | M3 | no `abac`, no `_evaluator`, evaluator raises, ImportError → `False` |
| `test_channel_pbac_uses_navigator_principal` | M3 | `EvalContext` username/user_id = `principal.user_id`, never the Telegram id |
| `test_service_request_less_pbac_branch` | M3 | `request=None` + `permission_app` + `principal` → evaluator consulted; without them → denied |
| `test_link_channel_identity_moves_ownership` | M4 | telegram id linked to user A, then linked to B → only B's row remains |
| `test_link_channel_identity_rejects_bad_input` | M4 | non-numeric nav id, empty provider id, secret in auth_data → `ValueError` |
| `test_unlink_channel_identity_counts` | M4 | returns deleted rows; 0 when absent |
| `test_login_persists_link_both_paths` | M4 | single-step and combined login call `link_channel_identity` once |
| `test_login_succeeds_when_link_write_fails` | M4 | DB error → login message still sent, flag stays false, warning logged |
| `test_logout_unlinks_before_clear` | M4 | `/logout` calls `unlink_channel_identity("telegram", id)` then clears the session |
| `test_ensure_principal_link_backfills_once` | M4 | authenticated session without flag → one write; second call no-op |
| `test_connectable_providers_filter` | M5 | MCP providers, manager `None`, and non-allowlisted providers excluded |
| `test_connect_outcomes` | M5 | needs_login / unknown_provider / already_connected / auth_url / device_code / denied mapping |
| `test_scopes_never_from_user` | M5 | `start_connect` called with provider default scopes only |
| `test_connect_requires_private_chat` | M6 | group chat → private-chat reply, no service call |
| `test_connect_without_principal_creates_no_state` | M6 | no `nav_user_id` → "/login first", `start_connect` never called |
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
| `test_connection_post_auth_build_and_handle` | M9 | `build_auth_url` uses principal + `start_connect`; `handle_result` calls `handle_callback`, runs hook, writes no identity rows |
| `test_jira_post_auth_preset_compat` | M9 | `JiraPostAuthProvider.provider_name == "jira"`; YAML `post_auth_actions: [{provider: jira}]` still registers |
| `test_post_auth_any_registered_provider` | M9 | `post_auth_actions: [{provider: o365}]` registers when `o365` is in the registry; unknown → warning |
| `test_purge_dry_run_and_date_gate` | M10 | dry run deletes nothing; before the date → refused unless `--force`; counts only, no values |
| `test_purge_deletes_only_channel_keys` | M10 | `jira:oauth:telegram:*` and `oauth2:*:telegram:*` deleted; `…:web:*`, `…:msteams:*` untouched |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_telegram_login_link_resolves` | plain `/login` → `telegram` row → FEAT-773 `IdentityPrincipalResolver.resolve("telegram", id)` returns the principal; `/logout` → `None` |
| `test_e2e_telegram_connect_any_provider` | `/connect <dummy descriptor provider>` → callback with the state → `TelegramConnectionNotifier` message in the issuing chat → tool resolves |
| `test_e2e_telegram_jira_parity` | (FEAT-773 test, updated) `/connect_jira` alias → callback → notifier → Jira tool resolves; `<jira>` prompt block present |
| `test_e2e_needs_auth_button` | Jira tool without connection → LLM sees the needs-auth message → Telegram reply then Connect button |
| `test_e2e_cross_channel_from_telegram` | connect on Telegram, listed by `list_for_principal` and resolved on web for the same principal |
| `test_e2e_unlinked_user_forced_reconnect` | legacy `jira:oauth:telegram:<id>` with no identity row → no resolution; "/login first" on `/connect` |

### Validation Contract

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
def fake_pdp_app():                         # {"abac": obj with _evaluator.check_access recording EvalContext; allow/deny/raise modes}
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC-1 (G1)** After a successful Telegram `/login` (single-step or combined, any strategy), `auth.user_identities` holds exactly one `telegram` row for that Telegram id, owned by the logged-in Navigator user; linking the same Telegram id to another user moves the row.
- [ ] **AC-2 (G1)** `/logout` deletes the `telegram` row before clearing the session; afterwards FEAT-773's resolver returns `None` for that Telegram id and no connection resolves from Telegram.
- [ ] **AC-3 (G1)** A failed link write never fails the login; the session flag stays false and the next connection command or agent turn retries once (`_ensure_principal_link`).
- [ ] **AC-4 (G2)** `/connect [<provider>]`, `/disconnect <provider>`, `/connections` work for every connectable provider; MCP providers, providers without a manager, and providers outside `connection_providers` are never offered or accepted; user input never sets scopes.
- [ ] **AC-5 (G2)** `/connect_jira`, `/disconnect_jira`, `/jira_status` behave as aliases; `/connect_office365` family aliases the generic commands only when `o365` is registered, otherwise behaves exactly as today.
- [ ] **AC-6 (G2)** No connection command creates OAuth state for a user without a resolvable principal, or in a non-private chat.
- [ ] **AC-7 (G3)** Telegram connect/disconnect are evaluated by `check_integration_access` against the Navigator principal; with no PDP, no evaluator, or an evaluator error the command is refused with the "not allowed" message and no OAuth state is created.
- [ ] **AC-8 (G4)** `AbstractClient._execute_tool` returns the needs-auth message (provider named, no URL) for `status="authorization_required"`; all other statuses behave as before.
- [ ] **AC-9 (G4)** When a tool needs auth during a Telegram turn, the agent's reply is sent first, then one Connect button per distinct provider (fresh OAuth state carrying this `chat_id`/`bot_id`); device-code payloads show code and URI; unlinked users get one "/login first" line.
- [ ] **AC-10 (G5)** `connection.completed`, `connection.revoked`, `connection.refresh_failed` for any provider produce one plain-text Telegram message through the issuing bot; a notifier failure never fails the callback; `TelegramOAuthNotifier`, `TelegramJiraNotifierAdapter` and `app["telegram_jira_session_stamper"]` no longer exist in `packages/`.
- [ ] **AC-11 (G5)** The `<jira>` user-context block appears after a Jira connection and disappears after disconnect/revoke, through the registered session hook.
- [ ] **AC-12 (G6)** `post_auth_actions` registers any provider present in `OAuth2ProviderRegistry`; `JiraPostAuthProvider` is a preset of `ConnectionPostAuthProvider` and writes no identity rows or tokens.
- [ ] **AC-13 (G7)** `python -m parrot.auth.oauth2.legacy_audit --purge --channel telegram` is a dry run without `--confirm`, refuses before `OAUTH2_LEGACY_KEYS_UNTIL` without `--force`, deletes only Telegram legacy keys, and prints counts only.
- [ ] **AC-14** `parrot/auth/pending.py` exists once with the FEAT-775 M5 contract; `grep -rn "def collect_auth_requirements" packages/` matches one definition.
- [ ] **AC-15** `docs/integrations/telegram-connections.md` exists and documents the PBAC deploy precondition and the cutover runbook.
- [ ] **AC-16** The Validation Contract passes; `ruff check` clean on touched files; no `print`, no `requests`/`httpx`; Telegram replies built by this feature use `parse_mode=None`.

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
from navigator_auth.abac.policies.resources import ResourceType   # verified: members TOOL, KB, VECTOR, AGENT, MCP, URI, DATASET, WIDGET, CARD, SLUG, DATASOURCE, DRIVER, RAW_QUERY — no INTEGRATION
from navigator_auth.abac.policies.environment import Environment  # verified: resolver.py:314 imports it
from navigator_auth.abac.policies.evaluator import PolicyEvaluator  # verified: check_access(self, ctx, resource_type, resource_name, action, env=None, owner_reports_to=None, org_id=1, client_id=1) -> EvaluationResult
# FEAT-773 (exist only after merge)
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
#   :2273 except AuthorizationRequired as auth_exc:  → ToolResult(success=False, status="authorization_required", result=None,
#         error=auth_exc.message, metadata={"auth_url", "provider", "scopes", "tool_name"})  (:2279-2290)

# packages/ai-parrot/src/parrot/auth/oauth2/service.py
async def _check_pbac(self, request: Any, action: str, provider_id: Optional[str] = None) -> bool  # :490
#   :509-511 request is None → False ; :513 abac = request.app.get("abac") ; :524 await abac.is_allowed(request, ctx)

# packages/ai-parrot-server/src/parrot/handlers/agent.py  (request-bound PDP pattern to mirror)
#   :184 pdp = self.request.app.get("abac") ; :187 evaluator = getattr(pdp, "_evaluator", None) ; :200 evaluator.check_access(...)

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
| `check_integration_access` | `app["abac"]._evaluator.check_access` | PDP evaluator | `handlers/agent.py:184-200` |
| `ConnectionCommandService` | `IntegrationsService.start_connect/disconnect/status/list_for_principal` *(FEAT-773 signatures)* | method call | `service.py:74` |
| `TelegramConnectionNotifier` | `ChannelNotifierRegistry` *(FEAT-773)* | `register(notifier)` | FEAT-773 §3 M4 |
| `_invoke_agent` collector | `collect_auth_requirements` | context manager | M1 |
| `ConnectionPostAuthProvider` | `PostAuthRegistry.register` | Protocol | `post_auth.py:109` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.auth.pending`, `collect_auth_requirements`, `record_auth_requirement`~~ — created by FEAT-775 M5 or this spec's M1, whichever merges first.
- ~~`check_integration_access`, `parrot.auth.oauth2.channel_pbac`, `IntegrationsService(permission_app=…)`~~ — new here (M3).
- ~~`IdentityMappingService.link_channel_identity` / `unlink_channel_identity` / a delete-by-`provider_user_id` query~~ — only `delete_identity(nav_user_id, auth_provider)` exists (identity_mapping.py:307).
- ~~`ResourceType.INTEGRATION`~~ — not in navigator-auth 0.28.7 (§8 Q1).
- ~~A Telegram identity write in any auth strategy's `handle_callback`~~ — none (auth.py:456-506 et al.); only `JiraPostAuthProvider._write_identity_records`.
- ~~Telegram handling of `authorization_required` / `AuthorizationRequired`~~ — none anywhere under `integrations/telegram/` (grep, 2026-10-30).
- ~~`AIMessage.tool_calls[*].result` carrying the needs-auth `ToolResult`~~ — `_execute_tool` returns `result.result` (`None`); `ToolCall` (models/basic.py:23) has `result`/`error` only.
- ~~Telegram commands `/connect`, `/disconnect`, `/connections`~~ — no `Command("connect")` etc. under `integrations/telegram/` today.
- ~~`ConnectionCommandService`, `ConnectOutcome`, `TelegramConnectionNotifier`, `ConnectionPostAuthProvider`, `register_connection_commands`, `purge_legacy_keys`, `TelegramAgentConfig.connection_providers`, `TelegramUserSession.principal_link_persisted`~~ — new here.
- ~~`ConnectionChannel` protocol~~ — absent (FEAT-773 proposal §3.4); this spec does not create it: FEAT-773's `ChannelNotifier` plus M5's command core cover the role.

### Edit Sites (Blueprint Anchors)
<!-- Verified against: 370a62d9b (pre-FEAT-773). Re-run `grep -c` for every row after FEAT-773 merges. -->

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/auth/pending.py` | CREATE (or verify, if FEAT-775 merged) | — | — | — |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | `except AuthorizationRequired as auth_exc:` (FEAT-773 widens it) | `tools/manager.py:2273` | 1 |
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | `if isinstance(result, ToolResult):` | `clients/base.py:1661` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/channel_pbac.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | MODIFY | `async def _check_pbac(` | `service.py:490` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/legacy_audit.py` | MODIFY | `def main(` *(FEAT-773 M10 — unverified until merge)* | — | — |
| `packages/ai-parrot-server/src/parrot/services/identity_mapping.py` | MODIFY | `    async def delete_identity(` | `identity_mapping.py:307` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/connections.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py` | MODIFY | `class TelegramJiraNotifierAdapter` *(FEAT-773 M8 — unverified until merge)* | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | `def _register_channel_notifiers(` *(FEAT-773 M8 — unverified until merge; today `def _build_jira_credential_sink(app: Any) -> Any:` :81)* | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_commands.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_notifier.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_connection.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py` | MODIFY | `def register_jira_commands(` | `jira_commands.py:156` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/office365_commands.py` | MODIFY | `def register_office365_commands(` | `office365_commands.py:106` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py` | MODIFY | `class JiraPostAuthProvider:` | `post_auth_jira.py:38` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py` | MODIFY | `    post_login_ran: bool = field(default=False, repr=False, compare=False)` | `telegram/auth.py:91` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` | MODIFY | `    post_auth_actions: List[PostAuthAction] = field(default_factory=list)` | `telegram/models.py:111` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` | MODIFY | `_KNOWN_POST_AUTH_PROVIDERS = frozenset({"jira"})` | `telegram/models.py:16` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `    def _register_jira_commands(self) -> None:` | `wrapper.py:400` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `    def _register_office365_commands(self) -> None:` | `wrapper.py:475` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `    def _init_post_auth_providers(self) -> None:` | `wrapper.py:557` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `    async def _invoke_agent(` | `wrapper.py:1464` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `        old_name = session.display_name` / `        session.clear_auth()` (handle_logout) | `wrapper.py:2322-2323` | 1 (pair) |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `        success = await self._auth_strategy.handle_callback(data, session)` | `wrapper.py:2362` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `        basic_ok = await self._auth_strategy.handle_callback(basic_data, session)` | `wrapper.py:2404` | 1 |
| `docs/integrations/telegram-connections.md` | CREATE | — | — | — |
| `docs/auth/connections.md` | MODIFY | *(FEAT-773 M10 — unverified until merge)* | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Principal from the session, never from the message text.** Commands derive the principal from
  `TelegramUserSession` (authenticated, numeric `nav_user_id`); a provider argument is the only user input, and it
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
- **Logout semantics change.** Today `/logout` leaves Jira usable (the token is keyed by the Telegram id). After S-2
  `/logout` unlinks, so connections stop resolving from that Telegram account until the next `/login` — intended.
- **Same Telegram id, different Navigator user.** `link_channel_identity` moves the row; the previous user's
  connections become unreachable from that Telegram account (they remain on other channels).
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
| `navigator-auth` | ≥ 0.28.7 (in `.venv`) | `PolicyEvaluator.check_access`, `ResourceType`, `Environment`, `auth.user_identities` |
| `aiogram` | existing | commands, inline keyboards, callback queries |

---

## 8. Open Questions

- [ ] **Q1 — PBAC resource for integrations.** navigator-auth 0.28.7 has no `ResourceType.INTEGRATION`. Which
  `resource_type` / `resource_name` does `check_integration_access` pass (e.g. `ResourceType.TOOL` +
  `"integration:<provider>"`, or a new navigator-auth resource type), and must it match what
  `abac.is_allowed(request, {"action", "provider"})` evaluates on the web so one policy covers both? —
  *Owner: Jesus* (also FEAT-773 §8 "PBAC allowlist shape"). Blocks M3.
- [ ] **Q2 — Codex S3: legacy rollback.** Should the Telegram purge keep a rollback path (e.g. export the
  `jira:oauth:telegram:*` keys to an encrypted backup before deletion) or is the date gate + dry run enough? —
  *Owner: Jesus*.
- [ ] **Q3 — Legacy key cutover date and acceptable unbound count** (carried from FEAT-773 §8 and proposal §5) —
  *Owner: Jesus* (ops decision before M10 runs in prod).
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
  - M5 → M3 (calls `IntegrationsService(..., permission_app=)`).
  - M6 → M4 (`principal_for_session`, `_ensure_principal_link`), M5 (`ConnectionCommandService`), M7 (deletes
    `TelegramOAuthNotifier` only after the notifier replaces the FEAT-773 adapter).
  - M8 → M1 (`collect_auth_requirements`), M4, M5, M6 (`render_connect_outcome`).
  - M9 → M4 (identity row moves to the link path), M5.
  - M11 → all.
  - M1, M2, M3, M4, M7, M10 have no edges between them and can run concurrently.
- **Shared files** (tasks serialized): `telegram/wrapper.py` (M4, M6, M7, M8, M9); `telegram/models.py` (M6, M9);
  `telegram/jira_commands.py` (M6, M7 via the notifier removal — M6 owns the edit).
- **Exclusive resources**: none (no migrations: `auth.user_identities` is unchanged; no lockfile change).
- **Cross-feature dependencies**: **FEAT-773 merged** (hard). FEAT-775 (S-3b) shares `parrot/auth/pending.py`
  — whichever merges first creates it (§2 "Shared with FEAT-775"); FEAT-775 benefits from M3 and M2.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-30 | Jesus Lara (with Claude Opus 5.5) | Initial draft — S-2 of FEAT-773 |

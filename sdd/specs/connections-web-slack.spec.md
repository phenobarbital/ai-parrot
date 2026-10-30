---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server, ai-parrot-integrations, admin-ui, docs]
tags: [oauth2, connections, web-ui, sse, slack, o365]
---

# Feature Specification: Connections — Web + Slack (S-3a of FEAT-773): Connections panel, SSE push, auto-retry, Slack linking, O365 store consolidation

**Feature ID**: FEAT-777
**Date**: 2026-10-30
**Author**: Jesus Lara (with Claude Opus 5.5)
**Status**: approved
**Target version**: 1.3.0

> **Source**: S-3a row of proposal `sdd/proposals/delegated-auth-connections.proposal.md` §6 (FEAT-773,
> `accepted`, research state `sdd/state/FEAT-773/`) and the S-3a items in the Non-Goals of the S-1 spec
> `sdd/specs/delegated-auth-connections.spec.md` §1. **This spec consumes S-1's contracts** (`Principal`,
> `PrincipalResolver`, `CredentialStore`, `ConnectionEvent`, `ChannelNotifier`, `ConnectionEventPublisher`,
> `AuthRequiredPayload`, `/api/v1/connections*`) and cannot start before FEAT-773 is merged.
> Siblings: S-2 Telegram migration, S-3b MS Teams, S-4 CLI + local MCP (FEAT-774, `connections-cli-local-mcp`).
> Spec-time decisions taken with the user on 2026-10-30 are marked **(D1–D3)**.

---

## 1. Motivation & Business Requirements

### Problem Statement

After S-1, a connection is principal-keyed and visible from every channel, but the people who use the web
and Slack surfaces cannot see or benefit from it:

1. **No user-level view.** The admin UI only has a per-agent `IntegrationsMenu` over
   `/api/v1/agents/integrations/{agent_id}` (`integrations.ts:51-52`). There is no page that lists a user's
   connections with status, account, scopes and expiry, and no page under a user section at all.
2. **No live completion.** Completion reaches only the tab that opened the popup (`postMessage`,
   `popup.ts:51`). A connection finished in another tab or on Telegram never shows up until a reload. The
   admin UI has no push channel: its WebSocket service is a deliberate no-op stub (FEAT-476 non-goal,
   `websocket-service.ts:1-12`), and `UserSocketManager` is wired only in the repo-root `app.py`, keyed by
   JWT username and process-local (`handlers/user.py:247`, `:382-414`).
3. **Manual retry, and none at all when streaming.** `ConnectIntegrationPill` says "You can now retry your
   prompt" (`ConnectIntegrationPill.svelte:31-33`). `auth_required` is detected only on the non-streaming
   path (`AgentChat.svelte:1344`); the streaming frame format has no `auth_required` variant
   (`stream.ts:27-30`), so in the default streaming mode the user never sees a Connect pill.
4. **Slack first-link has no owner.** Slack has no login, so `/connect_jira` carries no `nav_user_id`
   (`slack/commands/jira_commands.py:91-99`) and the durable Identity Vault write is skipped
   (`docs/auth/jira-credential-ownership.md:60-84`, "Known gap"). After S-1, an unresolvable principal fails
   closed, so Slack users could not connect at all.
5. **O365 lives in three stores.** Browser 3LO writes `vault_utils` DocumentDB `user_credentials` under
   `oauth2_o365_web_{user_id}`; device code writes navigator-session `VaultTokenSync` `o365:*` keyed by the
   e-mail/OID (`o365_devicecode_provider.py:142`, `:272`); `O365OAuth2Provider` is registered nowhere
   (`o365_provider.py:8-14` docstring only; `manager.py:2789-2810` registers Jira only).
6. **A dead placeholder.** `JiraConnectTool` / `setup_jira_oauth_session` / `hotswap_to_full_toolkit`
   (`jira_connect_tool.py`) is reachable only through `agent.jira_credential_resolver`, which nothing sets
   (`handlers/agent.py:1043-1080`); `JiraToolkit` is on the broker seam after S-1.

### Goals

- **G1 — Connections panel.** `/account/connections` lists every registered provider for the logged-in
  principal (status, account, scopes granted, expiry, channels seen) with Connect / Reconnect / Disconnect,
  over S-1's `/api/v1/connections*`.
- **G2 — Live completion via SSE (D1).** `GET /api/v1/connections/events` streams the principal's
  `connection.*` events as Server-Sent Events, delivered across gunicorn workers through a per-principal
  Redis pub/sub channel. No WebSocket is added (FEAT-476's non-goal stands); `UserSocketManager` is untouched.
- **G3 — Needs-auth in every chat mode, with automatic retry.** Streaming and non-streaming AgentTalk
  responses carry the `AuthRequiredPayload`; the UI renders the Connect pill in both, and after a successful
  connect re-sends the originating prompt once, idempotently.
- **G4 — Slack linking through the web session (D2).** Slack `/login` (and `/connect` when unlinked) DMs a
  signed one-time link; opening it in the logged-in admin UI writes the `slack` identity row for that
  session's Navigator user. Slack `/connect <provider>`, `/disconnect <provider>`, `/connections` are generic;
  `/connect_jira` etc. stay as aliases.
- **G5 — One O365 credential (D3, full consolidation).** O365 3LO and device-code grants live in one
  principal-keyed record (Identity Vault via S-1's `CredentialStore`, Redis hot cache via
  `O365OAuthManager`); `VaultTokenSync` no longer serves `o365`; legacy `o365:*` and
  `oauth2_o365_web_*` entries are migrated once and deleted.
- **G6 — Retire agent enablement in the UI** (`/enable`, `confirmIntegrationEnable`, `EnableResponse`) and
  the FEAT-083 hot-swap placeholder.

### Non-Goals (explicitly out of scope)

- Anything S-1 owns: principal keys, `CredentialStore`, PBAC on connect/disconnect, `AuthRequiredPayload`,
  the event publisher and bus, multi-account (v1 is single account per provider).
- A WebSocket route, or changes to `UserSocketManager` / `wsService` (D1 keeps FEAT-476's decision).
- Telegram (S-2) and MS Teams (S-3b) commands and notifiers.
- The CLI surface and a generic RFC 8628 device-code engine (S-4, FEAT-774). S-3a moves the **existing**
  O365 device-code resolver onto the shared store; it does not generalize it or give the CLI a principal.
- Auto-linking Slack users by e-mail (rejected at spec time in favour of D2).
- Removing the agent-scoped `/api/v1/agents/integrations/{agent_id}` list/connect/delete routes (they stay as
  S-1 aliases; only `/enable` goes).
- `VaultTokenSync` for fireflies / work.iq / entra static keys (unchanged).

---

## 2. Architectural Design

### Overview

**Push (M1, D1).** S-1's `ConnectionEventPublisher` delivers each event to the `ChannelNotifier` of
`event.channel`. The web panel must see *every* event of its principal regardless of the originating channel,
so M1 adds a second, channel-independent delivery list to the publisher: `ConnectionEventSink`s, called for
every event after the notifier, isolated the same way (exceptions logged). The server registers
`RedisConnectionPush` as a sink: it publishes `event.model_dump_json()` to the Redis channel
`parrot:connections:user:{user_id}`. `ConnectionEventsHandler` (`GET /api/v1/connections/events`) takes the
principal from the session (never a query parameter), subscribes to that channel, and writes
`event: connection\ndata: <json>\n\n` frames plus a `: keep-alive` comment every 25 s. Any worker can serve
the stream; any worker can publish. Semantics: no buffering — the stream is a hint, `GET /api/v1/connections`
is authoritative; the client refetches the list on every (re)connect and on every event, so duplicates and
gaps are harmless. Because the admin UI authenticates with a bearer header from `localStorage`, the client
reads the stream with `fetch` + `ReadableStream` (the same pattern as `stream.ts`), not `EventSource`.

**Slack linking (M2, D2).** Core gets a small `ChannelLinkIssuer` over Redis: `issue(channel,
channel_user_id, extra)` stores a 10-minute single-use nonce `channel_link:{nonce}` and returns
`{CONNECTIONS_LINK_BASE_URL}/account/link?token={nonce}`; `consume(nonce)` deletes and returns the claim. The
Slack `/login` command DMs that URL. The admin UI page `/account/link` (requires login) calls
`POST /api/v1/channel-links/{nonce}/confirm`; the server consumes the nonce and calls
`IdentityMappingService.upsert_identity(nav_user_id=<session user>, auth_provider="slack",
provider_user_id="{team_id}:{slack_user_id}", auth_data={team_id, slack_user_id})`. The principal therefore
comes only from an authenticated web session; the nonce only says *which Slack user* is being linked. The
Slack `provider_user_id` is the team-qualified id everywhere (link handler, OAuth callback, S-1's
`IdentityPrincipalResolver` lookup), matching the `user_id` the Slack commands already build
(`jira_commands.py:77-79`). Slack `/connect <provider>` resolves the principal; `None` → "link your account
first: /login" and no OAuth state; otherwise `IntegrationsService.start_connect(channel="slack",
principal=…)`. A provider-agnostic `SlackConnectionNotifier` (`channel = "slack"`) replaces S-1's
`SlackJiraNotifierAdapter` and DMs completion / revocation / refresh failure for any provider.

**O365 consolidation (M3, D3).** The 3LO path already inherits S-1's principal keys and `CredentialStore`
through `O365OAuthManager(AbstractOAuth2Manager)`; S-3a registers `O365OAuth2Provider` at startup when
`O365_CLIENT_ID` is configured, so O365 appears in the panel. The device-code resolver stops owning a store:
it reads through `O365OAuthManager.get_valid_token(channel, principal.user_id)` (Redis → store → locked
refresh — device code already refreshes through `O365OAuthManager.refresh_access_token`,
`o365_devicecode_provider.py:159-176`) and, after a device flow, persists through a new public
`O365OAuthManager.store_device_grant(principal, payload)` that builds the token set and calls S-1's
durable-first `_persist_token(..., minted=True)` and `upsert_users_integration`. The record carries
`grant_origin ∈ {"authorization_code", "device_code"}` for display and audit. The resolver's `user_id` today
is the e-mail/OID; it now resolves the principal first (`resolve_principal(channel, user_id)`, S-1's
canonical-identity path that AC-3 of S-1 requires for `a2a`), failing closed on `None`. Legacy `o365:*`
entries in `VaultTokenSync` (keyed by the e-mail/OID) are read once per principal, rewritten, and deleted,
until `OAUTH2_LEGACY_KEYS_UNTIL` (S-1 config); the 3LO legacy vault name `oauth2_o365_web_{u}` is already
covered by S-1's `_read_legacy_token`.

**Chat (M4).** AgentTalk detects an `authorization_required` `ToolResult` among the turn's tool calls
(`AIMessage.tool_calls[*].result`) and S-1's re-raised exceptions, and emits S-1's `AuthRequiredPayload`:
non-streaming → the existing `AuthRequiredEnvelope` JSON; streaming → a trailer frame
`\n\x00{"auth_required": {…payload}, "turn_id": …}` after the envelope, the same framing as the FEAT-752
suggestions trailer (`agent.py:2625`). `stream.ts` gains the `auth_required` `StreamChunk`; `AgentChat`
inserts the Connect pill in both modes. The pill uses `startConnect` (S-1 route) rather than the raw
`auth_url`, so origin validation and PBAC apply; on success — popup `postMessage` **or** an SSE
`connection.completed` for the same provider — it calls `onConnected`, and `AgentChat` re-sends the user
message that produced the `auth_required` message, at most once (keyed by that message id), and only if no
newer user message exists; otherwise the pill shows a Retry button wired to the existing `handleRetry`.

**Panel and cleanup (M5, M6).** `ConnectionsPanel` (account page) and the per-agent `IntegrationsMenu` both
read `lib/stores/connections.svelte.ts`, which owns the list, the SSE reader and refetch-on-event. The
`/account` section is shared with FEAT-772 (passkeys, TASK-4902–4904, pending): whichever lands first adds
`"account"` to `appSections`, the nav entry, and `/account` to `SPA_SECTIONS`; the other only adds its route.
`/enable` disappears end to end. API types are generated from the Pydantic models through
`scripts/generate_ts_types.py` instead of hand-written in `integrations.ts`.

### Component Diagram

```
 connect on any channel (web popup | Slack /connect | Telegram | device code)
        │
        ▼
 S-1 AbstractOAuth2Manager.handle_callback / O365OAuthManager.store_device_grant (M3)
        │ durable-first _persist_token → users_integrations row
        ▼
 S-1 ConnectionEventPublisher.publish(event)
   ├── ChannelNotifier[event.channel]   (slack → SlackConnectionNotifier, M2)
   ├── AuditLedger / Streams bus        (S-1)
   └── sinks (M1, every event) ── RedisConnectionPush ──► PUBLISH parrot:connections:user:{user_id}
                                                                │  (any gunicorn worker)
 browser ── fetch GET /api/v1/connections/events ◄── ConnectionEventsHandler SUBSCRIBE ┘
   │  connections.svelte.ts: on event / reconnect → GET /api/v1/connections (authoritative)
   ├── ConnectionsPanel (/account/connections)            [M5]
   ├── IntegrationsMenu (per-agent header)                 [M5]
   └── AgentChat: auth_required (stream trailer | JSON) → ConnectIntegrationPill
                    → POST /api/v1/connections/{p}/start → popup → onConnected → resend once   [M4]

 Slack /login ─► ChannelLinkIssuer.issue ─► DM https://<ui>/account/link?token=N
 browser (logged in) /account/link ─► POST /api/v1/channel-links/N/confirm
        ─► ChannelLinkIssuer.consume ─► IdentityMappingService.upsert_identity(slack, "T:U")    [M2]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| S-1 `parrot/auth/oauth2/events.py::ConnectionEventPublisher` | extends | `add_sink` / `ConnectionEventSink` (M1) |
| S-1 `ConnectionsHandler`, `IntegrationsService.start_connect/list_for_principal` | uses | panel, pill, Slack commands |
| S-1 `IdentityPrincipalResolver` | modifies | Slack lookup uses the team-qualified `provider_user_id`; `cli` resolves like `a2a` (canonical identity) |
| S-1 `SlackJiraNotifierAdapter` (integrations `core/auth/notifiers.py`) | replaces | `SlackConnectionNotifier` |
| `handlers/agent.py` AgentTalk | modifies | `auth_required` detection on both paths; streaming trailer; hot-swap bootstrap removed |
| `handlers/integrations.py::IntegrationsHandler` | modifies | `/enable` branch and `_post_enable` removed |
| `manager/manager.py` | modifies | routes (SSE, channel-link confirm), `/enable` route removed, sink + O365 provider registration |
| `services/identity_mapping.py::IdentityMappingService.upsert_identity` | uses | slack identity row on link confirm |
| `slack/commands/jira_commands.py`, `slack/oauth_callback.py`, `slack/wrapper.py` | modifies | generic commands, team-qualified identity, notifier registration |
| `parrot/auth/o365_oauth.py::O365OAuthManager` | extends | `store_device_grant`, `grant_origin` |
| `parrot/auth/oauth2/o365_devicecode_provider.py::O365DeviceCodeCredentialResolver` | modifies | manager-backed read/write, principal resolution, legacy migration |
| `parrot/auth/broker/factory.py::_build_device_code` | modifies | deps: `o365`, `o365_oauth_manager`, optional `legacy_vault` (no required `vault`) |
| `services/vault_token_sync.py` | modifies (docs) | `o365` no longer served |
| `parrot/tools/jira_connect_tool.py` | deletes | with its bootstrap and test |
| Admin UI `AgentChat.svelte`, `ConnectIntegrationPill.svelte`, `IntegrationsMenu.svelte`, `api/integrations.ts`, `api/stream.ts`, `App.svelte`, `nav.ts`, `config.ts` | modifies | see M4, M5 |
| `server/ui/serving.py::SPA_SECTIONS` | modifies | `/account` (shared with FEAT-772) |
| `scripts/generate_ts_types.py::_models` | modifies | connection models → `schemas/` → generated types |

### Data Models

```python
# parrot/auth/channel_link.py  (new, M2)
class ChannelLinkClaim(BaseModel):
    channel: str                    # "slack" in v1
    channel_user_id: str            # team-qualified: "{team_id}:{slack_user_id}"
    extra: Dict[str, str] = {}      # {team_id, slack_user_id}; never secrets
    issued_at: float

# parrot/auth/oauth2/events.py  (S-1 file, extended by M1)
class ConnectionEventSink(Protocol):
    async def deliver(self, event: ConnectionEvent) -> None: ...

# AgentTalk streaming trailer (M4) — one NUL-framed JSON object, after the envelope frame:
#   {"auth_required": AuthRequiredPayload.model_dump(), "turn_id": "<turn id>"}
# SSE frame (M1):
#   event: connection
#   data: ConnectionEvent.model_dump_json()      # S-1 model; no token material
```

```ts
// ui/src/lib/api/stream.ts (M4)
export type StreamChunk =
  | { type: "chunk"; text: string }
  | { type: "done"; message: AgentChatResponse | BotChatResponse }
  | { type: "suggestions"; suggestions: AgentChatSuggestion[]; turn_id?: string }
  | { type: "auth_required"; payload: AuthRequiredPayload; turn_id?: string };   // new
```

### New Public Interfaces

```python
# ai-parrot (core)
class ChannelLinkIssuer:                               # parrot/auth/channel_link.py
    async def issue(self, channel: str, channel_user_id: str, extra: Dict[str, str] | None = None) -> str: ...
    async def consume(self, nonce: str) -> Optional[ChannelLinkClaim]: ...
class O365OAuthManager:                                # parrot/auth/o365_oauth.py (added method)
    async def store_device_grant(self, principal: Principal, payload: Dict[str, Any], *, channel: str) -> O365TokenSet: ...

# ai-parrot-server
class RedisConnectionPush:                             # services/connection_push.py — ConnectionEventSink
    async def deliver(self, event: ConnectionEvent) -> None: ...
    def subscribe(self, user_id: str) -> AsyncIterator[ConnectionEvent]: ...
class ConnectionEventsHandler(BaseView)                # handlers/connection_events.py — GET /api/v1/connections/events (SSE)
class ChannelLinksHandler(BaseView)                    # handlers/channel_links.py — POST /api/v1/channel-links/{nonce}/confirm

# ai-parrot-integrations
class SlackConnectionNotifier:                         # slack/notifier.py — ChannelNotifier, channel = "slack"
def register_connection_commands(router, *, link_issuer, oauth_registry=None) -> None   # slack/commands/connection_commands.py
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: SSE push | yes | sink Protocol + `add_sink`; Redis channel `parrot:connections:user:{user_id}`; frame format and 25 s keep-alive fixed; session principal only | — |
| M2: Slack linking + generic commands + notifier | no | — | trust boundary (nonce ↔ session), identity-row key normalization and alias behaviour must be reasoned about, not transcribed |
| M3: O365 consolidation | no | — | production credential migration across two stores with principal re-keying (e-mail/OID → Navigator id) |
| M4: Chat needs-auth + auto-retry | no | — | idempotency rules and the streaming trailer touch every chat turn |
| M5: Connections panel, store, `/enable` removal | yes | routes, store API, components and removed symbols fixed below; Svelte 5 runes only | — |
| M6: Retire hot-swap placeholder | yes | delete the three listed files/blocks; no replacement | — |
| M7: Docs | yes | outline fixed below | — |

### Module 1: Per-principal SSE push
- **Path**: `packages/ai-parrot/src/parrot/auth/oauth2/events.py` (modify — S-1 file);
  `packages/ai-parrot-server/src/parrot/services/connection_push.py` (new);
  `packages/ai-parrot-server/src/parrot/handlers/connection_events.py` (new);
  `packages/ai-parrot-server/src/parrot/manager/manager.py` (route + startup/cleanup)
- **Responsibility**: channel-independent event sinks on the publisher; Redis fan-out per principal; an
  authenticated SSE endpoint that relays only the caller's events.
- **Depends on**: S-1 M4 (`ConnectionEvent`, `ConnectionEventPublisher`), S-1 M6 (`ConnectionsHandler` route block).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/oauth2/events.py  (modifies S-1 M4)
  class ConnectionEventSink(Protocol):
      async def deliver(self, event: ConnectionEvent) -> None:
          """Receive every event regardless of event.channel; may raise — the publisher logs and continues."""
  class ConnectionEventPublisher:
      def add_sink(self, sink: ConnectionEventSink) -> None:
          """Called after the channel notifier for every published event (order: notifier → sinks → audit → bus)."""

  # packages/ai-parrot-server/src/parrot/services/connection_push.py  (new)
  CHANNEL_TEMPLATE = "parrot:connections:user:{user_id}"
  class RedisConnectionPush:
      def __init__(self, redis_url: str) -> None: ...                       # REDIS_URL, conf.py:308
      async def start(self) -> None: ...                                    # aiohttp on_startup
      async def close(self) -> None: ...                                    # aiohttp on_cleanup
      async def deliver(self, event: ConnectionEvent) -> None:
          """PUBLISH CHANNEL_TEMPLATE.format(user_id=event.user_id) event.model_dump_json()."""
      def subscribe(self, user_id: str) -> AsyncIterator[ConnectionEvent]:
          """Own pubsub connection per call; unsubscribes and closes on cancellation."""
      # pattern: liveavatar output_transport.py run_output_subscriber (:100-133) + liveavatar_output.py hooks (:126-156)

  # packages/ai-parrot-server/src/parrot/handlers/connection_events.py  (new)
  class ConnectionEventsHandler(BaseView):                                  # BaseView/auth decorators: handlers/integrations.py:31-34
      async def get(self) -> web.StreamResponse:
          """401 without session; principal = session user (integrations.py:43-63 pattern, never a query param);
          headers text/event-stream, Cache-Control no-cache, X-Accel-Buffering no (stream.py:122-126 pattern);
          ': keep-alive' every 25 s; 'event: connection' frames; ends on client disconnect."""
  ```

### Module 2: Slack linking, generic Slack commands, Slack notifier
- **Path**: `packages/ai-parrot/src/parrot/auth/channel_link.py` (new); `packages/ai-parrot/src/parrot/conf.py`
  (`CONNECTIONS_LINK_BASE_URL`, `CHANNEL_LINK_TTL_SECONDS`); `packages/ai-parrot-server/src/parrot/handlers/channel_links.py` (new);
  `packages/ai-parrot-server/src/parrot/services/identity_principal.py` (modify — S-1 file);
  `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/connection_commands.py` (new);
  `slack/commands/jira_commands.py`, `slack/oauth_callback.py`, `slack/wrapper.py` (modify); `slack/notifier.py` (new);
  `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py` (modify — S-1 file: drop the Slack adapter)
- **Responsibility**: signed single-use link nonce; session-authenticated confirm that writes the `slack`
  identity row; `/login`, `/connect <p>`, `/disconnect <p>`, `/connections` (Jira commands become aliases);
  team-qualified Slack `provider_user_id`; provider-agnostic Slack notifier.
- **Depends on**: S-1 M1 (`resolve_principal`), M4 (`ChannelNotifier`), M6 (`start_connect(channel=, principal=)`, `disconnect`, `list_for_principal`), M8 (`IdentityPrincipalResolver`, notifier registration site).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/channel_link.py  (new)
  class ChannelLinkIssuer:
      """Redis key channel_link:{nonce} (secrets.token_urlsafe(32)), TTL CHANNEL_LINK_TTL_SECONDS (default 600), GETDEL on consume."""
      def __init__(self, redis_client: Any, *, base_url: str, ttl_seconds: int = 600) -> None: ...
      async def issue(self, channel: str, channel_user_id: str, extra: Optional[Dict[str, str]] = None) -> str:
          """Return f"{base_url}/account/link?token={nonce}"; raises ValueError on empty channel_user_id."""
      async def consume(self, nonce: str) -> Optional[ChannelLinkClaim]:
          """Single use: None when missing/expired/already consumed."""

  # packages/ai-parrot-server/src/parrot/handlers/channel_links.py  (new)
  class ChannelLinksHandler(BaseView):
      async def post(self) -> web.Response:
          """POST /api/v1/channel-links/{nonce}/confirm. 401 without session; 410 when consume() is None;
          nav_user_id = session user (must be numeric, else 403); IdentityMappingService.upsert_identity(
          nav_user_id=…, auth_provider=claim.channel, provider_user_id=claim.channel_user_id, auth_data=claim.extra)
          (identity_mapping.py:173-183); returns {channel, linked: true}. The body is ignored."""

  # packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/connection_commands.py  (new)
  def register_connection_commands(router: Any, *, link_issuer: ChannelLinkIssuer, service_factory: Callable[[], IntegrationsService]) -> None:
      """/login → DM link; /connect <provider> → resolve_principal("slack", "T:U"); None → 'link first: /login';
      else start_connect(channel="slack", principal=p, extra_state={team_id, slack_user_id}) → DM button;
      /disconnect <provider>; /connections → list_for_principal summary. Unknown provider → list of registered ids."""

  # slack/commands/jira_commands.py  (modifies; register_jira_commands verified :166)
  #   connect_jira_handler (:60) / disconnect_jira_handler (:103) / jira_status_handler (:132) delegate to the generic handlers with provider="jira"

  # slack/oauth_callback.py  (modifies; :251)
  #   provider_user_id=f"{team_id}:{slack_user_id}"   (was slack_user_id)

  # packages/ai-parrot-integrations/src/parrot/integrations/slack/notifier.py  (new)
  class SlackConnectionNotifier:
      channel = "slack"
      def __init__(self, bot_token: str) -> None: ...               # AsyncWebClient as SlackOAuthNotifier (oauth_callback.py:74-94)
      async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None:
          """DM extra.slack_user_id: completed / revoked / refresh_failed for any provider (display_name from the registry)."""

  # packages/ai-parrot-server/src/parrot/services/identity_principal.py  (modifies S-1 M8)
  #   slack: find_user_by_provider_account("slack", "{team_id}:{slack_user_id}")
  #   cli:   same canonical-identity path as a2a (e-mail / OID) — needed by M3's device-code resolver until S-4
  ```

### Module 3: O365 store consolidation
- **Path**: `packages/ai-parrot/src/parrot/auth/o365_oauth.py`, `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py`,
  `packages/ai-parrot/src/parrot/auth/broker/factory.py`, `packages/ai-parrot-server/src/parrot/manager/manager.py`
  (`_register_oauth2_providers`), `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py` (docstring)
- **Responsibility**: one principal-keyed O365 record for both grant types; device-code resolver backed by
  the manager; O365 registered as a connection provider; legacy `o365:*` migration.
- **Depends on**: S-1 M1, M2 (`_persist_token(principal, token_set, minted=, state_payload=)`, `_read_legacy_token`,
  `OAUTH2_LEGACY_KEYS_UNTIL`), M6 (`upsert_users_integration` row shape), M8 (`IdentityVaultCredentialStore` for any provider).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/auth/o365_oauth.py  (modifies)
  class O365TokenSet(AbstractOAuth2TokenSet):                       # verified: o365_oauth.py:44
      grant_origin: Literal["authorization_code", "device_code"] = "authorization_code"   # new
  class O365OAuthManager(AbstractOAuth2Manager):                    # verified: o365_oauth.py:55
      async def store_device_grant(self, principal: Principal, payload: Dict[str, Any], *, channel: str) -> O365TokenSet:
          """Build O365TokenSet(grant_origin="device_code") from an MSAL/token-endpoint payload (+ _discover_identity :190),
          then _persist_token(principal, ts, minted=True) (durable first, S-1) and upsert the users_integrations row
          with channels=[channel]; publishes connection.completed via the manager's event publisher."""

  # packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py  (modifies)
  class O365DeviceCodeCredentialResolver(CredentialResolver):       # verified: :73
      def __init__(self, o365_client: Any, o365_oauth_manager: Any, scopes: Optional[List[str]] = None,
                   prompt_callback: Optional[Callable[[Dict[str, Any]], None]] = None, *,
                   legacy_vault: Any = None) -> None: ...             # verified: :100-116 (vault_token_sync param REMOVED)
      async def resolve(self, channel: str, user_id: str) -> Optional[str]:
          """principal = await resolve_principal(channel, user_id) → None: raise PermissionError (fail closed);
          ts = await manager.get_valid_token(channel, principal.user_id); None → _migrate_legacy → device flow.""" # verified: :117
      async def _migrate_legacy(self, canonical_id: str, principal: Principal) -> Optional[str]:
          """Before OAUTH2_LEGACY_KEYS_UNTIL: legacy_vault.read_tokens(canonical_id, "o365") → store_device_grant →
          legacy_vault.delete_tokens(canonical_id, "o365"); else None."""
      async def _persist_token_set(...)                             # verified: :237 — now delegates to manager.store_device_grant
  # _O365_VAULT_PREFIX (:46) kept only for the legacy read

  # packages/ai-parrot/src/parrot/auth/broker/factory.py  (modifies _build_device_code, :167-200)
  #   required deps: "o365", "o365_oauth_manager"; optional "legacy_vault"; "vault" no longer required

  # packages/ai-parrot-server/src/parrot/manager/manager.py  (modifies _register_oauth2_providers, :2789)
  #   when O365_CLIENT_ID (conf.py:618) is set: reuse app["oauth2_manager_o365"] or build
  #   O365OAuthManager(client_id, client_secret=O365_CLIENT_SECRET (:619), redirect_uri=O365_REDIRECT_URI (:622),
  #   tenant_id=O365_TENANT_ID (:620) or "common", app, credential_store=…, event_publisher=…); setup();
  #   register_oauth2_provider(O365OAuth2Provider(manager=…))  (o365_provider.py:32)
  ```

### Module 4: Needs-auth in every chat mode + automatic retry
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/agent.py`; UI `src/lib/api/stream.ts`,
  `src/lib/components/agents/AgentChat.svelte`, `src/lib/components/agents/integrations/ConnectIntegrationPill.svelte`
- **Responsibility**: emit `AuthRequiredPayload` on streaming (trailer) and non-streaming (envelope) paths when
  the turn hit `authorization_required`; render the pill in both; connect through S-1's start route; auto-resend once.
- **Depends on**: S-1 M5 (`AuthRequiredPayload`, both exceptions' `to_payload`), S-1 M6 (`POST /api/v1/connections/{p}/start`), M1 (store events), M5 (`connections.svelte.ts`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/handlers/agent.py  (modifies)
  def _auth_required_from(ai_message: AIMessage) -> Optional[AuthRequiredPayload]:
      """First tool call whose result is a ToolResult (or dict) with status == "authorization_required";
      payload = AuthRequiredPayload(**result.metadata). ToolCall.result verified: models/basic.py:28;
      ToolResult.status/metadata: tools/abstract.py (:255, :258)."""
  async def _write_auth_required_trailer(self, stream_resp: web.StreamResponse, ai_message: AIMessage) -> None:
      """Write b"\\n\\x00" + json {"auth_required": payload, "turn_id": …} after the envelope frame; mirrors
      _write_suggestions_trailer (agent.py:2625); never raises (client cancellation excepted)."""
  #   non-streaming: after bot.ask (agent.py:1901), if _auth_required_from(response) → AuthRequiredEnvelope JSON (as :1916-1927)
  ```
  ```ts
  // ui/src/lib/components/agents/integrations/ConnectIntegrationPill.svelte  (modifies; props verified :7-17)
  let { provider, message, agentId, onConnected }: {
    provider: string; message: string; agentId: string;
    onConnected?: (provider: string) => void;          // new; authUrl prop REMOVED (start via startConnect)
  } = $props();
  // AgentChat.svelte: autoRetried: Set<string> keyed by the auth_required message id; resend via handleSend(...) (:757)
  // only when no newer user message exists; else render a Retry button → handleRetry (:1946)
  ```

### Module 5: Connections panel, store, API client, `/enable` removal
- **Path**: UI `src/lib/api/connections.ts` (new), `src/lib/stores/connections.svelte.ts` (new),
  `src/lib/components/account/ConnectionsPanel.svelte` (new), `src/pages/account/Connections.svelte` (new),
  `src/pages/account/LinkChannel.svelte` (new), `src/App.svelte`, `src/lib/nav.ts`, `src/lib/config.ts`,
  `src/lib/components/agents/integrations/IntegrationsMenu.svelte`, `src/lib/api/integrations.ts` (modify);
  server `server/ui/serving.py`, `handlers/integrations.py`, `manager/manager.py` (remove `/enable`);
  core `parrot/auth/oauth2/models.py`, `parrot/auth/oauth2/__init__.py` (remove `EnableResponse`);
  `scripts/generate_ts_types.py` (register models); `ui/schemas/*.json` + `src/lib/types/generated/*` (generated)
- **Responsibility**: user-level panel and link page; a single rune store for the list + SSE; menu reads the
  store; `/enable` removed everywhere; generated TS types for `IntegrationDescriptor`, `ConnectInitResponse`,
  `DisconnectResponse`, `AuthRequiredPayload`, `ConnectionEvent`.
- **Depends on**: M1 (SSE endpoint), S-1 M6 (routes and models).
- **Interface Skeleton**:
  ```ts
  // ui/src/lib/api/connections.ts  (new; axios client as integrations.ts:49)
  export async function listConnections(): Promise<IntegrationDescriptor[]>;                 // GET /api/v1/connections
  export async function getConnection(provider: string): Promise<IntegrationDescriptor>;     // GET /api/v1/connections/{p}
  export async function startConnect(provider: string, returnOrigin: string, scopes?: string[]): Promise<ConnectInitResponse>; // POST …/{p}/start
  export async function disconnect(provider: string): Promise<DisconnectResponse>;          // DELETE …/{p}
  export async function confirmChannelLink(token: string): Promise<{ channel: string; linked: boolean }>; // POST /api/v1/channel-links/{token}/confirm
  export function openConnectionEvents(onEvent: (e: ConnectionEvent) => void, signal: AbortSignal): Promise<void>; // fetch + getAuthHeaders (auth-headers.ts:16)

  // ui/src/lib/stores/connections.svelte.ts  (new)
  class ConnectionsStore {
    items = $state<IntegrationDescriptor[]>([]); loading = $state(false); live = $state(false);
    async refresh(): Promise<void>;
    start(): void;   // idempotent: opens the SSE reader once; backoff 1s→30s; refresh() on open and on each event
    stop(): void;
    onEvent(cb: (e: ConnectionEvent) => void): () => void;   // used by ConnectIntegrationPill / AgentChat
  }
  export const connectionsStore: ConnectionsStore;

  // ConnectionsPanel.svelte: rows = provider, status badge (connected | needs_reconnect | disconnected),
  //   account (display_account_name / email), scopes_granted, expires_at, channels; Connect / Reconnect / Disconnect.
  // LinkChannel.svelte: reads ?token, calls confirmChannelLink once, shows linked / expired (410) / error.
  // App.svelte routes: /account/connections, /account/link (requiresAuth: true; pattern App.svelte:21-63)
  // REMOVED: confirmIntegrationEnable (integrations.ts:89), EnableResponse TS type (:36-38), the menu's /enable call (IntegrationsMenu.svelte:64)
  ```
  ```python
  # handlers/integrations.py: REMOVED `if path.endswith("/enable")` branch (:103-104) and _post_enable (:163)
  # manager/manager.py: REMOVED route "/api/v1/agents/integrations/{agent_id}/{provider}/enable" (:2467-2468);
  #   ADDED "/api/v1/connections/events" (M1) and "/api/v1/channel-links/{nonce}/confirm" (M2) next to S-1's ConnectionsHandler routes
  # parrot/auth/oauth2/models.py: REMOVED EnableResponse (models.py:95) + its export
  # server/ui/serving.py: SPA_SECTIONS gains "/account" (:39) unless FEAT-772 TASK-4904 already added it
  ```

### Module 6: Retire the FEAT-083 hot-swap placeholder
- **Path**: `packages/ai-parrot/src/parrot/tools/jira_connect_tool.py` (delete);
  `packages/ai-parrot-server/src/parrot/handlers/agent.py` (remove `_bootstrap_jira_oauth_session` :1043 and its call :1035);
  `packages/ai-parrot/tests/unit/test_agentalk_jira_connect.py` (delete)
- **Responsibility**: remove dead code now that `JiraToolkit` declares `credential_provider="jira"` (S-1 M7).
- **Depends on**: S-1 M7.
- **Interface Skeleton**: none (deletion only); `grep -rn "jira_connect_tool\|JiraConnectTool\|hotswap_to_full_toolkit\|_bootstrap_jira_oauth_session" packages/*/src packages/*/tests` returns nothing afterwards.

### Module 7: Docs
- **Path**: `docs/auth/connections.md` (modify — created by S-1), `docs/auth/jira-credential-ownership.md`,
  `docs/integrations/office365-oauth2.md`, `docs/integrations/slack.md` (modify if present, else a Slack section in `connections.md`)
- **Responsibility**: Connections panel and SSE endpoint (frame format, auth, semantics); Slack linking flow
  and commands; close the "Known gap" (`jira-credential-ownership.md:60-84`) for Slack; O365 store section
  rewritten (one record, `grant_origin`, legacy migration; fixes the `:10` vs `:153` contradiction).
- **Depends on**: M1–M6.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_publisher_calls_sinks_for_every_channel` | M1 | event with `channel="telegram"` reaches a registered sink; raising sink is logged, publish succeeds |
| `test_redis_push_channel_per_principal` | M1 | `deliver` publishes on `parrot:connections:user:{user_id}` only; payload equals `ConnectionEvent` fields (no token keys) |
| `test_sse_handler_requires_session_and_ignores_query_user` | M1 | 401 without session; `?user_id=` ignored |
| `test_sse_frames_and_keepalive` | M1 | `event: connection` frames; keep-alive comment; unsubscribes on client disconnect |
| `test_sse_cross_worker_delivery` | M1 | two app instances on one Redis: publish on A, stream on B receives it |
| `test_channel_link_issue_consume_single_use` | M2 | consume once → claim; second consume / after TTL → None |
| `test_channel_link_confirm_uses_session_principal` | M2 | identity row written for the session user; body ignored; 410 on spent nonce; 403 non-numeric session id |
| `test_slack_connect_unlinked_replies_login` | M2 | no principal → "/login" reply, no OAuth state created |
| `test_slack_connect_linked_starts_with_principal` | M2 | `start_connect(channel="slack", principal=…)` called; DM button with auth URL |
| `test_slack_jira_aliases_delegate` | M2 | `/connect_jira` ≡ `/connect jira` |
| `test_slack_identity_key_team_qualified` | M2 | callback and link both write `provider_user_id="T:U"`; resolver finds it |
| `test_slack_connection_notifier_any_provider` | M2 | completed / revoked / refresh_failed DMs for jira and o365 |
| `test_o365_store_device_grant_durable_first` | M3 | store failure → `CredentialPersistenceError`, no Redis key; success → row with `grant_origin="device_code"` |
| `test_devicecode_resolver_reads_through_manager` | M3 | cache hit and refresh go through `get_valid_token`; no `VaultTokenSync` call |
| `test_devicecode_resolver_fails_closed_without_principal` | M3 | `resolve_principal` → None raises, no device flow |
| `test_devicecode_legacy_migration_once` | M3 | legacy `o365:*` read, rewritten, deleted; second resolve does not read legacy; no read after `OAUTH2_LEGACY_KEYS_UNTIL` |
| `test_o365_provider_registered_when_configured` | M3 | `O365_CLIENT_ID` set → `OAuth2ProviderRegistry.get("o365")`; unset → absent |
| `test_broker_device_code_deps_without_vault` | M3 | `_build_device_code` builds with `o365` + `o365_oauth_manager` only |
| `test_agenttalk_auth_required_from_tool_result` | M4 | non-streaming: tool result `authorization_required` → `AuthRequiredEnvelope` |
| `test_agenttalk_stream_auth_required_trailer` | M4 | streaming: trailer frame after envelope with full payload incl. device-code fields |
| `test_enable_route_removed` | M5 | `POST …/{provider}/enable` → 404; `EnableResponse` not importable |
| `test_jira_connect_tool_removed` | M6 | module absent; AgentTalk bootstrap gone |

### UI Tests (vitest, wrapped by pytest `tests/ui/test_vitest_*.py`)
| Test | Module | Description |
|---|---|---|
| `stream.test.ts` › auth_required trailer | M4 | parser yields `{type:"auth_required"}` |
| `AgentChat.test.ts` › streaming pill + auto-retry once | M4 | pill rendered in streaming mode; completion → one resend; second completion → none; newer user message → Retry button only |
| `ConnectIntegrationPill.test.ts` | M4 | uses `startConnect`; `onConnected` on popup success or matching SSE event |
| `connections.test.ts` (store) | M5 | refresh on open and per event; backoff; `stop` aborts |
| `ConnectionsPanel.test.ts` | M5 | renders status/account/scopes/expiry/channels; connect/disconnect actions |
| `LinkChannel.test.ts` | M5 | success, 410 expired, error |
| `IntegrationsMenu.test.ts` | M5 | reads the store; never calls `/enable` |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_slack_link_then_connect` | Slack `/login` → link confirm as web user → `/connect jira` → callback → Slack DM + identity-vault row for that Navigator user |
| `test_e2e_web_panel_live_update` | connect via callback for `channel="telegram"` → SSE subscriber of the same principal receives `connection.completed`; another principal's stream receives nothing |
| `test_e2e_o365_device_and_web_share_record` | device grant stored → `GET /api/v1/connections` shows o365 connected (`grant_origin` device_code) → 3LO reconnect replaces it |

### Validation Contract

runners:
- kind: pytest
  tests:
  - tests/auth/test_o365_oauth.py
  - packages/ai-parrot/tests/auth/test_o365_devicecode_resolver.py
  - packages/ai-parrot/tests/auth/test_broker_devicecode.py
  - packages/ai-parrot-server/tests/unit/test_vault_token_sync_atomic_persist.py
  - packages/ai-parrot-integrations/tests/integrations/slack/test_slack_jira_commands.py
  - packages/ai-parrot-integrations/tests/integrations/slack/test_slack_oauth_callback.py
  - packages/ai-parrot-integrations/tests/integrations/slack/test_slack_wrapper_jira.py
  - packages/ai-parrot-integrations/tests/integrations/test_jira_oauth_integration.py
  - tests/unit/integrations/oauth2/test_handler.py
  - tests/unit/integrations/oauth2/test_agenttalk_envelope.py
  - tests/unit/integrations/oauth2/test_models.py
  - tests/integration/oauth2/test_e2e_web_connect.py
  - tests/integration/oauth2/test_e2e_auth_envelope.py
  markers: none
- kind: vitest
  cwd: packages/ai-parrot-server/ui
  tests:
  - src/lib/api/stream.test.ts
  - src/lib/components/agents/AgentChat.test.ts

> `/sdd-task` adds the new test files above to the contract once their paths are frozen.

### Test Data / Fixtures
```python
@pytest.fixture
def principal() -> Principal:          # S-1 fixture shape
    return Principal(user_id="1042", canonical_identity="jlara@example.com", channel="slack", channel_user_id="T01:U02")

@pytest.fixture
def redis_push(redis_url):             # real Redis db 15 + unique prefix, skip if unreachable (no fakeredis in the venv)
    ...

@pytest.fixture
def fake_identity_mapping():           # records upsert_identity kwargs; raises ValueError on non-numeric nav_user_id like the real one
    ...

@pytest.fixture
def legacy_vault():                    # in-memory VaultTokenSync double: read_tokens / delete_tokens over {(canonical_id, "o365"): {...}}
    ...
```

---

## 5. Acceptance Criteria

- [ ] **AC-1 (G1)** `/account/connections` lists every registered provider for the logged-in principal with status, account, `scopes_granted`, `expires_at` and `channels`, and supports connect, reconnect and disconnect through `/api/v1/connections*` only.
- [ ] **AC-2 (G2, D1)** `GET /api/v1/connections/events` streams `text/event-stream` frames for the session principal only; the principal is never taken from the query or body; a keep-alive is sent at least every 30 s.
- [ ] **AC-3 (G2)** An event published by any worker (and for any originating channel) reaches every open stream of that principal on any worker within 2 s; no stream of another principal receives it; frames contain only `ConnectionEvent` fields.
- [ ] **AC-4 (G2)** No WebSocket route is added and `UserSocketManager` / `wsService` are unchanged.
- [ ] **AC-5 (G4, D2)** The `slack` identity row is written only by `POST /api/v1/channel-links/{nonce}/confirm` from an authenticated session (or by the OAuth callback when the state already carries a bound principal); nonces are single-use and expire after `CHANNEL_LINK_TTL_SECONDS`.
- [ ] **AC-6 (G4)** Slack `/connect <provider>` for an unlinked user replies with the `/login` instruction and creates no OAuth state; for a linked user it starts the flow with the resolved principal; completion, revocation and refresh failure are DMed for any provider; `/connect_jira`, `/disconnect_jira`, `/jira_status` keep working as aliases; Slack `provider_user_id` is `"{team_id}:{slack_user_id}"` everywhere.
- [ ] **AC-7 (G3)** Streaming and non-streaming AgentTalk responses carry the `AuthRequiredPayload` when a tool returned `authorization_required`; the UI shows the Connect pill in both modes; after a successful connect the originating prompt is re-sent exactly once, and never when a newer user message exists.
- [ ] **AC-8 (G5, D3)** O365 3LO and device-code grants are one principal-keyed record (`O365TokenSet.grant_origin`); `VaultTokenSync` is not called for `o365` by any code path except the one-time legacy read; `O365OAuth2Provider` is registered when `O365_CLIENT_ID` is set; the device-code resolver fails closed without a principal.
- [ ] **AC-9 (G6)** `/enable` (route, handler branch, `EnableResponse`, `confirmIntegrationEnable`) is gone; `IntegrationsMenu` and `ConnectIntegrationPill` call only `/api/v1/connections*`.
- [ ] **AC-10 (G6)** `jira_connect_tool.py`, `_bootstrap_jira_oauth_session` and `test_agentalk_jira_connect.py` are deleted with no remaining reference in `packages/`.
- [ ] **AC-11** API TS types for the connection models are generated from Pydantic (`scripts/generate_ts_types.py` → `schemas/` → `src/lib/types/generated/`), not hand-written.
- [ ] **AC-12** The Validation Contract passes, including the vitest runner; the multi-worker SSE, Slack linked/unlinked and O365 exactly-once migration tests pass; `ruff check` clean on touched Python files; Svelte 5 runes only; no `print`, `requests`/`httpx`.
- [ ] **AC-13** `docs/auth/connections.md`, `docs/auth/jira-credential-ownership.md` (Slack gap closed) and `docs/integrations/office365-oauth2.md` (one O365 record) are updated.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified 2026-10-30 against `dev` @ `370a62d9b`. S-1 (FEAT-773)
> symbols are **not in the tree yet**; they are listed under "Does NOT Exist" and become available only when
> FEAT-773 merges — re-verify their final signatures against `sdd/specs/delegated-auth-connections.spec.md` §2/§3
> and the merged code before use.

### Verified Imports
```python
from parrot.auth.o365_oauth import O365OAuthManager, O365TokenSet                           # verified: o365_oauth.py:55, :44
from parrot.auth.oauth2.o365_provider import O365OAuth2Provider                             # verified: o365_provider.py:32
from parrot.auth.oauth2.o365_devicecode_provider import O365DeviceCodeCredentialResolver    # verified: o365_devicecode_provider.py:73
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry, register_oauth2_provider    # verified: registry.py:69, :126
from parrot.auth.oauth2.models import IntegrationDescriptor, ConnectInitResponse, EnableResponse, DisconnectResponse, AuthRequiredEnvelope  # verified: models.py:21,79,95,105,117
from parrot.auth.oauth2.persistence import upsert_users_integration                         # verified: persistence.py:42
from parrot.auth.exceptions import AuthorizationRequired                                    # verified: exceptions.py:12
from parrot.models.basic import ToolCall                                                    # verified: models/basic.py:23 (result: Optional[Any] :28)
from parrot.tools.abstract import ToolResult                                                # verified: tools/abstract.py (status :255, metadata :258)
from parrot.conf import REDIS_URL, O365_CLIENT_ID, O365_CLIENT_SECRET, O365_TENANT_ID, O365_REDIRECT_URI, WEB_OAUTH_ALLOWED_ORIGINS  # verified: conf.py:308, 618-622, 751
# ai-parrot-server
from parrot.services.identity_mapping import IdentityMappingService                         # verified: identity_mapping.py:136
from parrot.services.vault_token_sync import VaultTokenSync                                 # verified: vault_token_sync.py:107
from parrot.handlers.integrations import IntegrationsHandler                                # verified: handlers/integrations.py:34
# ai-parrot-integrations
from parrot.integrations.slack.oauth_callback import SlackOAuthNotifier, handle_slack_jira_callback  # verified: slack/oauth_callback.py:74, :157
from parrot.integrations.slack.commands.jira_commands import register_jira_commands         # verified: slack/commands/jira_commands.py:166
import redis.asyncio as aioredis                                                            # pattern: handlers/user.py:20, liveavatar_output.py:126
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/auth/o365_oauth.py
class O365TokenSet(...)                                                       # :44
class O365OAuthManager(AbstractOAuth2Manager): provider_id = "o365" (:65); __init__(..., tenant_id="common") (:73);
    _exchange_code (:113); _refresh_request (:140); refresh_access_token (:167); _discover_identity (:190)   # :55

# packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py
_O365_VAULT_PREFIX: str = "o365"                                              # :46
class O365DeviceCodeCredentialResolver:                                       # :73
    def __init__(self, o365_client, o365_oauth_manager, vault_token_sync, scopes=None, prompt_callback=None)  # :100-116
    async def resolve(self, channel, user_id) -> Optional[str]                # :117; read :142; refresh via self._manager.refresh_access_token :159-176
    async def get_auth_url (:180); is_connected (:188); _run_device_flow(user_id) (:206); _persist_token_set (:237; store_tokens :272)

# packages/ai-parrot/src/parrot/auth/broker/factory.py
def _build_device_code(self, ...)                                             # :167-200; deps o365/o365_oauth_manager/vault required (:20-24 of the block)

# packages/ai-parrot-server/src/parrot/services/vault_token_sync.py
"Providers served here: fireflies, workiq, entra, o365"                       # :12
def _synth_session_uuid(nav_user_id, session_scheme=...)                      # :69
class VaultTokenSync: __init__(db_pool, redis, session_ttl=3600, session_scheme=...) (:139); store_tokens (:189); read_tokens (:303); delete_tokens (:317)  # :107

# packages/ai-parrot-server/src/parrot/services/identity_mapping.py
async def upsert_identity(self, *, nav_user_id: str, auth_provider: str, provider_user_id: str, auth_data: Dict,
                          display_name=None, email=None, token=None)          # :173-183; ValueError on non-numeric nav_user_id (:208-213)

# packages/ai-parrot-server/src/parrot/handlers/integrations.py
class IntegrationsHandler(BaseView): decorators (:31-32); _get_user_id (:43-63); post dispatcher (:90; '/enable' branch :103-104); _post_enable (:163)  # :34

# packages/ai-parrot-server/src/parrot/handlers/agent.py
await self._bootstrap_jira_oauth_session(...)  (:1035); async def _bootstrap_jira_oauth_session (:1043; import setup_jira_oauth_session :1072)
response: AIMessage = await bot.ask(...) (:1901); except AuthorizationRequired → AuthRequiredEnvelope JSON (:1916-1927)
async def _write_suggestions_trailer(self, stream_resp, bot, ai_message) (:2625; writes b"\n\x00" + json :2647)
async def _handle_stream_response(...) (:2650); headers X-Parrot-Stream "chunked-aimessage" (:2691); bot.ask_stream loop (:2708-2728)

# packages/ai-parrot-server/src/parrot/handlers/stream.py
SSE pattern: web.StreamResponse(headers={"Content-Type": "text/event-stream", …}) (:114-126)

# packages/ai-parrot-server/src/parrot/manager/manager.py
IntegrationsHandler routes (:2459-2472; /enable :2467-2468); on_startup _register_oauth2_providers (:2388); def (:2789; Jira only :2796-2806)

# packages/ai-parrot-server/src/parrot/server/ui/serving.py
SPA_SECTIONS: tuple[str, ...] = ("/login", "/agents")                        # :39 (used :136, :150)

# liveavatar Redis relay (pattern for M1)
integrations/liveavatar/output_transport.py: publish envelope (:72-82); run_output_subscriber subscribe + listen (:100-133)
server handlers/liveavatar_output.py: aioredis.from_url (:126); create_task (:128); on_startup/on_cleanup (:155-156)

# packages/ai-parrot-integrations/src/parrot/integrations/slack/
commands/jira_commands.py: _SLACK_CHANNEL = "slack" (:27); connect_jira_handler (:60; user_id f"{team_id}:{slack_user_id}" :77-79; create_authorization_url(..., extra_state={channel, team_id, slack_user_id}) :91-99); disconnect (:103); status (:132); register_jira_commands(router, oauth_manager) (:166)
oauth_callback.py: SlackOAuthNotifier (:74; notify_connected :97; notify_failure :127); handle_slack_jira_callback(request, token_set, state_payload) (:157); upsert_identity(... provider_user_id=slack_user_id ...) (:246-258, key :251)
wrapper.py: register_jira_commands (:128); app["slack_jira_oauth_notifier"] = SlackOAuthNotifier(bot_token=...) (:132); slash command payload team_id/user_id (:375-377)

# Admin UI (packages/ai-parrot-server/ui/src)
lib/api/integrations.ts: IntegrationDescriptor (:16-27); EnableResponse (:36-38); createApiClient (:49); BASE (:51-52); list (:58); start (:72); confirmIntegrationEnable (:89); disconnect (:103)
lib/oauth/popup.ts: POPUP_MESSAGE_TYPE "ai-parrot-oauth-callback" (:51); awaitOAuthCallback(options) (:66)
lib/components/agents/integrations/IntegrationsMenu.svelte: props { agentId } (:14); handleConnect (:50-83; confirmIntegrationEnable :64)
lib/components/agents/integrations/ConnectIntegrationPill.svelte: props provider/authUrl/message/agentId (:7-17); handleConnect (:21-52; confirm :30; toast :31-33)
lib/components/agents/AgentChat.svelte: handleSend (:757); streaming branch (:840-1199); auth_required detection (:1344); handleRetry (:1946); IntegrationsMenu (:2152); pill (:2468-2474)
lib/api/stream.ts: StreamChunk (:27-30); SEPARATOR "\x00" (:32)
lib/api/auth-headers.ts: getAuthHeaders (:16)
lib/services/websocket-service.ts: no-op stub (:1-76) — NOT to be changed
App.svelte: route table (:20-63); lib/nav.ts: NavSection (:13), entries (:29-54); lib/config.ts: appSections (:62)
scripts/generate_ts_types.py: _models() (:46-83); export_schemas (:117)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `RedisConnectionPush` | S-1 `ConnectionEventPublisher.add_sink` | sink registration at startup | S-1 spec §3 M4 (not in tree) |
| `ConnectionEventsHandler` | `RedisConnectionPush.subscribe` | async iterator | — (new) |
| `ChannelLinksHandler` | `IdentityMappingService.upsert_identity` | method call | `identity_mapping.py:173` |
| Slack `/connect` | S-1 `resolve_principal`, `IntegrationsService.start_connect(channel=, principal=)` | function/method | S-1 spec §3 M1/M6 |
| `SlackConnectionNotifier` | S-1 `ChannelNotifierRegistry.register` | registration in `slack/wrapper.py` | `slack/wrapper.py:132` (replaces) |
| `O365DeviceCodeCredentialResolver` | `O365OAuthManager.get_valid_token` / `store_device_grant` | method calls | `o365_devicecode_provider.py:142, :272` (replaced sites) |
| `_register_oauth2_providers` | `register_oauth2_provider(O365OAuth2Provider(manager=…))` | function call | `manager.py:2789`, `registry.py:126` |
| AgentTalk streaming | `_write_auth_required_trailer` | after envelope frame | `agent.py:2625` (pattern) |
| `connections.svelte.ts` | `GET /api/v1/connections/events` | fetch stream | `stream.ts` pattern, `auth-headers.ts:16` |

### Does NOT Exist (Anti-Hallucination)
- ~~S-1 symbols~~ `Principal`, `resolve_principal`, `CredentialStore`, `ConnectionEvent`, `ConnectionEventPublisher`, `ChannelNotifier`, `ChannelNotifierRegistry`, `AuthRequiredPayload`, `ConnectionsHandler`, `IdentityPrincipalResolver`, `IdentityVaultCredentialStore`, `SlackJiraNotifierAdapter`, `OAUTH2_LEGACY_KEYS_UNTIL`, `/api/v1/connections*` — **FEAT-773, not merged at spec time**.
- ~~`ConnectionEventSink`, `add_sink`, `RedisConnectionPush`, `ConnectionEventsHandler`, `ChannelLinkIssuer`, `ChannelLinkClaim`, `ChannelLinksHandler`, `SlackConnectionNotifier`, `register_connection_commands`, `store_device_grant`, `O365TokenSet.grant_origin`, `CONNECTIONS_LINK_BASE_URL`, `CHANNEL_LINK_TTL_SECONDS`~~ — new in this spec.
- ~~A WebSocket client in the admin UI~~ — `websocket-service.ts` is a no-op stub (FEAT-476); ~~`UserSocketManager` in ai-parrot-server's app~~ — only repo-root `app.py:229-235` builds it.
- ~~`EventSource` with an `Authorization` header~~ — browsers cannot set headers on `EventSource`; use fetch streaming.
- ~~A Slack login / auth strategy / session `nav_user_id`~~ — none under `integrations/slack/` (Telegram: `telegram/auth.py:377`; Teams: `msteams/auth.py:256`).
- ~~`users.info` e-mail lookup in the Slack wrapper~~ — only in `slack/knowledge_upload.py:214-218` and `slack/devloop/actions.py:256-257`; not used for identity (D2 rejects e-mail auto-link).
- ~~`O365OAuth2Provider` registration in src~~ — docstring example only (`o365_provider.py:8-14`).
- ~~In-tree production wiring of the device-code resolver deps~~ — bot attrs `_vault`, `_o365_interface`, `_o365_oauth_manager` (`bots/abstract.py:1765-1777`) are set nowhere.
- ~~A `/account` section, page or nav entry~~ — planned by FEAT-772 (TASK-4902–4904, pending); `SPA_SECTIONS` is `("/login", "/agents")`.
- ~~`AuthRequiredEnvelope` / `IntegrationDescriptor` generated TS types or JSON schemas~~ — hand-written in `integrations.ts:16-43`; `AgentMessage` has loose `type/provider/auth_url/scopes` (`types/agent.ts:39-43`).
- ~~An `auth_required` stream frame~~ — `StreamChunk` has `chunk|done|suggestions` only (`stream.ts:27-30`).
- ~~A caller of `hotswap_to_full_toolkit`~~ — none in src; `agent.jira_credential_resolver` is set nowhere.
- ~~`"o365:` string literals~~ — keys are built from `_O365_VAULT_PREFIX` + `VaultTokenSync` `{provider}:{field}`.

### Edit Sites (Blueprint Anchors)

Verified against: `370a62d9b` (`dev`, 2026-10-30). S-1 files are listed as **(S-1)** — their anchors do not
exist until FEAT-773 merges; `/sdd-task` MUST re-verify every row with `grep -c`.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/events.py` | MODIFY (S-1) | `class ConnectionEventPublisher` | (unverified — created by FEAT-773 M4) | — |
| `packages/ai-parrot-server/src/parrot/services/connection_push.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/connection_events.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/handlers/channel_links.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `            "/api/v1/agents/integrations/{agent_id}/{provider}/enable",` | `manager.py:2467` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `    async def _register_oauth2_providers(self, app: web.Application) -> None:` | `manager.py:2789` | 1 |
| `packages/ai-parrot-server/src/parrot/services/identity_principal.py` | MODIFY (S-1) | `class IdentityPrincipalResolver` | (unverified — created by FEAT-773 M8) | — |
| `packages/ai-parrot/src/parrot/auth/channel_link.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `WEB_OAUTH_ALLOWED_ORIGINS = config.get("WEB_OAUTH_ALLOWED_ORIGINS", fallback=[])` | `conf.py:751` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/connection_commands.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/notifier.py` | CREATE | — | — | — |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/jira_commands.py` | MODIFY | `async def connect_jira_handler(` | `slack/commands/jira_commands.py:60` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/jira_commands.py` | MODIFY | `def register_jira_commands(` | `slack/commands/jira_commands.py:166` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py` | MODIFY | `provider_user_id=slack_user_id` | `slack/oauth_callback.py:251` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` | MODIFY | `app["slack_jira_oauth_notifier"] = SlackOAuthNotifier(` | `slack/wrapper.py:132` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` | MODIFY | `register_jira_commands(` | `slack/wrapper.py:128` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py` | MODIFY (S-1) | `class SlackJiraNotifierAdapter` | (unverified — created by FEAT-773 M8) | — |
| `packages/ai-parrot/src/parrot/auth/o365_oauth.py` | MODIFY | `class O365OAuthManager(AbstractOAuth2Manager)` | `o365_oauth.py:55` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py` | MODIFY | `class O365DeviceCodeCredentialResolver` | `o365_devicecode_provider.py:73` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py` | MODIFY | `async def _persist_token_set(` | `o365_devicecode_provider.py:237` | 1 |
| `packages/ai-parrot/src/parrot/auth/broker/factory.py` | MODIFY | `def _build_device_code(` | `broker/factory.py:167` | 1 |
| `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py` | MODIFY | `Providers served here` | `vault_token_sync.py:12` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `async def _write_suggestions_trailer(` | `handlers/agent.py:2625` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `await self._bootstrap_jira_oauth_session(` | `handlers/agent.py:1035` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `async def _bootstrap_jira_oauth_session(` | `handlers/agent.py:1043` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/integrations.py` | MODIFY | `if path.endswith("/enable"):` | `handlers/integrations.py:103` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/integrations.py` | MODIFY | `async def _post_enable(self) -> web.Response:` | `handlers/integrations.py:163` | 1 |
| `packages/ai-parrot/src/parrot/auth/oauth2/models.py` | MODIFY | `class EnableResponse(BaseModel):` | `models.py:95` | (verify — S-1 edits this file) |
| `packages/ai-parrot/src/parrot/tools/jira_connect_tool.py` | DELETE | — | — | — |
| `packages/ai-parrot/tests/unit/test_agentalk_jira_connect.py` | DELETE | — | — | — |
| `packages/ai-parrot-server/src/parrot/server/ui/serving.py` | MODIFY | `SPA_SECTIONS: tuple[str, ...] = ("/login", "/agents")` | `serving.py:39` | 1 |
| `scripts/generate_ts_types.py` | MODIFY | `def _models(` | `generate_ts_types.py:46` | 1 |
| `packages/ai-parrot-server/ui/src/lib/api/connections.ts` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/stores/connections.svelte.ts` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/components/account/ConnectionsPanel.svelte` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/pages/account/Connections.svelte` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/pages/account/LinkChannel.svelte` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/api/integrations.ts` | MODIFY | `export async function confirmIntegrationEnable(` | `integrations.ts:89` | 1 |
| `packages/ai-parrot-server/ui/src/lib/api/stream.ts` | MODIFY | `export type StreamChunk =` | `stream.ts:27` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/integrations/IntegrationsMenu.svelte` | MODIFY | `confirmIntegrationEnable(agentId, provider)` | `IntegrationsMenu.svelte:64` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/integrations/ConnectIntegrationPill.svelte` | MODIFY | `confirmIntegrationEnable(agentId, provider)` | `ConnectIntegrationPill.svelte:30` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.svelte` | MODIFY | `if (rawResult.type === "auth_required")` | `AgentChat.svelte:1344` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.svelte` | MODIFY | `<ConnectIntegrationPill` | `AgentChat.svelte:2469` | 1 |
| `packages/ai-parrot-server/ui/src/App.svelte` | MODIFY | `path: "/agents"` | `App.svelte:23` | 1 |
| `packages/ai-parrot-server/ui/src/lib/nav.ts` | MODIFY | `section: "user"` | `nav.ts:34` | 1 |
| `packages/ai-parrot-server/ui/src/lib/config.ts` | MODIFY | `appSections:` | `config.ts:62` | 1 |
| `docs/auth/jira-credential-ownership.md` | MODIFY | `Known gap` | `jira-credential-ownership.md:60` | 1 |
| `docs/integrations/office365-oauth2.md` | MODIFY | `user_credentials` | `office365-oauth2.md:153` | 1 |
| `docs/auth/connections.md` | MODIFY (S-1) | (created by FEAT-773 M10) | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Core never imports server/integrations** — `ConnectionEventSink` and `ChannelLinkIssuer` live in core; the server registers `RedisConnectionPush` and serves the confirm route; Slack imports core only (S-1 Protocol-injection pattern).
- **Redis cross-worker relay** — copy `liveavatar/output_transport.py::run_output_subscriber` (:100-133) and the startup/cleanup wiring in `handlers/liveavatar_output.py` (:126-156). One subscriber connection per SSE request; always unsubscribe on cancellation.
- **SSE response** — `handlers/stream.py:114-126` headers (it already sends `X-Accel-Buffering: no`, :130).
- **Principal from the session only** — `IntegrationsHandler._get_user_id` (`integrations.py:43-63`) for both new handlers.
- **NUL-framed trailers** — the `auth_required` trailer reuses the FEAT-752 suggestions framing (`agent.py:2625-2648`); clients that ignore unknown trailers keep working.
- **Svelte 5 runes, shared state in `.svelte.ts`**, axios client from `createApiClient()`, fetch streaming with `getAuthHeaders()`; vitest tests next to components, each wrapped by a `tests/ui/test_vitest_*.py` pytest file.
- **Fail closed** — unresolvable principal (Slack, device code) means no OAuth state and no token, never a channel-keyed fallback (S-1).

### Known Risks / Gotchas
- **Hard dependency on FEAT-773.** Every S-1 symbol in §6 "Does NOT Exist" must be merged; if S-1's final signatures differ from its spec, update this spec's skeletons first.
- **Device-code principal before S-4.** The resolver's `user_id` today is an e-mail/OID. Until S-4's CLI resolver exists, `resolve_principal("cli", <email/OID>)` must use the same canonical-identity lookup S-1 builds for `a2a`; if that lookup cannot run in a process without the auth DB, the device-code path fails closed. In-tree production wiring of this resolver does not exist today (`bots/abstract.py:1765-1777` attrs set nowhere), so the blast radius is external deployments only — announce it. Coordinate with FEAT-774, which plans to turn this resolver into a generic RFC 8628 engine: S-3a changes its storage, S-4 its engine.
- **One O365 record, two grant types.** A 3LO reconnect replaces a device-code grant and vice versa (single account per provider, S-1 S3). Both refresh through `O365OAuthManager.refresh_access_token`, so the confidential client registration must accept refresh tokens minted by device code; this is already true today (`o365_devicecode_provider.py:159-176`) — keep a regression test.
- **Legacy `o365:*` keys are keyed by e-mail/OID**, not by Navigator id; the migration needs the canonical id from the principal. Unresolvable legacy entries stay until the window closes and are then ignored.
- **SSE behind proxies** — buffering proxies break streams; send `X-Accel-Buffering: no` and keep-alives ≤ 25 s. Gunicorn worker timeouts must not kill idle streams (keep-alive covers it).
- **Redis connection count** — one pubsub connection per open panel tab; the store opens at most one stream per tab and closes it on `stop()` / page hide.
- **Auto-retry replays a whole turn.** Tools that ran before the auth failure in the same turn run again; the at-most-once rule and the "no newer message" rule bound it. If a provider requires several connects in one turn, only the last completion triggers the resend.
- **`/account` collides with FEAT-772** (TASK-4903/4904 pending) on `App.svelte`, `nav.ts`, `config.ts`, `serving.py`. Check `origin/dev` before editing; never duplicate the section entry.
- **Removing `/enable`** breaks any external client still calling it (the TROC AgentChat repo was not inspected in FEAT-773 research). S-1 kept it as a no-op precisely for the admin UI; confirm no other caller before deleting.
- **Slack identity key change** — existing `slack` rows with a bare `slack_user_id` are effectively none (the callback writes them only when `nav_user_id` is present, which Slack never sent); no migration needed, but the resolver must not fall back to the bare id.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `redis.asyncio` | existing | pub/sub fan-out, link nonces |
| `aiohttp` | existing | SSE `StreamResponse`, handlers |
| `slack_sdk` | existing | `AsyncWebClient` DMs (as `SlackOAuthNotifier`) |
| `json-schema-to-typescript` (ui devDep) | existing | `pnpm generate` |

---

## 8. Open Questions

- [x] Push transport for the web panel — *Resolved at spec time (D1)*: SSE endpoint fed by per-principal Redis pub/sub; FEAT-476's no-WebSocket decision kept.
- [x] Slack user ↔ Navigator principal link — *Resolved at spec time (D2)*: Slack `/login` DMs a signed one-time link; the logged-in web session confirms it and writes the `slack` identity row. E-mail auto-link rejected.
- [x] O365 scope in S-3a — *Resolved at spec time (D3)*: full consolidation — 3LO and device code share one principal-keyed record; `VaultTokenSync` stops serving `o365`.
- [x] Multi-account, PBAC on connect/disconnect, needs-auth payload, durable-first persistence — *Resolved in S-1* (S3, S4/AC-8, S8/M5, S2/AC-5); not reopened here.
- [ ] PBAC evaluation for chat-channel starts (Slack `/connect`) when there is no HTTP request — S-3a calls `IntegrationsService.start_connect(channel="slack", principal=…)` and must not bypass whatever S-1 M6 settles — *Owner: implementer of S-1 M6 / Jesus*.
- [ ] `CONNECTIONS_LINK_BASE_URL` default — first entry of `WEB_OAUTH_ALLOWED_ORIGINS` or required config — *Owner: Jesus*.
- [ ] External callers of `/api/v1/agents/integrations/{agent}/{provider}/enable` (TROC AgentChat repo) before removal — *Owner: Jesus*.
- [ ] Ordering with FEAT-772 for the `/account` section — *Owner: whoever starts second* (check `origin/dev`).
- [ ] Device-code `resolve_principal("cli", …)` in processes without the auth DB until S-4 lands — accept fail-closed, or keep a time-boxed legacy read path — *Owner: Jesus, with FEAT-774*.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the accepted parent exploration doc (FEAT-773 proposal,
> scoped to the S-3a row) — never over this spec.
> Model: `gpt-5.6-luna` (codex-cli 0.164.0) · Status: completed · Transcript: `sdd/state/FEAT-777/design_research/`
> All cited paths passed containment and existence checks.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make durable persistence a required completion outcome (risk) | REJECT | Owned by S-1 (M2, AC-5); M3 reuses `_persist_token`. | — |
| S2 | Resolve and bind the Navigator principal before OAuth starts (architecture) | CONFIRM | Slack `/connect` fails closed without a principal; only a web session creates the link. | §2, M2, AC-5/AC-6 |
| S3 | Choose and enforce multi-account semantics (api) | REJECT | Decided in S-1 (S3): single account, replace on reconnect. | — |
| S4 | Remove agent enablement as a complete contract migration (architecture) | CONFIRM | `/enable` removed end to end in M5. | M5, AC-9 |
| S5 | Persist the metadata the Connections API promises (api) | REJECT | S-1 M6 adds the fields; S-3a renders them. | — |
| S6 | Apply PBAC to connect and revoke (risk) | REJECT | S-1 AC-8; new confirm route is session-bound to the caller. | — |
| S7 | Route push events by principal, cross-process (architecture) | CONFIRM (modified) | SSE instead of WS (D1); Redis per-principal channel; refetch-on-event semantics. | §2, M1, AC-2/AC-3 |
| S8 | Define connection events separately from usage fanout (architecture) | REJECT | S-1 M4 owns the event model and fanout; S-3a tests SSE frames carry only its fields. | — |
| S9 | Specify an idempotent retry contract for the UI (api) | CONFIRM | At-most-once resend keyed by message id; no-newer-message rule. | §2, M4, AC-7 |
| S10 | Normalize needs-auth at a shared boundary (alternative) | REJECT | S-1 M5; the streaming trailer carries the full payload. | — |
| S11 | Keep provider-specific store capabilities explicit during O365 migration (alternative) | CONFIRM (modified) | Full consolidation per D3, with `grant_origin` recorded; one refresh path already shared. | M3, §7 |
| S12 | Make migration correctness a cross-channel acceptance gate (testing) | CONFIRM | Multi-worker SSE, Slack linked/unlinked, O365 exactly-once tests. | §4, AC-12 |

Summary: **6** confirmed (2 modified) · **6** rejected (owned by S-1) · **0** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree (`feat-FEAT-777-connections-web-slack`), created only after FEAT-773 is merged into `dev`; the `sdd-coder` engine gives each task its own sub-worktree.
- **Module dependency graph**:
  - M1 → S-1 M4 (publisher); M5 → M1 (`connections.svelte.ts` reads the SSE endpoint)
  - M4 → M5 (pill and AgentChat use `connections.svelte.ts` / `connections.ts`), M4 → S-1 M5
  - M2 → S-1 M1/M6/M8; M3 → S-1 M2/M8; M6 → S-1 M7; M7 → M1–M6
  - Concurrent: M1 ∥ M2 ∥ M3 ∥ M6; then M5; then M4; M7 last.
- **Shared files** (tasks serialized): `manager/manager.py` (M1 route, M2 route, M3 registration, M5 `/enable` removal); `handlers/agent.py` (M4, M6); `parrot/auth/oauth2/models.py` + `__init__.py` (M5 only, but S-1 edits them); `parrot/conf.py` (M2); `AgentChat.svelte` (M4 only).
- **Exclusive resources**: `pnpm generate` rewrites `ui/schemas/` and `ui/src/lib/types/generated/` (M5 task `parallel: false`); no lockfile, no DB migration.
- **Cross-feature dependencies**: **FEAT-773 (S-1) must be merged first.** Coordinate with FEAT-772 (`/account` section files) and FEAT-774 (S-4; `o365_devicecode_provider.py`).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-30 | Jesus Lara (with Claude Opus 5.5) | Initial draft from the S-3a row of the FEAT-773 proposal and the S-1 Non-Goals. Decisions D1 (SSE, keep FEAT-476), D2 (Slack link via web session), D3 (full O365 consolidation). Codex design research: 6 confirm / 6 reject (S-1-owned). Contract verified at `370a62d9b`. |

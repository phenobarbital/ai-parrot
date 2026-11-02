# Delegated OAuth2 connections

This guide describes the principal-keyed OAuth2 connection model introduced by
FEAT-773. A connection belongs to a Navigator principal, not to the channel
through which it was created.

## Principal and key layout

The live Redis cache uses `oauth2:{provider}:{user_id}`. The refresh lock is
`lock:oauth2:{provider}:refresh:{user_id}` and the short-lived state nonce is
`oauth2:{provider}:nonce:{nonce}`. These keys contain no channel component.

During migration, older channel-scoped keys may still exist:
`oauth2:{provider}:{channel}:{user_id}` and Jira's
`jira:oauth:{channel}:{user_id}`. They are read at most once during the
migration window, rewritten to the principal key when a principal resolves,
and then retired. Do not use `KEYS`; operational audits use Redis `SCAN`.

## Adding a provider

Add a provider descriptor to the YAML file named by `OAUTH2_PROVIDERS_FILE`.
The descriptor supplies the provider endpoints, scopes, PKCE behavior and
refresh policy. Keep client material in the environment:
`OAUTH2_<PROVIDER>_CLIENT_ID`, `OAUTH2_<PROVIDER>_CLIENT_SECRET`, and
`OAUTH2_<PROVIDER>_REDIRECT_URI` (with the provider name upper-cased).

Provider-specific post-exchange behavior is registered by hook name in the
typed hook registry. Descriptors name the hook; they do not import arbitrary
Python paths.

## Durable owner

The Identity Vault (`auth.user_identities`) owns every 3LO provider grant,
through the `CredentialStore` protocol. Redis is the hot cache used by live
tool calls. Writes are durable-first, then cached; a successful callback is not
reported until the durable write succeeds.

## Channel adapters

Channels publish completion and revocation through `ChannelNotifier`. They
resolve channel identities to Navigator principals through `PrincipalResolver`.
The callback and notifier registry must remain in the same process for the
load-bearing in-process delivery path; the publish-only event bus is the
cross-process fallback.

| Channel | Notifier | Commands | Guide |
|---|---|---|---|
| Telegram | generic `TelegramConnectionNotifier` | `/connect [<provider>]`, `/disconnect <provider>`, `/connections` (+ Jira / Office365 aliases) | [Telegram connections](../integrations/telegram-connections.md) |

## Needs-auth contract

Tools and handlers use `AuthRequiredPayload` for both authorization-required
and credential-required outcomes. The payload carries the provider, channel,
principal-safe connection details and any device-code fields needed by the
client; token values are never included.

## Connections panel

The `/account/connections` page lists every registered provider for the logged-in
principal (status, account, scopes granted, expiry, channels seen) with Connect /
Reconnect / Disconnect, over S-1's `/api/v1/connections*`. The panel shares the
same store as the per-agent `IntegrationsMenu` (`/api/v1/agents/integrations/{agent_id}`).

## Live updates (SSE)

`GET /api/v1/connections/events` streams the principal's `connection.*` events
as Server-Sent Events, delivered across gunicorn workers through a per-principal
Redis pub/sub channel. No WebSocket is added (FEAT-476's non-goal stands);
`UserSocketManager` is untouched.

**Frame format:**
```
event: connection
data: <ConnectionEvent JSON>

: keep-alive
```

The stream is a hint; `GET /api/v1/connections` is authoritative. The client
refetches the list on every (re)connect and on every event, so duplicates and
gaps are harmless. Because the admin UI authenticates with a bearer header from
`localStorage`, the client reads the stream with `fetch` + `ReadableStream`
(the same pattern as `stream.ts`), not `EventSource`.

**Auth:** session principal only (via `@is_authenticated` + `@user_session`).

**Keep-alive:** every 25 s (`KEEPALIVE_SECONDS`).

**Redis channel:** `parrot:connections:user:{user_id}`.

## Slack linking

Slack `/login` (and `/connect` when unlinked) DMs a one-time link:
`{CONNECTIONS_LINK_BASE_URL}/account/link?token={nonce}`. The logged-in admin
UI previews both identities and requires explicit confirmation before
exclusively claiming the Slack identity for that session's Navigator user.

**Routes:**
- `GET /api/v1/channel-links/{nonce}` — read-only preview; 410 when the claim
  is absent.
- `POST /api/v1/channel-links/{nonce}/confirm` — explicit confirm; 409 conflict
  if already linked, 410 if expired.

**Behavior:**
- Loading the preview page never confirms or consumes the claim.
- Only an explicit Confirm click calls `POST …/confirm` with `{confirm: true}`.
- Cancel performs no write.
- The server consumes the nonce and calls
  `IdentityMappingService.claim_channel_identity` exclusive ownership.

**v1 limits:** single account per provider, no Slack relinking/transfer (admin
action), one Slack bot token for notifications, `/enable` status per spec §8.

## Slack commands

Generic Slack commands (no provider-specific logic):
- `/login` — DMs the link URL; unlinked users must run this first.
- `/connect <provider>` — starts a connection for `<provider>` (e.g. `jira`).
- `/disconnect <provider>` — revokes a connection for `<provider>`.
- `/connections` — lists the user's connections.

Provider-specific aliases (`/connect_jira`, `/disconnect_jira`, etc.) stay as
aliases for backward compatibility.

## Needs-auth retry

AgentTalk detects an `authorization_required` `ToolResult` among the turn's
tool calls and S-1's re-raised exceptions, and emits S-1's
`AuthRequiredPayload`:

- **Non-streaming:** the existing `AuthRequiredEnvelope` JSON.
- **Streaming:** a trailer frame
  ```
  \x00{"auth_required": {...payload}, "turn_id": "...", "retry_safe": false}
  ```
  after the envelope, the same framing as the FEAT-752 suggestions trailer.

The UI renders the Connect pill in both modes. On success — popup `postMessage`
**or** an SSE `connection.completed` for the same provider — it calls
`onConnected`, and `AgentChat` re-sends the user message only when the server
authorizes it.

**Server-authored `retry_safe`:** set only from complete turn-local execution
evidence showing no tool body began; missing evidence, any begun tool (even
failed/cancelled), delegation or an uninstrumented execution path means false.
A tool's own metadata cannot assert safety. Both response modes carry the flag
outside `AuthRequiredPayload`; absent means false.

**Auto-resend:** at most once keyed by the originating user message ID, and only
if no newer user message exists. Otherwise the user explicitly chooses whether
to retry. A retried response retains the originating message ID so repeated
auth failures cannot reset the budget. Multiple outstanding auth requirements
disable auto-retry; v1 exposes the first pill and requires manual retry.

**Manual retry:** shows a Retry button explaining that completed actions may
repeat.

## PBAC without a request

Slack, Microsoft Teams and CLI connection commands (`/connect`, `/disconnect`,
`/connections`) all use the injected `NavigatorConnectionAuthorizer` (via
`IntegrationsService._authorizer`) for request-independent authorization — it
is the single non-web policy surface. The authorizer evaluates PBAC policies
with the session principal as the subject and `integration:list`,
`integration:connect` or `integration:disconnect` as the action; roles, groups
and tenant come from the Navigator auth database. Teams additionally checks its
`PermissionContext` identity before the authorizer runs. The service fails closed when no PDP
is available.

**Policy effect:** explicit `ALLOW` only; no implicit allow. The resource
integration is `integration:<provider>` (e.g. `integration:jira`).

## API

The principal-level API is rooted at `/api/v1/connections`:

- `GET /api/v1/connections` lists connections for the authenticated principal.
- `POST /api/v1/connections/{provider}/start` starts a connection.
- `GET /api/v1/connections/{provider}` inspects one connection.
- `DELETE /api/v1/connections/{provider}` revokes one connection.

Mutating operations evaluate PBAC in the navigator-auth PDP with
`integration:connect` or `integration:disconnect`. The requested provider and
scopes are part of the PDP evaluation context, and the service fails closed
when no PDP is available.

## Migration window

Set `OAUTH2_LEGACY_KEYS_UNTIL` to the S-1 production deploy time plus 30 days.
Before that deadline, run:

```bash
python -m parrot.auth.oauth2.legacy_audit
```

The command reports bound and unbound counts by provider and channel without
printing user IDs or token values. There is no unbound-count retirement gate:
unbound Telegram keys represent users who must reconnect.

## Sample PDP policy

The policy lives in the navigator-auth PDP. A minimal shape is:

```yaml
actions:
  integration:connect:
    allow: subject.authenticated and resource.provider in subject.allowed_providers
  integration:disconnect:
    allow: subject.authenticated and resource.provider in subject.allowed_providers
```

The deployed policy should also constrain tenant, provider and requested scopes
according to the organization's authorization model.

## Key rotation

Add and activate the new Identity Vault key on every writer, then run the
re-encryption job with `--apply`:

```bash
python -m parrot.auth.oauth2.reencrypt --apply
```

Verify every token column with only the active key and require `stale == 0`
and `failed == 0` across all providers sharing the retiring key before
retiring it. A provider-filtered run cannot authorize global key retirement.

## CLI consumers

CLI requests authenticate with the bearer from `parrot login`. The relevant
routes under `/api/v1/connections` are:

- `GET /me` returns the Navigator user id, email, tenant, and roles represented
  by the bearer.
- `POST /{provider}/start` with `{"channel": "cli"}` starts browser consent
  and returns the state and authorization URL used by polling or pasted
  completion.
- `POST /{provider}/complete` with `code` and `state` completes a callback
  pasted into the CLI.
- `POST /{provider}/device/start` starts a server-mediated provider device
  grant; `POST /{provider}/device/poll` with its opaque `handle` polls it.
- `POST /{provider}/token` returns the provider access token, expiry, scopes,
  and account id. It never returns a refresh token.

Token pulls evaluate the fail-closed PBAC action `integration:use` with the
provider in context and publish an audit event without token material. If no
active connection exists, `POST /{provider}/token` returns HTTP 409 with an
`AuthRequiredPayload` JSON body. CLI clients refresh their login once after an
HTTP 401, persist a rotated refresh token when supplied, and retry the request
once.

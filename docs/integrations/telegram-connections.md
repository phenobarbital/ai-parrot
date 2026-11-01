# Telegram connections

Telegram bots expose the delegated OAuth2 connections of
[`docs/auth/connections.md`](../auth/connections.md) to the user's linked
Navigator principal. Grants are owned by the principal, not by the Telegram
chat. Code: `parrot/integrations/telegram/connection_commands.py`,
`connection_notifier.py`, `post_auth_connection.py`, `wrapper.py`, and the
channel-neutral `parrot/integrations/core/auth/connections.py`
(`ConnectionCommandService`).

## Commands

| Command | Behaviour |
|---|---|
| `/connect` | Shows a provider picker (one inline button per connectable provider). |
| `/connect <provider>` | Starts the OAuth2 flow and replies with a `Connect <Provider>` URL button. Replies "already connected" when the grant covers the requested scopes. `office365` is an alias of `o365`; names are case-insensitive. |
| `/disconnect <provider>` | Revokes the principal's grant. Without an argument it replies `Usage: /disconnect <provider>`. |
| `/connections` | One line per connectable provider: `<Provider>: <status> [as <account>]`. |
| `/connect_jira`, `/disconnect_jira`, `/jira_status` | Aliases, registered only when a connectable `jira` provider exists. |
| `/connect_office365`, `/disconnect_office365`, `/office365_status` | Registered when any provider is connectable or the bot uses the `oauth2` login method. |

Rules:

- Connection commands work **only in a private chat**. Elsewhere the bot replies
  "Please use a private chat with the bot to manage connections."
- The user must be logged in; otherwise the bot replies
  "Please /login first to link your Telegram account."
- All replies are **plain text** (`parse_mode=None`).
- Completion, revocation and refresh failures are delivered asynchronously by
  `TelegramConnectionNotifier` (e.g. `Jira connected as <account>.`,
  `<Provider> access expired — /connect <provider> to reconnect.`).

The provider list comes from `OAuth2ProviderRegistry`. A provider is
connectable when it has a manager, its id does not start with `mcp:`, and it
passes the allowlist below.

## Configuration (`connection_providers`, `post_auth_actions`)

```yaml
agents:
  my_bot:
    chatbot_id: my_agent
    # Optional allowlist; omit (null) to expose every connectable provider.
    connection_providers: [jira, o365]
    # Optional staged login: secondary authorizations after the primary login.
    post_auth_actions:
      - provider: jira
        required: true
      - provider: o365
        required: false
```

`post_auth_actions` accepts any provider registered in `OAuth2ProviderRegistry`
(each is driven by the generic `ConnectionPostAuthProvider`). An unknown
provider only produces a startup warning.

## Linking your Telegram account (/login, /logout)

A successful `/login` persists the Telegram -> Navigator principal link
(channel identity `telegram:<telegram_id>`); a session that predates the link
is backfilled on its next message. Connections resolve through this link.

`/logout` cancels any pending staged login, **unlinks** the Telegram identity
and clears the session. It does not revoke connections: they belong to the
principal. Use `/disconnect <provider>` for that.

## Permissions (deploy precondition)

Authorization goes through the shared `ConnectionAuthorizer` in
`app["connection_authorizer"]` (the same one Slack, Teams and the CLI use),
passed to `IntegrationsService`. Actions checked:

- `integration:list` — `/connections` (a denial yields an empty list)
- `integration:connect` — `/connect`, the needs-auth Connect button, staged login
- `integration:disconnect` — `/disconnect`

The integrations surface fails **closed**. Before enabling Telegram
connections, deploy a policy granting `integration:connect` and
`integration:disconnect` for the intended provider and scopes (see the sample
policy in `connections.md`) and make sure the production authorizer has
parity with that policy (FEAT-775 prerequisite). Without it `/connect` replies
"Connecting <Provider> is not allowed for your account."

## When a tool needs a connection

When a tool reports `AuthRequiredPayload` during a turn, the bot first delivers
the agent's reply, then (private chats only) sends one prompt per provider:

- device-code providers: `To connect <provider>, visit <uri> and enter code <code>.`
- otherwise: a `Connect <Provider>` URL button for the union of requested scopes
  (or the "not allowed" / "already connected" text).
- with no linked principal: "Please /login first to link your Telegram account."

Prompt failures are logged and never turn a successful reply into an error.

## Combined login (staged)

With `post_auth_actions` set, the primary login only produces a **pending
candidate**, never an active session. The bot then sends an
`Authorize <provider> to finish login.` button per action. The attempt:

- stays pending until **every required** provider completes (optional ones
  must complete or fail); only then is the identity link published, the
  session activated and `Authenticated as <name>. Connected: ...` sent;
- expires after 10 minutes (capped by the OAuth state expiry); a new `/login`
  supersedes it and `/logout` cancels it;
- on a required-step failure, cancellation or expiry publishes **no** identity
  link and activates nothing; on failure the bot replies
  `Login requires authorization for <providers>. Please try again with /login.`

Discarding a login attempt is not revocation: provider grants that already
completed stay owned by the principal even if a later required step fails.
Remove them with `/disconnect <provider>`.

## Legacy cutover runbook

Legacy channel-scoped tokens (`jira:oauth:telegram:*`, `oauth2:<provider>:telegram:*`
in Redis) are not migrated; unbound users must re-connect.

1. **Audit** (read-only, never reads values):
   `python -m parrot.auth.oauth2.legacy_audit [--provider jira --provider o365]`
   prints bound/unbound counts per provider and channel.
2. **Announce** to the unbound users that they must `/login` and `/connect`
   again (forced re-connect).
3. **Date**: set `OAUTH2_LEGACY_KEYS_UNTIL` (ISO-8601) and wait for it to pass.
4. **Purge**:
   ```bash
   python -m parrot.auth.oauth2.legacy_audit --purge --channel telegram            # dry run: counts only
   python -m parrot.auth.oauth2.legacy_audit --purge --channel telegram --confirm  # UNLINK keys
   ```
   `--purge` requires `--channel`; providers default to `jira` and `o365`.
   A real purge is refused (exit code 2) while `OAUTH2_LEGACY_KEYS_UNTIL` is
   missing, unparsable or not yet passed; `--force` bypasses the date gate.
   Channels containing `* ? [ ] :` are rejected.

The purge touches **Redis only**. Residual vault cleanup is a separate
operation subject to the same expiry gate; no command for it ships here.

# Connections on Microsoft Teams

## Overview

Microsoft Teams connections are keyed to the Navigator principal, not to a Teams display name or the Bot
Framework sender id. A live FEAT-729 `/login` session supplies the Navigator user id and the Microsoft Entra ID
object id (AAD oid). The Navigator id owns the connection and permissions; the AAD oid is the explicit Teams
channel identity used to find the credential.

FEAT-773 provides the principal-keyed, channel-neutral connection model and the `/api/v1/connections*` service
routes. FEAT-775 makes that model available in Teams through generic commands, Adaptive Cards and a Teams
connection notifier. Teams does not provide third-party-provider SSO: each provider still uses its configured
OAuth or device-code flow.

## Commands

Use these commands in a personal (1:1) Teams conversation:

```text
/connect [<provider>]
/disconnect <provider>
/connections [<provider>]
```

`/connect` without a provider displays a provider picker. `/connect <provider>` reports an existing sufficient
grant or opens the provider's authorization flow. `/disconnect <provider>` revokes the provider connection.
`/connections` displays all permitted providers; adding a provider displays only that provider's status.
Status cards contain **Connect** or **Disconnect** buttons, and the provider picker uses card **Action.Submit**
buttons that invoke the same handlers as typed commands.

The Jira commands remain compatibility aliases:

```text
/connect_jira       # equivalent to /connect jira
/disconnect_jira    # equivalent to /disconnect jira
/jira_status        # equivalent to /connections jira
jira                # equivalent to /connections
integrations        # equivalent to /connections
```

The generic `/connections` command is the replacement for the old Jira-only menu. Unknown providers produce
`Unknown provider '<provider_id>'. Try \`/connect\` to see the list.`; `/disconnect` without a provider produces
`Usage: \`/disconnect <provider>\``.

## Prerequisites

Users must complete `/login` through the live FEAT-729 Teams authentication session before using connections.
The session must be authenticated, unexpired, have a Navigator user id and have an AAD oid. An existing
`auth.user_identities` row alone is not sufficient: Teams connection commands require the live session and its
AAD identity. An unauthenticated or incomplete session receives:

> Please `/login` first, then try again.

The bot must have `navigator_auth_url` configured so that the `/login` command and the session exchange are
available. When the auth lane is disabled, the operator-facing response is:

> Connections need Navigator sign-in; ask an operator to enable it

If `auth_required=True`, startup fails instead of silently serving unauthenticated users when
`navigator_auth_url` is missing.

## Personal-only rule

Connections and consent are personal. They are not available in group chats or channel conversations, because a
conversation reference or an account result could otherwise be exposed to everyone in that conversation. In a
non-personal conversation, the bot makes no connection service call and replies:

> Connections are personal — message me directly (1:1 chat) to manage them.

The conversation-reference store likewise retains only the latest personal reference for each Navigator user.

## Automatic Connect cards

When a tool reports that authorization is required during a Teams turn, the wrapper first sends the agent's
response, then offers one connection card per provider that needs consent. The card is created through
`IntegrationsService.start_connect(channel="msteams")`; its signed state carries the serialized conversation
reference and the owning bot app id. The tool-produced authorization URL is not reused because it does not carry
that Teams routing state.

For browser-based OAuth, the card says:

> Click the button below to authorize your **<Provider>** account:

and provides a `Connect <Provider>` **Action.OpenUrl** button. For a device-code provider, it instead displays the
user code, the verification URI and, when available, the expiration in seconds, with an **Open verification page**
button. The code and URI come from the same complete device challenge; conflicting challenges are rejected with a
safe retry response.

Automatic offers are personal-only and require the same live principal as explicit commands. They expose no URL,
code or service call in a group/channel conversation or without a valid `/login` session. Requested scopes are
unioned and sorted per provider. An active connection skips consent only when its granted scopes cover the request;
an active grant missing scopes enters consent for the upgrade. Connecting does not automatically re-run the failed
tool: after the completion message, ask the bot again.

## Notifications & multi-bot routing

Each aiohttp app has one `MSTeamsConnectionNotifier` for `channel="msteams"`. It keeps a map of Microsoft app id
to Bot Framework adapter, so multiple Teams bots in one app route proactive messages through the adapter that owns
the conversation. The notifier handles all three lifecycle events:

| Event | Teams message |
| --- | --- |
| `connection.completed` | `<Provider> connected as **<display_name>**. Ask again to use it.` |
| `connection.revoked` | `<Provider> disconnected.` |
| `connection.refresh_failed` | `<Provider> access expired — \`/connect <id>\` to reconnect.` |

For a callback, routing uses the conversation reference and bot app id in the signed state. For revoke and refresh
events without OAuth state, it loads the latest personal reference for the event user from Redis. References use
the `msteams:convref:{nav_user_id}` key and a 30-day TTL, refreshed on each authenticated personal turn. Missing
references, unknown app ids and adapter failures are logged and do not fail the callback or refresh operation.

## Permissions

Teams uses the same request-less authorizer as Slack and the CLI: `NavigatorConnectionAuthorizer`
(`app["connection_authorizer"]`, see [Connections — PBAC without a request](../auth/connections.md#pbac-without-a-request)).
One set of `integration` resource policies therefore covers every non-web channel. Policies are evaluated with the
Teams principal as the subject, and the resource is the provider id (`*` for the collection gate):

| Service operation | Resource (`integration`) | Action |
|---|---|---|
| `list_for_principal` (gate) | `*` | `integration:list` |
| `list_for_principal` (per-provider filter) | `{provider}` | `integration:list` |
| `status` | `{provider}` | `integration:list` |
| `start_connect` | `{provider}` | `integration:connect` |
| `disconnect` | `{provider}` | `integration:disconnect` |

Only an explicit `ALLOW` grants access. Listing denials return an empty result; denied status, connect and
disconnect operations are rendered as a plain not-allowed response. A missing authorizer or PDP, an authorizer
failure, an inactive Navigator user, or an exclusive Teams binding that no longer resolves to the same Navigator
user all deny closed.

The Teams `PermissionContext` is used only as an identity check, before the authorizer runs: the target user, the
principal, the tenant and the AAD object id (`channel_user_id`) must all match, otherwise the operation is denied
without consulting policy.

### Roles and groups

The authorizer loads the user's role, groups and tenant (`org_id`/`client_id`) from the Navigator auth database, not
from the Teams sign-in. Policies can grant Teams users access by role or group (for example a `connections-users`
group), exactly as for Slack.

## Operator checklist

- Register every provider's OAuth redirect URI with that provider before enabling its Teams connection flow.
- Configure `navigator_auth_url` for every Teams bot that exposes connections.
- Configure the Microsoft app `client_id` for each bot. It identifies the adapter used for proactive routing.
- Add PBAC policies for the `integration` resource and the `integration:*` actions in the permissions table (the same policies Slack and the CLI use; roles and groups apply).
- Ensure Redis is available for the 30-day personal conversation-reference store.
- Register providers in `OAuth2ProviderRegistry`; Teams exposes every registered provider, not only Jira.
- Keep provider client credentials and redirect URIs in deployment configuration, never in messages or source.

## Migration note

Users of `/connect_jira` do not need to reconnect immediately. Existing channel-scoped grants remain readable and
can be migrated to the principal-keyed connection while `OAUTH2_LEGACY_KEYS_UNTIL` is open. After that window
closes, the legacy keys are no longer read; reconnect with:

```text
/connect jira
```

The `/connect_jira`, `/disconnect_jira` and `/jira_status` aliases remain available for compatibility, but new
connection flows should use the generic commands. Group/channel connect and Teams SSO for third-party providers are
not supported.

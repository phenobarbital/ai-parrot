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

## Needs-auth contract

Tools and handlers use `AuthRequiredPayload` for both authorization-required
and credential-required outcomes. The payload carries the provider, channel,
principal-safe connection details and any device-code fields needed by the
client; token values are never included.

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

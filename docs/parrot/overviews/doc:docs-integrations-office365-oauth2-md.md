---
type: Wiki Overview
title: Office 365 OAuth 2.0 (Delegated) — AI-Parrot Integration
id: doc:docs-integrations-office365-oauth2-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This guide documents the Microsoft Graph delegated permissions required by
relates_to:
- concept: mod:parrot.auth.o365_oauth
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
---

# Office 365 OAuth 2.0 (Delegated) — AI-Parrot Integration

This guide documents the Microsoft Graph delegated permissions required by
the `Office365Toolkit` shipped with AI-Parrot, the Azure AD app
registration steps, and the env-var wiring.

The toolkit uses the generic
[`AbstractOAuth2Manager`](../../packages/ai-parrot/src/parrot/auth/oauth2_base.py)
infrastructure with PKCE + client_secret (confidential client). Tokens
are persisted in the navigator-session encrypted vault and hot-cached in
Redis with a 90-day TTL.

## Architecture summary

```
Frontend popup ─── POST /api/v1/agents/integrations/operator/o365/connect
   │                              │
   │                              ▼
   │              IntegrationsService.start_connect()
   │                              │
   │                              ▼
   │          O365OAuthManager.create_authorization_url()
   │              (PKCE code_verifier + nonce stored in Redis, 10-min TTL)
   │                              │
   ▼                              ▼
opens auth_url ──→  https://login.microsoftonline.com/.../authorize
   │                              │
   │   user consents              ▼
   └──────────► GET /api/auth/oauth2/o365/callback?code=...&state=...
                                 │
                                 ▼
              O365OAuthManager.handle_callback()
              ├─ POST /oauth2/v2.0/token  (PKCE)
              ├─ GET  /v1.0/me            (identity discovery)
              ├─ vault.store(user_id, "oauth2_o365_web_{user_id}", token)
              └─ redis.set("oauth2:o365:web:{user_id}", token, ex=90d)
```

## Required delegated scopes

| Scope                    | Grants                                        | Used by                                                    |
|--------------------------|-----------------------------------------------|------------------------------------------------------------|
| `openid` `profile`       | OIDC sign-in + identity discovery             | `_discover_identity()` (every flow)                        |
| `offline_access`         | Returns a `refresh_token`                     | Long-lived sessions, transparent refresh                   |
| `User.Read`              | Read the signed-in user's profile             | `_discover_identity()` (every flow)                        |
| `Mail.Read`              | Read the user's mail                          | `read_inbox`, `search_messages`                            |
| `Mail.Send`              | Send mail as the user                         | `send_email`                                               |
| `Files.Read`             | Read the user's OneDrive files                | `list_onedrive_files`                                      |
| `Files.ReadWrite`        | Create/modify files in the user's OneDrive    | Future `upload_to_onedrive` (not in MVP)                   |
| `Sites.Read.All`         | Read SharePoint sites the user can see        | `list_sharepoint_sites`                                    |
| `Calendars.Read`         | Read the user's calendars                     | `list_upcoming_events`                                     |

Optional scopes for future tools (do not add unless the tool needs them —
keep the consent screen minimal):

| Scope                     | Purpose                                       |
|---------------------------|-----------------------------------------------|
| `Mail.ReadWrite`          | Mark messages read, move between folders      |
| `Mail.Send.Shared`        | Send mail from a shared mailbox the user owns |
| `Sites.ReadWrite.All`     | Write to SharePoint document libraries        |
| `Calendars.ReadWrite`     | Create / update calendar events               |

## Azure AD app registration

1. Sign in to the [Azure portal](https://portal.azure.com) → **App registrations** → **New registration**.
2. **Name**: e.g. `AI-Parrot Operator (delegated)`.
3. **Supported account types**:
   - For internal-only tenants: *Accounts in this organizational directory only* (`O365_TENANT_ID` = tenant GUID).
   - For multi-tenant SaaS: *Accounts in any organizational directory* (`O365_TENANT_ID` = `organizations`).
   - For personal Microsoft accounts too: *Accounts in any organizational directory and personal Microsoft accounts* (`O365_TENANT_ID` = `common`).
4. **Redirect URI**:
   - Platform: **Web**.
   - URL: `https://<your-host>/api/auth/oauth2/o365/callback`
     (for local dev: `http://localhost:5000/api/auth/oauth2/o365/callback`).
5. After the app is created, copy:
   - **Application (client) ID** → env var `O365_CLIENT_ID`.
   - **Directory (tenant) ID** → env var `O365_TENANT_ID` (or `common` / `organizations`).
6. **Certificates & secrets** → **New client secret** → copy the *Value*
   (visible only once) → env var `O365_CLIENT_SECRET`.
7. **API permissions** → **Add a permission** → **Microsoft Graph** →
   **Delegated permissions** → tick every row from the "Required delegated
   scopes" table above → **Add permissions**.
8. If your tenant requires admin consent (most enterprise tenants do),
   click **Grant admin consent for <tenant>**. End users will otherwise
   still be prompted on first sign-in.

## Environment variables

Configured in `parrot/conf.py`:

```
O365_CLIENT_ID=<application-client-id>
O365_CLIENT_SECRET=<client-secret-value>
O365_TENANT_ID=common                       # or "organizations" / tenant GUID
O365_REDIRECT_URI=https://host/api/auth/oauth2/o365/callback
OAUTH2_REDIS_URL=redis://localhost:6379/4
WEB_OAUTH_ALLOWED_ORIGINS=https://app.example.com,http://localhost:3000
```

The vault encryption uses navigator-session's master keys — make sure
`NAV_SESSION_VAULT_KEYS` is also configured (see `navigator_session`
docs).

## Bootstrapping the manager

In your application startup (e.g. `app.py`):

```python
from parrot.auth.o365_oauth import O365OAuthManager
from parrot.integrations.oauth2.o365_provider import O365OAuth2Provider
from parrot.integrations.oauth2.registry import register_oauth2_provider
from parrot.conf import (
    O365_CLIENT_ID, O365_CLIENT_SECRET, O365_TENANT_ID,
    O365_REDIRECT_URI, OAUTH2_REDIS_URL,
)


async def on_startup(app):
    manager = O365OAuthManager(
        client_id=O365_CLIENT_ID,
        client_secret=O365_CLIENT_SECRET,
        redirect_uri=O365_REDIRECT_URI,
        tenant_id=O365_TENANT_ID,
        app=app,
        redis_url=OAUTH2_REDIS_URL,
    )
    manager.setup()  # mounts /api/auth/oauth2/o365/callback
    register_oauth2_provider(O365OAuth2Provider(manager=manager))
```

After this, any agent whose `configure()` builds an
`Office365Toolkit(OAuthCredentialResolver(manager))` automatically
resolves per-user tokens at tool-call time.

## Token lifecycle

| Layer       | Backing store                        | TTL              | Source of truth |
|-------------|--------------------------------------|------------------|-----------------|
| Hot cache   | Redis `oauth2:o365:{channel}:{uid}`  | 90 days (sliding)| no              |
| Persisted   | DocumentDB `user_credentials`        | none (until delete) | **yes**       |
| Refresh lock| Redis `lock:oauth2:o365:refresh:...` | 10 s             | no              |
| Nonce + PKCE| Redis `oauth2:o365:nonce:<state>`    | 10 minutes       | one-shot        |

On `get_valid_token(channel, user_id)`:

1. Read Redis cache. If present and unexpired → return.
2. Fall back to the vault. On hit, refill the Redis cache and return.
3. If the token is expired and has a `refresh_token`, acquire the
   `lock:oauth2:o365:refresh:...` Redis lock and POST `grant_type=refresh_token`
   to the token endpoint. On success, write the new token back to both
   layers and return; on 400/401 from Microsoft, revoke both layers and
   return `None` (user must re-authorize).

## Revocation

Users can revoke consent from
<https://myapps.microsoft.com/> → *Manage your applications* → revoke.
The next `get_valid_token` call will get HTTP 400/401 on refresh and the
manager will purge both vault and Redis. The toolkit then raises
`AuthorizationRequired` on the next tool call, surfacing a fresh
auth URL to the user.

To force a logout from the server side:

```python
await manager.revoke("web", user_id)
```

## Troubleshooting

| Symptom                                            | Likely cause                                                                            |
|----------------------------------------------------|-----------------------------------------------------------------------------------------|
| `Origin '...' is not in the list of allowed origins` | `return_origin` missing from `WEB_OAUTH_ALLOWED_ORIGINS`.                              |
| Browser shows `AADSTS65001`                        | Tenant requires admin consent and it has not been granted for one of the scopes.        |
| `O365 token exchange failed with status 400`       | `redirect_uri` mismatch — must match the Azure registration exactly (scheme + host + path). |
| Toolkit raises `AuthorizationRequired` immediately | Token missing from vault AND Redis — user must run the connect flow.                    |
| Refresh fails repeatedly with 400                  | User changed their tenant password or admin revoked the app — vault is purged automatically. |

## See also

- Generic base: [`parrot/auth/oauth2_base.py`](../../packages/ai-parrot/src/parrot/auth/oauth2_base.py)
- O365 manager: [`parrot/auth/o365_oauth.py`](../../packages/ai-parrot/src/parrot/auth/o365_oauth.py)
- Toolkit: [`parrot_tools/o365/oauth_toolkit.py`](../../packages/ai-parrot-tools/src/parrot_tools/o365/oauth_toolkit.py)
- Provider registration: [`parrot/integrations/oauth2/o365_provider.py`](../../packages/ai-parrot/src/parrot/integrations/oauth2/o365_provider.py)
- Reference agent: [`agents/operator.py`](../../agents/operator.py)
- Demo script: [`examples/agents/oauth/demo_operator.py`](../../examples/agents/oauth/demo_operator.py)

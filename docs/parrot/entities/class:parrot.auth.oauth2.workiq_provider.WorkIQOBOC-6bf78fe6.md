---
type: Wiki Entity
title: WorkIQOBOCredentialResolver
id: class:parrot.auth.oauth2.workiq_provider.WorkIQOBOCredentialResolver
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Credential resolver that exchanges an Entra assertion for a Work IQ OBO token.
relates_to:
- concept: class:parrot.auth.credentials.CredentialResolver
  rel: extends
---

# WorkIQOBOCredentialResolver

Defined in [`parrot.auth.oauth2.workiq_provider`](../summaries/mod:parrot.auth.oauth2.workiq_provider.md).

```python
class WorkIQOBOCredentialResolver(CredentialResolver)
```

Credential resolver that exchanges an Entra assertion for a Work IQ OBO token.

Implements the :class:`~parrot.auth.credentials.CredentialResolver` contract
so the A2A bridge (FEAT-263 / TASK-1644) can gate any tool declaring
``credential_provider = "workiq"`` through this OBO flow.

Resolution steps:

1. Check vault for a cached ``workiq:access_token`` for *user_id*.
2. If absent, look for the user's Entra token (``o365:access_token`` in vault).
3. If the Entra token exists, call
   :meth:`O365Client.acquire_token_on_behalf_of` with the Work IQ scope,
   cache the result as ``workiq:access_token``, and return the token.
4. If neither is available, return ``None`` — the bridge will surface the
   Entra sign-in link from :meth:`get_auth_url`.

Args:
    o365_interface: A configured
        :class:`~parrot.interfaces.o365.O365Client` instance used for
        the OBO token exchange.
    o365_oauth_manager: The application-level O365 OAuth manager (must
        expose ``create_authorization_url(channel, user_id)``).
    vault_token_sync: A configured
        :class:`~parrot.services.vault_token_sync.VaultTokenSync` instance
        used for reading and writing per-user tokens.
    workiq_scope: The delegated OBO scope (default:
        ``api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask``).

## Methods

- `async def resolve(self, channel: str, user_id: str) -> Optional[str]` — Return the per-user Work IQ OBO access token, or ``None``.
- `async def get_auth_url(self, channel: str, user_id: str) -> str` — Return the Entra sign-in URL for the O365 delegated flow.

---
type: Wiki Entity
title: O365OAuthManager
id: class:parrot.auth.o365_oauth.O365OAuthManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Microsoft Identity Platform OAuth 2.0 (PKCE + client_secret).
relates_to:
- concept: class:parrot.auth.oauth2_base.AbstractOAuth2Manager
  rel: extends
---

# O365OAuthManager

Defined in [`parrot.auth.o365_oauth`](../summaries/mod:parrot.auth.o365_oauth.md).

```python
class O365OAuthManager(AbstractOAuth2Manager)
```

Microsoft Identity Platform OAuth 2.0 (PKCE + client_secret).

The authorization and token endpoints embed the tenant ID; pass
``"common"`` to support both personal and work accounts in one app
registration. ``handle_callback`` resolves user identity via
``GET https://graph.microsoft.com/v1.0/me`` and stores the result on
:class:`O365TokenSet`.

## Methods

- `def authorization_url_extra_params(self) -> Dict[str, str]` — Force consent prompt and request the account selection screen.
- `async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]` — Public, stateless Entra refresh: exchange a refresh_token for a new token dict.

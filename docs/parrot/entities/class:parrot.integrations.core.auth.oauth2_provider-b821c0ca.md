---
type: Wiki Entity
title: OAuth2ProviderConfig
id: class:parrot.integrations.core.auth.oauth2_providers.OAuth2ProviderConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for a specific OAuth2 identity provider.
---

# OAuth2ProviderConfig

Defined in [`parrot.integrations.core.auth.oauth2_providers`](../summaries/mod:parrot.integrations.core.auth.oauth2_providers.md).

```python
class OAuth2ProviderConfig
```

Configuration for a specific OAuth2 identity provider.

Attributes:
    name: Provider identifier (e.g. "google", "github").
    authorization_url: URL to redirect the user for authentication.
    token_url: URL to exchange an authorization code for tokens.
    userinfo_url: URL to fetch the authenticated user's profile.
    default_scopes: Default OAuth2 scopes requested if none are
        specified in the bot configuration.

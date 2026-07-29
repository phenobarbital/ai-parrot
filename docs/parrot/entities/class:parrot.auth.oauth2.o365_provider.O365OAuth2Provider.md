---
type: Wiki Entity
title: O365OAuth2Provider
id: class:parrot.auth.oauth2.o365_provider.O365OAuth2Provider
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: OAuth2 provider for Microsoft Office 365 (delegated / 3LO).
relates_to:
- concept: class:parrot.auth.oauth2.registry.OAuth2Provider
  rel: extends
---

# O365OAuth2Provider

Defined in [`parrot.auth.oauth2.o365_provider`](../summaries/mod:parrot.auth.oauth2.o365_provider.md).

```python
class O365OAuth2Provider(OAuth2Provider)
```

OAuth2 provider for Microsoft Office 365 (delegated / 3LO).

Attributes:
    provider_id: Always ``"o365"``.
    display_name: ``"Office 365"``.
    icon: Material Design Icon key ``"mdi:microsoft-office"``.
    default_scopes: Microsoft Graph delegated scopes — mirror
        :data:`parrot.auth.o365_oauth.DEFAULT_O365_SCOPES`.

## Methods

- `def manager(self) -> 'O365OAuthManager'`
- `def toolkit_factory(self, credential_resolver: 'CredentialResolver') -> 'Office365Toolkit'`

---
type: Wiki Entity
title: OAuthCredentialResolver
id: class:parrot.auth.credentials.OAuthCredentialResolver
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Resolves credentials from an OAuth 2.0 token store.
relates_to:
- concept: class:parrot.auth.credentials.CredentialResolver
  rel: extends
---

# OAuthCredentialResolver

Defined in [`parrot.auth.credentials`](../summaries/mod:parrot.auth.credentials.md).

```python
class OAuthCredentialResolver(CredentialResolver)
```

Resolves credentials from an OAuth 2.0 token store.

The resolver delegates all lookups to a manager that implements
``get_valid_token(channel, user_id)`` and
``create_authorization_url(channel, user_id)``.  The reference
implementation is :class:`JiraOAuthManager`, but any compatible object
(e.g., a future GitHub or O365 manager) can be plugged in.

## Methods

- `async def resolve(self, channel: str, user_id: str) -> Optional[Any]`
- `async def get_auth_url(self, channel: str, user_id: str) -> str`

---
type: Wiki Entity
title: StaticCredentialResolver
id: class:parrot.auth.credentials.StaticCredentialResolver
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Returns a fixed :class:`StaticCredentials` instance.
relates_to:
- concept: class:parrot.auth.credentials.CredentialResolver
  rel: extends
---

# StaticCredentialResolver

Defined in [`parrot.auth.credentials`](../summaries/mod:parrot.auth.credentials.md).

```python
class StaticCredentialResolver(CredentialResolver)
```

Returns a fixed :class:`StaticCredentials` instance.

Used for ``basic_auth`` / ``token_auth`` modes where a single
service-account credential is shared across all users.  The resolver
ignores ``channel`` and ``user_id``.

## Methods

- `async def resolve(self, channel: str, user_id: str) -> StaticCredentials`
- `async def get_auth_url(self, channel: str, user_id: str) -> str`

---
type: Wiki Entity
title: CredentialResolver
id: class:parrot.auth.credentials.CredentialResolver
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Resolves credentials for a given channel/user pair.
---

# CredentialResolver

Defined in [`parrot.auth.credentials`](../summaries/mod:parrot.auth.credentials.md).

```python
class CredentialResolver(ABC)
```

Resolves credentials for a given channel/user pair.

## Methods

- `async def resolve(self, channel: str, user_id: str) -> Optional[Any]` — Return credentials for ``(channel, user_id)`` or ``None``.
- `async def get_auth_url(self, channel: str, user_id: str) -> str` — Return the authorization URL the user should follow.
- `async def is_connected(self, channel: str, user_id: str) -> bool` — Return True when :meth:`resolve` currently yields credentials.

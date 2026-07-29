---
type: Wiki Entity
title: NavigatorAuthClient
id: class:parrot.integrations.telegram.auth.NavigatorAuthClient
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Authenticate Telegram users against Navigator API.
---

# NavigatorAuthClient

Defined in [`parrot.integrations.telegram.auth`](../summaries/mod:parrot.integrations.telegram.auth.md).

```python
class NavigatorAuthClient
```

Authenticate Telegram users against Navigator API.

SSL verification is enabled by default.  Set the ``NAVIGATOR_SSL_VERIFY``
environment variable to ``false`` (or ``0`` / ``no``) to disable
verification in environments that use self-signed certificates.  Disabling
verification in production is a security risk — prefer installing the CA
certificate instead.

## Methods

- `async def login(self, username: str, password: str) -> Optional[Dict]` — Authenticate against Navigator API.
- `async def validate_token(self, token: str) -> bool` — Validate an existing session token (optional future use).

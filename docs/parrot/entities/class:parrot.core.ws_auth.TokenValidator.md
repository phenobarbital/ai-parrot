---
type: Wiki Entity
title: TokenValidator
id: class:parrot.core.ws_auth.TokenValidator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: JWT Token validator.
---

# TokenValidator

Defined in [`parrot.core.ws_auth`](../summaries/mod:parrot.core.ws_auth.md).

```python
class TokenValidator
```

JWT Token validator.

Supports multiple validation backends:
- navigator_auth (production)
- Custom validator function
- Fallback for testing

## Methods

- `async def validate(self, token: str) -> Optional[AuthenticatedUser]` — Validate JWT token and return user info.

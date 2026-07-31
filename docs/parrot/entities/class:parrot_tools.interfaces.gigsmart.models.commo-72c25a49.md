---
type: Wiki Entity
title: OAuthToken
id: class:parrot_tools.interfaces.gigsmart.models.common.OAuthToken
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parsed OAuth 2.1 token response from the GigSmart token endpoint.
---

# OAuthToken

Defined in [`parrot_tools.interfaces.gigsmart.models.common`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.common.md).

```python
class OAuthToken(BaseModel)
```

Parsed OAuth 2.1 token response from the GigSmart token endpoint.

Args:
    access_token: The Bearer token string.
    token_type: Always ``"bearer"`` for GigSmart.
    expires_in: Token lifetime in seconds.
    refresh_token: Present only for auth_code grant responses.
    scope: Space-separated list of granted scopes.
    expires_at: Computed absolute UTC expiry time (``now + expires_in``).

## Methods

- `def is_expired(self) -> bool` — Return True if the token has passed its expiry time.
- `def needs_refresh(self, threshold_seconds: int=120) -> bool` — Return True if the token expires within *threshold_seconds*.

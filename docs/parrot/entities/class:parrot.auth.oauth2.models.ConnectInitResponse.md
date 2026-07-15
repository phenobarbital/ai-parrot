---
type: Wiki Entity
title: ConnectInitResponse
id: class:parrot.auth.oauth2.models.ConnectInitResponse
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Response for the connect-init endpoint.
---

# ConnectInitResponse

Defined in [`parrot.auth.oauth2.models`](../summaries/mod:parrot.auth.oauth2.models.md).

```python
class ConnectInitResponse(BaseModel)
```

Response for the connect-init endpoint.

Attributes:
    auth_url: Full Atlassian authorization URL to open in a popup.
    state: Opaque CSRF nonce; the client must not interpret it.
    scopes: Scopes included in the authorization request.
    expires_in: Seconds the nonce remains valid (default 600).

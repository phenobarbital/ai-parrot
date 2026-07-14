---
type: Wiki Entity
title: CredentialResponse
id: class:parrot.handlers.models.credentials.CredentialResponse
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Response model for a single credential returned by the API.
---

# CredentialResponse

Defined in [`parrot.handlers.models.credentials`](../summaries/mod:parrot.handlers.models.credentials.md).

```python
class CredentialResponse(BaseModel)
```

Response model for a single credential returned by the API.

Sensitive parameters are returned as-is (decrypted) only to the
authenticated owner of the credential.

Attributes:
    name: Credential name.
    driver: asyncdb driver identifier.
    params: Decrypted connection parameters.

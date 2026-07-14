---
type: Wiki Entity
title: CredentialPayload
id: class:parrot.handlers.models.credentials.CredentialPayload
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input model for creating/updating a user database credential.
---

# CredentialPayload

Defined in [`parrot.handlers.models.credentials`](../summaries/mod:parrot.handlers.models.credentials.md).

```python
class CredentialPayload(BaseModel)
```

Input model for creating/updating a user database credential.

Validates the structure of a credential payload submitted via POST or PUT.
Credential names are unique per user (not globally).

Attributes:
    name: Unique credential name within the user's scope (1-128 chars).
    driver: asyncdb driver identifier (e.g., 'pg', 'mysql', 'bigquery').
    params: Connection parameters dict (host, port, user, password, database, etc.).

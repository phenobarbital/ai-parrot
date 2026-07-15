---
type: Wiki Entity
title: CredentialsHandler
id: class:parrot.handlers.credentials.CredentialsHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: CRUD handler for user database credentials.
---

# CredentialsHandler

Defined in [`parrot.handlers.credentials`](../summaries/mod:parrot.handlers.credentials.md).

```python
class CredentialsHandler(BaseView)
```

CRUD handler for user database credentials.

Provides endpoints to create, read, update, and delete asyncdb-syntax
database credentials.  Each user maintains their own isolated credential
namespace identified by ``name``.

Class Attributes:
    COLLECTION: DocumentDB collection name for credential storage.
    SESSION_PREFIX: Key prefix used in the session vault.

## Methods

- `async def get(self) -> web.Response` — Retrieve credentials for the authenticated user.
- `async def post(self) -> web.Response` — Create a new credential for the authenticated user.
- `async def put(self) -> web.Response` — Update an existing credential for the authenticated user.
- `async def delete(self) -> web.Response` — Delete a credential for the authenticated user.

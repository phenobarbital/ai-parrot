---
type: Wiki Summary
title: parrot.handlers.credentials
id: mod:parrot.handlers.credentials
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: CredentialsHandler — CRUD HTTP view for user database credentials.
relates_to:
- concept: class:parrot.handlers.credentials.CredentialsHandler
  rel: defines
- concept: func:parrot.handlers.credentials.setup_credentials_routes
  rel: defines
- concept: mod:parrot.handlers.credentials_utils
  rel: references
- concept: mod:parrot.handlers.models.credentials
  rel: references
- concept: mod:parrot.interfaces.documentdb
  rel: references
---

# `parrot.handlers.credentials`

CredentialsHandler — CRUD HTTP view for user database credentials.

Implements GET, POST, PUT, and DELETE operations for per-user database
credential management.  Credentials are:

* Validated with :class:`parrot.handlers.models.credentials.CredentialPayload`
* Saved immediately to the user session vault (Redis-backed)
* Persisted to DocumentDB asynchronously via fire-and-forget
* Encrypted at rest using :mod:`parrot.handlers.credentials_utils`

Routes (registered by :func:`setup_credentials_routes`):
    ``GET    /api/v1/users/credentials``          — list all credentials
    ``POST   /api/v1/users/credentials``          — create a credential
    ``GET    /api/v1/users/credentials/{name}``   — get single credential
    ``PUT    /api/v1/users/credentials/{name}``   — update credential
    ``DELETE /api/v1/users/credentials/{name}``   — delete credential

## Classes

- **`CredentialsHandler(BaseView)`** — CRUD handler for user database credentials.

## Functions

- `def setup_credentials_routes(app: web.Application) -> None` — Register credential management routes on the aiohttp application.

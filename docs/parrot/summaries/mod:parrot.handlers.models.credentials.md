---
type: Wiki Summary
title: parrot.handlers.models.credentials
id: mod:parrot.handlers.models.credentials
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Credential Pydantic data models.
relates_to:
- concept: class:parrot.handlers.models.credentials.CredentialDocument
  rel: defines
- concept: class:parrot.handlers.models.credentials.CredentialPayload
  rel: defines
- concept: class:parrot.handlers.models.credentials.CredentialResponse
  rel: defines
---

# `parrot.handlers.models.credentials`

Credential Pydantic data models.

This module defines the data models used for:
- Validating incoming credential payloads (POST/PUT requests)
- Representing DocumentDB storage documents
- Serializing API responses

## Classes

- **`CredentialPayload(BaseModel)`** — Input model for creating/updating a user database credential.
- **`CredentialDocument(BaseModel)`** — DocumentDB storage model for a user credential.
- **`CredentialResponse(BaseModel)`** — Response model for a single credential returned by the API.

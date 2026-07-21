---
type: Wiki Entity
title: CredentialDocument
id: class:parrot.handlers.models.credentials.CredentialDocument
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: DocumentDB storage model for a user credential.
---

# CredentialDocument

Defined in [`parrot.handlers.models.credentials`](../summaries/mod:parrot.handlers.models.credentials.md).

```python
class CredentialDocument(BaseModel)
```

DocumentDB storage model for a user credential.

The ``credential`` field stores an encrypted JSON string produced by
:func:`parrot.handlers.credentials_utils.encrypt_credential`.

Attributes:
    user_id: Identifier of the owning user.
    name: Credential name (unique per user).
    credential: Encrypted JSON string of ``driver`` + ``params``.
    created_at: Timestamp when the credential was first created.
    updated_at: Timestamp of the most recent update.

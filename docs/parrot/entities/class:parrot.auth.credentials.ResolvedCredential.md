---
type: Wiki Entity
title: ResolvedCredential
id: class:parrot.auth.credentials.ResolvedCredential
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Credential material returned by the broker on a successful resolution.
---

# ResolvedCredential

Defined in [`parrot.auth.credentials`](../summaries/mod:parrot.auth.credentials.md).

```python
class ResolvedCredential(BaseModel)
```

Credential material returned by the broker on a successful resolution.

Attributes:
    provider: Provider identifier.
    secret: Raw credential (token, API key, …).  **NEVER** log this field;
        only :attr:`key_fingerprint` should appear in audit records.
    key_fingerprint: SHA-256 hex digest of ``secret`` (for audit).

---
type: Wiki Entity
title: LocalHMACSigner
id: class:parrot.security.audit_ledger.LocalHMACSigner
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: HMAC-SHA256 signer for local development and testing.
relates_to:
- concept: class:parrot.security.audit_ledger.AbstractKMSSigner
  rel: extends
---

# LocalHMACSigner

Defined in [`parrot.security.audit_ledger`](../summaries/mod:parrot.security.audit_ledger.md).

```python
class LocalHMACSigner(AbstractKMSSigner)
```

HMAC-SHA256 signer for local development and testing.

This signer uses Python's built-in :mod:`hmac` module with a caller-supplied
secret key.  It is cryptographically sound for low-threat environments but
does **not** provide the tamper-evidence guarantees of a true managed KMS
(key rotation, HSM backing, audit trail of key usage, etc.).

Args:
    secret: The HMAC secret.  Defaults to a random 32-byte secret if not
        provided (suitable for unit tests where verification happens in the
        same process).  In production use, supply a secret from the vault.

## Methods

- `async def sign(self, data: bytes) -> str` — Return the HMAC-SHA256 hex digest of *data* under the secret key.
- `async def verify(self, data: bytes, signature: str) -> bool` — Return ``True`` iff *signature* matches the HMAC-SHA256 of *data*.

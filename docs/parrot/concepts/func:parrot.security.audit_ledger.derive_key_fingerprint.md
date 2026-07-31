---
type: Concept
title: derive_key_fingerprint()
id: func:parrot.security.audit_ledger.derive_key_fingerprint
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the SHA-256 hex digest of ``credential_material``.
---

# derive_key_fingerprint

```python
def derive_key_fingerprint(credential_material: Any) -> str
```

Return the SHA-256 hex digest of ``credential_material``.

The fingerprint uniquely identifies a credential without exposing any
secret bytes.

Args:
    credential_material: Any credential value — token string, dict with
        ``access_token`` / ``token``, or arbitrary bytes.  Dicts and other
        objects are serialised to JSON before hashing.

Returns:
    A 64-character lowercase hex string (SHA-256).

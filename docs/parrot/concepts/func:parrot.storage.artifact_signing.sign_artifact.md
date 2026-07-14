---
type: Concept
title: sign_artifact()
id: func:parrot.storage.artifact_signing.sign_artifact
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Compute the base64url HMAC digest over ``'{artifact_id}|{expiry}'``.
---

# sign_artifact

```python
def sign_artifact(artifact_id: str, expiry: int, key: bytes) -> str
```

Compute the base64url HMAC digest over ``'{artifact_id}|{expiry}'``.

Args:
    artifact_id: Artifact identifier being signed.
    expiry: Absolute UNIX expiry timestamp (seconds).
    key: HMAC secret key.

Returns:
    base64url-encoded digest without ``=`` padding.

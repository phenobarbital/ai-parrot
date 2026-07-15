---
type: Concept
title: verify_signature()
id: func:parrot.storage.artifact_signing.verify_signature
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Verify a ``{expiry}.{sig}`` signature segment.
---

# verify_signature

```python
def verify_signature(artifact_id: str, signature_segment: str, key: bytes) -> bool
```

Verify a ``{expiry}.{sig}`` signature segment.

Args:
    artifact_id: Artifact identifier the signature should authorise.
    signature_segment: The ``{expiry}.{hmac}`` path segment.
    key: HMAC secret key.

Returns:
    True when the signature is valid AND the expiry is in the future.

---
type: Concept
title: get_signing_key()
id: func:parrot.storage.artifact_signing.get_signing_key
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Read ``INFOGRAPHIC_SIGNING_KEY`` from the environment.
---

# get_signing_key

```python
def get_signing_key() -> bytes
```

Read ``INFOGRAPHIC_SIGNING_KEY`` from the environment.

Returns:
    The configured key as bytes, or a deterministic insecure fallback
    when the variable is unset (development only).

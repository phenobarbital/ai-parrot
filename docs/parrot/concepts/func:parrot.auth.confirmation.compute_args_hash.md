---
type: Concept
title: compute_args_hash()
id: func:parrot.auth.confirmation.compute_args_hash
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Produce a stable SHA-256 hash over normalized parameters.
---

# compute_args_hash

```python
def compute_args_hash(parameters: dict) -> str
```

Produce a stable SHA-256 hash over normalized parameters.

The hash is deterministic across runs: keys are sorted and values are
serialized with ``json.dumps(..., sort_keys=True, default=str)`` to handle
non-JSON-serialisable values gracefully.

Args:
    parameters: Tool call parameters to hash.

Returns:
    Hex-encoded SHA-256 digest of the canonical parameter serialization.

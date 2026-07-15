---
type: Concept
title: load_bytes()
id: func:parrot_tools.security.parsers._types.load_bytes
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Normalise content to bytes regardless of input type.
---

# load_bytes

```python
def load_bytes(content: bytes | Path) -> bytes
```

Normalise content to bytes regardless of input type.

Args:
    content: Raw bytes or path to a file.

Returns:
    File content as bytes.

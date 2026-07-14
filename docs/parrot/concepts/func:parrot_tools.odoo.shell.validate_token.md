---
type: Concept
title: validate_token()
id: func:parrot_tools.odoo.shell.validate_token
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Validate that a token contains only safe characters.
---

# validate_token

```python
def validate_token(token: str, label: str='token') -> None
```

Validate that a token contains only safe characters.

Rejects empty strings, path-traversal sequences (``..``), tokens
starting with a dot, and any character outside ``[a-zA-Z0-9_.-]``.

Args:
    token: The string to validate.
    label: Human-readable name for error messages.

Raises:
    ValueError: When the token is empty, contains path traversal, or
        contains illegal characters.

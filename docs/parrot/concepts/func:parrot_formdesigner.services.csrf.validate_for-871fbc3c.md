---
type: Concept
title: validate_form_csrf_token()
id: func:parrot_formdesigner.services.csrf.validate_form_csrf_token
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Validate a CSRF token against the in-process store.
---

# validate_form_csrf_token

```python
def validate_form_csrf_token(session_id: str, form_id: str, token: str) -> bool
```

Validate a CSRF token against the in-process store.

Performs a constant-time comparison to prevent timing attacks.  Expired
entries are pruned on access.

Args:
    session_id: Session identifier.
    form_id: Form identifier.
    token: Token string from the ``X-CSRF-Token`` / ``X-Form-CSRF-Token``
        request header.

Returns:
    ``True`` if the token matches and has not expired; ``False`` otherwise.

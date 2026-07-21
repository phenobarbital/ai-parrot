---
type: Concept
title: issue_form_csrf_token()
id: func:parrot_formdesigner.services.csrf.issue_form_csrf_token
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Issue a CSRF token for the given session / form pair.
---

# issue_form_csrf_token

```python
def issue_form_csrf_token(session_id: str, form_id: str) -> str
```

Issue a CSRF token for the given session / form pair.

The token is stored in-process with a TTL of :data:`_TTL_SECONDS`.
Any previously issued token for the same ``(session_id, form_id)`` is
replaced.

Args:
    session_id: Session identifier extracted from the navigator-auth
        session cookie.
    form_id: Form identifier from the URL path.

Returns:
    A URL-safe 32-byte random token string.

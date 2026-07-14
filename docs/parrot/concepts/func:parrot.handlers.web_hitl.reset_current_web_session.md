---
type: Concept
title: reset_current_web_session()
id: func:parrot.handlers.web_hitl.reset_current_web_session
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Reset the web session ContextVar to its previous value.
---

# reset_current_web_session

```python
def reset_current_web_session(token: Token) -> None
```

Reset the web session ContextVar to its previous value.

Should be called in a ``finally`` block to ensure the ContextVar is
cleaned up even when the request handler raises an exception.

Args:
    token: The :class:`contextvars.Token` returned by a prior call to
        :func:`set_current_web_session`.

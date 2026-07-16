---
type: Concept
title: set_current_web_session()
id: func:parrot.handlers.web_hitl.set_current_web_session
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Set the active web session ID for the current request context.
---

# set_current_web_session

```python
def set_current_web_session(session: Optional[str]) -> Token
```

Set the active web session ID for the current request context.

Args:
    session: WebSocket channel name (typically the user's ``session_id``
        or ``ws_channel_id``).

Returns:
    A :class:`contextvars.Token` that can be used to restore the previous
    value via :func:`reset_current_web_session`.

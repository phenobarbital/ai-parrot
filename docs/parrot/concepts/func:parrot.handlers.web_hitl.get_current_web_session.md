---
type: Concept
title: get_current_web_session()
id: func:parrot.handlers.web_hitl.get_current_web_session
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the active web session ID for the current request context.
---

# get_current_web_session

```python
def get_current_web_session() -> Optional[str]
```

Return the active web session ID for the current request context.

Returns:
    The WebSocket channel name previously set by
    :func:`set_current_web_session`, or ``None`` if none was set.

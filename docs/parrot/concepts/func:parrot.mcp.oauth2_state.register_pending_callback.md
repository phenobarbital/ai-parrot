---
type: Concept
title: register_pending_callback()
id: func:parrot.mcp.oauth2_state.register_pending_callback
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Register a pending OAuth2 callback for the given state parameter.
---

# register_pending_callback

```python
def register_pending_callback(state: str) -> Tuple[asyncio.Event, Dict[str, str]]
```

Register a pending OAuth2 callback for the given state parameter.

The transport layer calls this to get the event/result pair before
opening the browser.  The callback route calls
:func:`resolve_pending_callback` when the code arrives.

Args:
    state: OAuth2 state parameter (must be unique per flow).

Returns:
    Tuple of (asyncio.Event, result_dict).  The event is set when
    the callback is received; result_dict is populated with
    ``{"code": ..., "state": ...}``.

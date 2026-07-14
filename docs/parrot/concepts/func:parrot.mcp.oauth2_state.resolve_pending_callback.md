---
type: Concept
title: resolve_pending_callback()
id: func:parrot.mcp.oauth2_state.resolve_pending_callback
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Resolve a pending OAuth2 callback by signalling the event.
---

# resolve_pending_callback

```python
def resolve_pending_callback(state: str, code: str) -> bool
```

Resolve a pending OAuth2 callback by signalling the event.

Called by the Navigator callback route after validating the incoming
redirect.  Pops the entry from the dict (preventing replay) and sets
the event so the waiting transport coroutine can continue.

Args:
    state: OAuth2 state parameter identifying the pending flow.
    code: Authorization code from the authorization server.

Returns:
    ``True`` if the callback was found and resolved, ``False`` if the
    state was unknown or already consumed.

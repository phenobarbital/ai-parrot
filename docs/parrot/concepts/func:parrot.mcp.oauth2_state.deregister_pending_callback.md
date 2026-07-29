---
type: Concept
title: deregister_pending_callback()
id: func:parrot.mcp.oauth2_state.deregister_pending_callback
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Remove a pending callback entry without signalling it.
---

# deregister_pending_callback

```python
def deregister_pending_callback(state: str) -> None
```

Remove a pending callback entry without signalling it.

Call this when the transport times out waiting for the callback, to prevent
the abandoned state entry from accumulating in ``_pending_mcp_callbacks``
indefinitely.

Args:
    state: OAuth2 state parameter to remove.

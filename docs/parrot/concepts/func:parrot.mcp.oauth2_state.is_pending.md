---
type: Concept
title: is_pending()
id: func:parrot.mcp.oauth2_state.is_pending
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return ``True`` if there is a pending callback for the given state.
---

# is_pending

```python
def is_pending(state: str) -> bool
```

Return ``True`` if there is a pending callback for the given state.

Args:
    state: OAuth2 state parameter.

Returns:
    ``True`` if the state is registered, ``False`` otherwise.

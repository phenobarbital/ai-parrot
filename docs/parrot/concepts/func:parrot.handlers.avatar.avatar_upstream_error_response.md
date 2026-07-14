---
type: Concept
title: avatar_upstream_error_response()
id: func:parrot.handlers.avatar.avatar_upstream_error_response
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Translate a LiveAvatar upstream error into a clean JSON response.
---

# avatar_upstream_error_response

```python
def avatar_upstream_error_response(exc: ClientResponseError) -> web.Response
```

Translate a LiveAvatar upstream error into a clean JSON response.

Without this, the upstream ``ClientResponseError`` propagates and aiohttp
returns a bare ``500`` whose body does NOT carry the reason — the frontend
cannot tell "no credits" from a real server bug.  Map the two cases the
frontend acts on:

  * "No credits" (LiveAvatar code ``4033`` / ``403``) -> ``402`` so the UI
    can show an actionable "avatar has no credits" message.
  * Any other upstream failure -> ``502`` (provider error).

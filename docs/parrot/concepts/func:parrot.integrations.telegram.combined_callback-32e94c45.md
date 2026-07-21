---
type: Concept
title: combined_auth_callback_handler()
id: func:parrot.integrations.telegram.combined_callback.combined_auth_callback_handler
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handle the combined BasicAuth + secondary OAuth redirect.
---

# combined_auth_callback_handler

```python
async def combined_auth_callback_handler(request: web.Request) -> web.Response
```

Handle the combined BasicAuth + secondary OAuth redirect.

Query parameters:
    code: Authorization code from the OAuth provider (required on success).
    state: CSRF nonce echoed back by the provider (required on success).
    provider: Name of the secondary provider (defaults to ``"jira"``).
    error, error_description: Present if the user denied consent.

Returns:
    HTML response. Success path returns 200 with a page that calls
    ``Telegram.WebApp.sendData`` and closes the WebApp. Missing
    parameters return 400; provider-reported errors return 200 with
    an error page (so the WebApp closes cleanly).

---
type: Concept
title: oauth2_callback_handler()
id: func:parrot.integrations.telegram.oauth2_callback.oauth2_callback_handler
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handle OAuth2 provider redirect with authorization code.
---

# oauth2_callback_handler

```python
async def oauth2_callback_handler(request: web.Request) -> web.Response
```

Handle OAuth2 provider redirect with authorization code.

Extracts ``code`` and ``state`` from query parameters and returns
an HTML page that passes them back to Telegram via WebApp.sendData().

Args:
    request: The aiohttp request from the OAuth2 provider redirect.

Returns:
    HTML response with Telegram WebApp integration script.

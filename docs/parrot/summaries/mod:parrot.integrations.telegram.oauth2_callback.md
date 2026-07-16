---
type: Wiki Summary
title: parrot.integrations.telegram.oauth2_callback
id: mod:parrot.integrations.telegram.oauth2_callback
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: OAuth2 callback endpoint for Telegram WebApp authentication.
relates_to:
- concept: func:parrot.integrations.telegram.oauth2_callback.oauth2_callback_handler
  rel: defines
- concept: func:parrot.integrations.telegram.oauth2_callback.setup_oauth2_routes
  rel: defines
---

# `parrot.integrations.telegram.oauth2_callback`

OAuth2 callback endpoint for Telegram WebApp authentication.

Handles the OAuth2 provider redirect after user authentication.
Captures the authorization code and state, then returns an HTML page
that passes the data back to Telegram via WebApp.sendData().

## Functions

- `async def oauth2_callback_handler(request: web.Request) -> web.Response` — Handle OAuth2 provider redirect with authorization code.
- `def setup_oauth2_routes(app: web.Application, path: str='/oauth2/callback') -> None` — Register OAuth2 callback route on the aiohttp application.

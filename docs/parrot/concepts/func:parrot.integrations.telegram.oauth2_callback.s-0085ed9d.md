---
type: Concept
title: setup_oauth2_routes()
id: func:parrot.integrations.telegram.oauth2_callback.setup_oauth2_routes
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Register OAuth2 callback route on the aiohttp application.
---

# setup_oauth2_routes

```python
def setup_oauth2_routes(app: web.Application, path: str='/oauth2/callback') -> None
```

Register OAuth2 callback route on the aiohttp application.

Args:
    app: The aiohttp application instance.
    path: URL path for the callback endpoint.

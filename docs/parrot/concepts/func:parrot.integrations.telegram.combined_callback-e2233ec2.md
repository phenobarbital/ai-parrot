---
type: Concept
title: setup_combined_auth_routes()
id: func:parrot.integrations.telegram.combined_callback.setup_combined_auth_routes
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register the combined callback route and exclude it from auth.
---

# setup_combined_auth_routes

```python
def setup_combined_auth_routes(app: web.Application, path: str=COMBINED_CALLBACK_PATH) -> None
```

Register the combined callback route and exclude it from auth.

Args:
    app: The aiohttp application instance.
    path: URL path for the combined callback endpoint.

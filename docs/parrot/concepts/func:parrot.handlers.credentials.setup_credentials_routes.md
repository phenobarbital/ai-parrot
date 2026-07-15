---
type: Concept
title: setup_credentials_routes()
id: func:parrot.handlers.credentials.setup_credentials_routes
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register credential management routes on the aiohttp application.
---

# setup_credentials_routes

```python
def setup_credentials_routes(app: web.Application) -> None
```

Register credential management routes on the aiohttp application.

Registers two routes:
- ``/api/v1/users/credentials`` — collection-level (GET all, POST create)
- ``/api/v1/users/credentials/{name}`` — item-level (GET one, PUT, DELETE)

Args:
    app: The aiohttp :class:`web.Application` instance.

---
type: Concept
title: setup_oauth2_routes()
id: func:parrot.auth.oauth2_routes.setup_oauth2_routes
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Attach the OAuth2 callback route for ``provider_id`` to *app*.
---

# setup_oauth2_routes

```python
def setup_oauth2_routes(app: web.Application, provider_id: str, callback_path: str) -> None
```

Attach the OAuth2 callback route for ``provider_id`` to *app*.

Idempotent — calling twice with the same arguments is a no-op.

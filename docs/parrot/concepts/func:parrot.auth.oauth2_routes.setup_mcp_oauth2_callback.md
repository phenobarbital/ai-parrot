---
type: Concept
title: setup_mcp_oauth2_callback()
id: func:parrot.auth.oauth2_routes.setup_mcp_oauth2_callback
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Register the MCP OAuth2 callback route on *app*.
---

# setup_mcp_oauth2_callback

```python
def setup_mcp_oauth2_callback(app: web.Application) -> None
```

Register the MCP OAuth2 callback route on *app*.

Idempotent — calling twice is a no-op.  The route is registered at
``/api/auth/oauth2/mcp/callback`` and excluded from auth middleware.

Args:
    app: The aiohttp web application.

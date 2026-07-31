---
type: Concept
title: handle_mcp_oauth2_callback()
id: func:parrot.auth.oauth2_routes.handle_mcp_oauth2_callback
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handle OAuth2 callback for MCP server authorization code flows.
---

# handle_mcp_oauth2_callback

```python
async def handle_mcp_oauth2_callback(request: web.Request) -> web.Response
```

Handle OAuth2 callback for MCP server authorization code flows.

This route is called by the authorization server after the user grants
access.  It dispatches the authorization code to the waiting transport
coroutine via the shared ``_pending_mcp_callbacks`` dict in
:mod:`parrot.mcp.oauth2_state`.

Route: ``GET /api/auth/oauth2/mcp/callback``

Query parameters:
    code: Authorization code from the authorization server.
    state: OAuth2 state parameter identifying the pending flow.
    error: Error code from the authorization server (optional).
    error_description: Human-readable error description (optional).

Returns:
    HTML response with success or error message.

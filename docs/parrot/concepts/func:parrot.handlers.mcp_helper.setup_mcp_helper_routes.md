---
type: Concept
title: setup_mcp_helper_routes()
id: func:parrot.handlers.mcp_helper.setup_mcp_helper_routes
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Register MCP helper management routes on the aiohttp application.
---

# setup_mcp_helper_routes

```python
def setup_mcp_helper_routes(app: web.Application) -> None
```

Register MCP helper management routes on the aiohttp application.

Registers four routes:
- ``GET  /api/v1/agents/chat/{agent_id}/mcp-servers``
  → :class:`MCPHelperHandler` (catalog)
- ``POST /api/v1/agents/chat/{agent_id}/mcp-servers``
  → :class:`MCPHelperHandler` (activate)
- ``GET  /api/v1/agents/chat/{agent_id}/mcp-servers/active``
  → :class:`MCPActiveHandler` (list active)
- ``DELETE /api/v1/agents/chat/{agent_id}/mcp-servers/{server_name}``
  → :class:`MCPServerItemHandler` (deactivate)

Args:
    app: The aiohttp :class:`~aiohttp.web.Application` instance.

---
type: Wiki Entity
title: MCPHelperHandler
id: class:parrot.handlers.mcp_helper.MCPHelperHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: HTTP handler for MCP server catalog listing and activation.
---

# MCPHelperHandler

Defined in [`parrot.handlers.mcp_helper`](../summaries/mod:parrot.handlers.mcp_helper.md).

```python
class MCPHelperHandler(BaseView)
```

HTTP handler for MCP server catalog listing and activation.

Handles two routes:
- ``GET  /api/v1/agents/chat/{agent_id}/mcp-servers`` — full catalog
- ``POST /api/v1/agents/chat/{agent_id}/mcp-servers`` — activate server

## Methods

- `async def get(self) -> web.Response` — Return the full catalog of pre-built MCP server helpers.
- `async def post(self) -> web.Response` — Activate a pre-built MCP server on the session ToolManager.

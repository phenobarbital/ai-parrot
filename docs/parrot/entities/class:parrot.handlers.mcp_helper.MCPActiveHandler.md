---
type: Wiki Entity
title: MCPActiveHandler
id: class:parrot.handlers.mcp_helper.MCPActiveHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: HTTP handler that returns the currently active MCP servers in the session.
---

# MCPActiveHandler

Defined in [`parrot.handlers.mcp_helper`](../summaries/mod:parrot.handlers.mcp_helper.md).

```python
class MCPActiveHandler(BaseView)
```

HTTP handler that returns the currently active MCP servers in the session.

Handles one route:
- ``GET /api/v1/agents/chat/{agent_id}/mcp-servers/active``

## Methods

- `async def get(self) -> web.Response` — Return the list of active MCP servers from the session ToolManager.

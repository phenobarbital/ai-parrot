---
type: Wiki Entity
title: MCPServerItemHandler
id: class:parrot.handlers.mcp_helper.MCPServerItemHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTTP handler for deactivating a specific MCP server.
---

# MCPServerItemHandler

Defined in [`parrot.handlers.mcp_helper`](../summaries/mod:parrot.handlers.mcp_helper.md).

```python
class MCPServerItemHandler(BaseView)
```

HTTP handler for deactivating a specific MCP server.

Handles one route:
- ``DELETE /api/v1/agents/chat/{agent_id}/mcp-servers/{server_name}``

## Methods

- `async def delete(self) -> web.Response` — Deactivate an MCP server: remove from ToolManager, soft-delete from DB.

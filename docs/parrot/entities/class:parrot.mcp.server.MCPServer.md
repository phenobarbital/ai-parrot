---
type: Wiki Entity
title: MCPServer
id: class:parrot.mcp.server.MCPServer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Main MCP server class that chooses transport.
---

# MCPServer

Defined in [`parrot.mcp.server`](../summaries/mod:parrot.mcp.server.md).

```python
class MCPServer
```

Main MCP server class that chooses transport.

## Methods

- `def register_tool(self, tool: AbstractTool)` — Register a tool.
- `def register_tools(self, tools: List[AbstractTool])` — Register multiple tools.
- `async def start(self)` — Start the server.
- `async def stop(self)` — Start the server.

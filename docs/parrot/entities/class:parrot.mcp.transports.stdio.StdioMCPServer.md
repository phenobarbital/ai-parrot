---
type: Wiki Entity
title: StdioMCPServer
id: class:parrot.mcp.transports.stdio.StdioMCPServer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: MCP server using stdio transport.
relates_to:
- concept: class:parrot.mcp.transports.base.MCPServerBase
  rel: extends
---

# StdioMCPServer

Defined in [`parrot.mcp.transports.stdio`](../summaries/mod:parrot.mcp.transports.stdio.md).

```python
class StdioMCPServer(MCPServerBase)
```

MCP server using stdio transport.

## Methods

- `async def start(self)` — Start the stdio MCP server.
- `async def stop(self)` — Stop the stdio server.

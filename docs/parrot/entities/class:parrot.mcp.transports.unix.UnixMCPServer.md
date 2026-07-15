---
type: Wiki Entity
title: UnixMCPServer
id: class:parrot.mcp.transports.unix.UnixMCPServer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: MCP server using Unix socket transport.
relates_to:
- concept: class:parrot.mcp.transports.base.MCPServerBase
  rel: extends
---

# UnixMCPServer

Defined in [`parrot.mcp.transports.unix`](../summaries/mod:parrot.mcp.transports.unix.md).

```python
class UnixMCPServer(MCPServerBase)
```

MCP server using Unix socket transport.

## Methods

- `def add_shutdown_handler(self, handler: Callable)` — Register user-defined shutdown handler.
- `async def start(self)` — Start Unix socket server.
- `async def stop(self)` — Stop the server and cleanup.

---
type: Wiki Entity
title: QuicMCPServer
id: class:parrot.mcp.transports.quic.QuicMCPServer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: QUIC/HTTP3 MCP Server with WebTransport support.
relates_to:
- concept: class:parrot.mcp.transports.base.MCPServerBase
  rel: extends
---

# QuicMCPServer

Defined in [`parrot.mcp.transports.quic`](../summaries/mod:parrot.mcp.transports.quic.md).

```python
class QuicMCPServer(MCPServerBase)
```

QUIC/HTTP3 MCP Server with WebTransport support.

Inherits behavior from MCPServerBase and adds QUIC transport layer.

Example:
    >>> from parrot.mcp.server import MCPServerConfig
    >>> 
    >>> config = MCPServerConfig(
    ...     name="high-perf-mcp",
    ...     transport="quic",
    ...     host="0.0.0.0",
    ...     port=4433,
    ... )
    >>> 
    >>> server = QuicMCPServer(config)
    >>> server.register_tool(MySearchTool())
    >>> server.register_tool(MyDatabaseTool())
    >>> 
    >>> await server.start()

## Methods

- `async def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]` — Handle tools/call request.
- `async def start(self) -> None` — Start the QUIC MCP server.
- `async def stop(self) -> None` — Stop the QUIC MCP server.
- `def broadcast_datagram(self, data: bytes) -> None` — Broadcast unreliable datagram to all connected clients.
- `def is_running(self) -> bool`

---
type: Wiki Entity
title: WebSocketMCPSession
id: class:parrot.mcp.transports.websocket.WebSocketMCPSession
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: MCP client session for WebSocket transport.
---

# WebSocketMCPSession

Defined in [`parrot.mcp.transports.websocket`](../summaries/mod:parrot.mcp.transports.websocket.md).

```python
class WebSocketMCPSession
```

MCP client session for WebSocket transport.

Implements the client side of SEP-1288 WebSocket transport:
- Connects to WebSocket MCP server
- Manages session ID persistence
- Handles request/response matching
- Supports automatic reconnection
- Receives server-initiated notifications

## Methods

- `async def connect(self)` — Connect to WebSocket MCP server.
- `async def list_tools(self)` — List available tools from MCP server.
- `async def call_tool(self, tool_name: str, arguments: dict)` — Call a tool on the MCP server.
- `async def disconnect(self)` — Disconnect from WebSocket server.

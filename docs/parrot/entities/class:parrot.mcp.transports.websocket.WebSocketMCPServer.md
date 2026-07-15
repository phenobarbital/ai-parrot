---
type: Wiki Entity
title: WebSocketMCPServer
id: class:parrot.mcp.transports.websocket.WebSocketMCPServer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: MCP server using WebSocket transport for bidirectional communication.
relates_to:
- concept: class:parrot.mcp.oauth_server.OAuthRoutesMixin
  rel: extends
- concept: class:parrot.mcp.transports.base.MCPServerBase
  rel: extends
---

# WebSocketMCPServer

Defined in [`parrot.mcp.transports.websocket`](../summaries/mod:parrot.mcp.transports.websocket.md).

```python
class WebSocketMCPServer(OAuthRoutesMixin, MCPServerBase)
```

MCP server using WebSocket transport for bidirectional communication.

Implements the WebSocket transport as proposed in SEP-1288:
- Session-based connection management (single connection per session)
- Bidirectional JSON-RPC communication
- Server-initiated notifications support
- OAuth authentication via query params or websocket subprotocol
- Automatic ping/pong keep-alive

## Methods

- `async def start(self)` — Start the WebSocket MCP server.
- `async def stop(self)` — Stop the WebSocket server.
- `async def send_notification(self, session_id: str, method: str, params: Dict[str, Any])` — Send server-initiated notification to client.

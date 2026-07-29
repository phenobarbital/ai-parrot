---
type: Wiki Summary
title: parrot.mcp.transports.websocket
id: mod:parrot.mcp.transports.websocket
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.mcp.transports.websocket
relates_to:
- concept: class:parrot.mcp.transports.websocket.WebSocketConnection
  rel: defines
- concept: class:parrot.mcp.transports.websocket.WebSocketMCPServer
  rel: defines
- concept: class:parrot.mcp.transports.websocket.WebSocketMCPSession
  rel: defines
- concept: mod:parrot.mcp.client
  rel: references
- concept: mod:parrot.mcp.config
  rel: references
- concept: mod:parrot.mcp.oauth_server
  rel: references
- concept: mod:parrot.mcp.transports.base
  rel: references
---

# `parrot.mcp.transports.websocket`

## Classes

- **`WebSocketConnection`** — Represents an active WebSocket connection with session info.
- **`WebSocketMCPServer(OAuthRoutesMixin, MCPServerBase)`** — MCP server using WebSocket transport for bidirectional communication.
- **`WebSocketMCPSession`** — MCP client session for WebSocket transport.

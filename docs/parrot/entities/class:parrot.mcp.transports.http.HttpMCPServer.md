---
type: Wiki Entity
title: HttpMCPServer
id: class:parrot.mcp.transports.http.HttpMCPServer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: MCP server using HTTP transport.
relates_to:
- concept: class:parrot.mcp.oauth_server.OAuthRoutesMixin
  rel: extends
- concept: class:parrot.mcp.transports.base.MCPServerBase
  rel: extends
---

# HttpMCPServer

Defined in [`parrot.mcp.transports.http`](../summaries/mod:parrot.mcp.transports.http.md).

```python
class HttpMCPServer(OAuthRoutesMixin, MCPServerBase)
```

MCP server using HTTP transport.

## Methods

- `async def start(self)` — Start the HTTP server.
- `async def stop(self)` — Stop the HTTP server.

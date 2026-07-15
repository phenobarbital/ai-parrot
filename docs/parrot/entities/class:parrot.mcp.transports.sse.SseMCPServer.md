---
type: Wiki Entity
title: SseMCPServer
id: class:parrot.mcp.transports.sse.SseMCPServer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: MCP server using SSE transport compatible with ChatGPT and OpenAI MCP clients.
relates_to:
- concept: class:parrot.mcp.oauth_server.OAuthRoutesMixin
  rel: extends
- concept: class:parrot.mcp.transports.base.MCPServerBase
  rel: extends
---

# SseMCPServer

Defined in [`parrot.mcp.transports.sse`](../summaries/mod:parrot.mcp.transports.sse.md).

```python
class SseMCPServer(OAuthRoutesMixin, MCPServerBase)
```

MCP server using SSE transport compatible with ChatGPT and OpenAI MCP clients.

## Methods

- `async def start(self)` — Start the SSE MCP server.
- `async def stop(self)` — Stop the SSE server.

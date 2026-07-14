---
type: Wiki Summary
title: parrot.mcp.transports.sse
id: mod:parrot.mcp.transports.sse
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.mcp.transports.sse
relates_to:
- concept: class:parrot.mcp.transports.sse.SseMCPServer
  rel: defines
- concept: class:parrot.mcp.transports.sse.SseMCPSession
  rel: defines
- concept: mod:parrot.mcp.client
  rel: references
- concept: mod:parrot.mcp.config
  rel: references
- concept: mod:parrot.mcp.oauth_server
  rel: references
- concept: mod:parrot.mcp.transports.base
  rel: references
- concept: mod:parrot.mcp.transports.http
  rel: references
---

# `parrot.mcp.transports.sse`

## Classes

- **`SseMCPServer(OAuthRoutesMixin, MCPServerBase)`** — MCP server using SSE transport compatible with ChatGPT and OpenAI MCP clients.
- **`SseMCPSession(HttpMCPSession)`** — MCP session using SSE (Server-Sent Events) for transport.

---
type: Wiki Summary
title: parrot.mcp.transports.http
id: mod:parrot.mcp.transports.http
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.mcp.transports.http
relates_to:
- concept: class:parrot.mcp.transports.http.HttpMCPServer
  rel: defines
- concept: class:parrot.mcp.transports.http.HttpMCPSession
  rel: defines
- concept: mod:parrot.mcp.client
  rel: references
- concept: mod:parrot.mcp.config
  rel: references
- concept: mod:parrot.mcp.oauth2_config
  rel: references
- concept: mod:parrot.mcp.oauth2_state
  rel: references
- concept: mod:parrot.mcp.oauth2_storage
  rel: references
- concept: mod:parrot.mcp.oauth_server
  rel: references
- concept: mod:parrot.mcp.transports.base
  rel: references
---

# `parrot.mcp.transports.http`

## Classes

- **`HttpMCPServer(OAuthRoutesMixin, MCPServerBase)`** — MCP server using HTTP transport.
- **`HttpMCPSession`** — MCP session for HTTP/SSE transport using aiohttp.

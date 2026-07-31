---
type: Wiki Entity
title: HttpMCPSession
id: class:parrot.mcp.transports.http.HttpMCPSession
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: MCP session for HTTP/SSE transport using aiohttp.
---

# HttpMCPSession

Defined in [`parrot.mcp.transports.http`](../summaries/mod:parrot.mcp.transports.http.md).

```python
class HttpMCPSession
```

MCP session for HTTP/SSE transport using aiohttp.

## Methods

- `async def connect(self)` — Connect to MCP server via HTTP.
- `async def list_tools(self)` — List available tools via HTTP.
- `async def call_tool(self, tool_name: str, arguments: dict)` — Call a tool via HTTP.
- `async def disconnect(self)` — Disconnect HTTP session.

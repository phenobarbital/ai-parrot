---
type: Wiki Entity
title: SseMCPSession
id: class:parrot.mcp.transports.sse.SseMCPSession
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: MCP session using SSE (Server-Sent Events) for transport.
relates_to:
- concept: class:parrot.mcp.transports.http.HttpMCPSession
  rel: extends
---

# SseMCPSession

Defined in [`parrot.mcp.transports.sse`](../summaries/mod:parrot.mcp.transports.sse.md).

```python
class SseMCPSession(HttpMCPSession)
```

MCP session using SSE (Server-Sent Events) for transport.

## Methods

- `async def connect(self)` — Connect to MCP server via SSE + HTTP.
- `async def disconnect(self)` — Disconnect SSE session.

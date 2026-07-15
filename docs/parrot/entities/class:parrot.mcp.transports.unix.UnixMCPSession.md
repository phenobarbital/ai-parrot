---
type: Wiki Entity
title: UnixMCPSession
id: class:parrot.mcp.transports.unix.UnixMCPSession
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: MCP session for Unix socket transport.
---

# UnixMCPSession

Defined in [`parrot.mcp.transports.unix`](../summaries/mod:parrot.mcp.transports.unix.md).

```python
class UnixMCPSession
```

MCP session for Unix socket transport.

## Methods

- `async def connect(self)` — Connect to MCP server via Unix socket.
- `async def list_tools(self)` — List available tools.
- `async def call_tool(self, tool_name: str, arguments: dict)` — Call a tool.
- `async def disconnect(self)` — Disconnect Unix socket session.

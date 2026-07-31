---
type: Wiki Entity
title: StdioMCPSession
id: class:parrot.mcp.transports.stdio.StdioMCPSession
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: MCP session for stdio transport.
---

# StdioMCPSession

Defined in [`parrot.mcp.transports.stdio`](../summaries/mod:parrot.mcp.transports.stdio.md).

```python
class StdioMCPSession
```

MCP session for stdio transport.

## Methods

- `async def connect(self)` — Connect to MCP server via stdio.
- `async def list_tools(self)` — List available tools.
- `async def call_tool(self, tool_name: str, arguments: dict)` — Call a tool.
- `async def disconnect(self)` — Disconnect stdio session.

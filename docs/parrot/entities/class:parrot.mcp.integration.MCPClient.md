---
type: Wiki Entity
title: MCPClient
id: class:parrot.mcp.integration.MCPClient
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Complete MCP client with stdio and HTTP transport support.
---

# MCPClient

Defined in [`parrot.mcp.integration`](../summaries/mod:parrot.mcp.integration.md).

```python
class MCPClient
```

Complete MCP client with stdio and HTTP transport support.

## Methods

- `async def connect(self)` — Connect to MCP server using appropriate transport.
- `async def call_tool(self, tool_name: str, arguments: Dict[str, Any], headers: Optional[Dict[str, str]]=None)` — Call an MCP tool.
- `async def get_available_tools(self) -> List[Dict[str, Any]]` — Get raw available tools from server.
- `def get_tools_for_context(self, context: Optional['ReadonlyContext']=None) -> List[Dict[str, Any]]` — Get tools, filtered by context.
- `async def get_tools(self, context: Optional['ReadonlyContext']=None) -> List[MCPToolProxy]` — Get tools filtered by configuration and context.
- `async def disconnect(self)` — Disconnect from MCP server.

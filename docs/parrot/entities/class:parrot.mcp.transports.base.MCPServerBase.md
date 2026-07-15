---
type: Wiki Entity
title: MCPServerBase
id: class:parrot.mcp.transports.base.MCPServerBase
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base class for MCP servers.
---

# MCPServerBase

Defined in [`parrot.mcp.transports.base`](../summaries/mod:parrot.mcp.transports.base.md).

```python
class MCPServerBase(ABC)
```

Base class for MCP servers.

## Methods

- `def register_resource(self, resource: MCPResource, read_handler: Callable[[str], Awaitable[str | bytes]])` — Register a resource with the MCP server.
- `async def handle_resources_list(self, params: Dict[str, Any]) -> Dict[str, Any]` — Handle resources/list request.
- `async def handle_resources_read(self, params: Dict[str, Any]) -> Dict[str, Any]` — Handle resources/read request.
- `async def handle_prompts_list(self, params: Dict[str, Any]) -> Dict[str, Any]` — Handle prompts/list request.
- `def register_tool(self, tool: AbstractTool)` — Register an AI-Parrot tool with the MCP server.
- `def register_tools(self, tools: List[AbstractTool])` — Register multiple tools.
- `async def handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]` — Handle MCP initialize request.
- `async def handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]` — Handle tools/list request.
- `async def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]` — Handle tools/call request.
- `async def start(self)` — Start the MCP server.
- `async def stop(self)` — Stop the MCP server.

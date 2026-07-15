---
type: Wiki Entity
title: MCPToolAdapter
id: class:parrot.mcp.adapter.MCPToolAdapter
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Adapts AI-Parrot AbstractTool to MCP tool format.
---

# MCPToolAdapter

Defined in [`parrot.mcp.adapter`](../summaries/mod:parrot.mcp.adapter.md).

```python
class MCPToolAdapter
```

Adapts AI-Parrot AbstractTool to MCP tool format.

## Methods

- `def to_mcp_tool_definition(self) -> Dict[str, Any]` — Convert AbstractTool to MCP tool definition.
- `async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]` — Execute the AI-Parrot tool and convert result to MCP format.

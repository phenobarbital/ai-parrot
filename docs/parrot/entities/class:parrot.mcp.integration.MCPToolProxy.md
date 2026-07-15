---
type: Wiki Entity
title: MCPToolProxy
id: class:parrot.mcp.integration.MCPToolProxy
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Proxy tool that wraps an individual MCP tool.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# MCPToolProxy

Defined in [`parrot.mcp.integration`](../summaries/mod:parrot.mcp.integration.md).

```python
class MCPToolProxy(AbstractTool)
```

Proxy tool that wraps an individual MCP tool.

## Methods

- `def validate_args(self, **kwargs) -> Dict[str, Any]` — Bypass Pydantic validation for MCP tools.
- `def get_tool_schema(self) -> Dict[str, Any]` — Override to return the MCP tool schema directly.

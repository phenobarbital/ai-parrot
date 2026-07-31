---
type: Wiki Entity
title: MCPServerParam
id: class:parrot.mcp.registry.MCPServerParam
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Describes a single parameter accepted by an MCP server helper.
---

# MCPServerParam

Defined in [`parrot.mcp.registry`](../summaries/mod:parrot.mcp.registry.md).

```python
class MCPServerParam(BaseModel)
```

Describes a single parameter accepted by an MCP server helper.

Attributes:
    name: Parameter name (matches the Python keyword argument).
    type: Expected value type; use ``SECRET`` for credentials.
    required: Whether the caller must supply a value.
    default: Default value used when ``required`` is ``False``.
    description: Human-readable explanation shown in the catalog.

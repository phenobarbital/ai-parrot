---
type: Wiki Entity
title: MCPParamType
id: class:parrot.mcp.registry.MCPParamType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Type hint for an MCP server parameter.
---

# MCPParamType

Defined in [`parrot.mcp.registry`](../summaries/mod:parrot.mcp.registry.md).

```python
class MCPParamType(str, Enum)
```

Type hint for an MCP server parameter.

The ``SECRET`` variant signals that the frontend should mask the input
field and that the value must be stored in the Vault rather than
persisted in DocumentDB plaintext.

---
type: Wiki Entity
title: MCPServerDescriptor
id: class:parrot.mcp.registry.MCPServerDescriptor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Catalog entry describing a single pre-built MCP server helper.
---

# MCPServerDescriptor

Defined in [`parrot.mcp.registry`](../summaries/mod:parrot.mcp.registry.md).

```python
class MCPServerDescriptor(BaseModel)
```

Catalog entry describing a single pre-built MCP server helper.

Attributes:
    name: Registry slug used as the identifier in API requests
        (e.g. ``"perplexity"``).
    display_name: Human-friendly label for UI display.
    description: What the MCP server does.
    method_name: Name of the ``MCPEnabledMixin`` method to call
        (e.g. ``"add_perplexity_mcp_server"``).
    params: Ordered list of accepted parameters.
    category: Grouping label for the catalog
        (e.g. ``"search"``, ``"media"``, ``"dev-tools"``).
    activatable: Whether the server can be activated via the POST endpoint.
        Servers without a ``create_*`` factory (e.g. ``genmedia``) should
        set this to ``False``.

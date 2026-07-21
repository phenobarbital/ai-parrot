---
type: Wiki Entity
title: MCPClientConfig
id: class:parrot.mcp.client.MCPClientConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Complete configuration for external MCP server connection.
---

# MCPClientConfig

Defined in [`parrot.mcp.client`](../summaries/mod:parrot.mcp.client.md).

```python
class MCPClientConfig
```

Complete configuration for external MCP server connection.

Supports both static configuration and dynamic behavior through
header_provider and token_supplier callbacks.

Example:
    >>> # Static config
    >>> config = MCPClientConfig(
    ...     name="my-server",
    ...     url="http://localhost:8080/mcp",
    ...     transport="http",
    ...     headers={"X-API-Key": "secret"}
    ... )

    >>> # Dynamic headers based on context
    >>> def my_header_provider(ctx):
    ...     return {"X-User-ID": ctx.user_id} if ctx else {}
    >>> config = MCPClientConfig(
    ...     name="my-server",
    ...     url="http://localhost:8080/mcp",
    ...     header_provider=my_header_provider
    ... )

## Methods

- `async def get_headers(self, context: Optional['ReadonlyContext']=None) -> Dict[str, str]` — Get merged static, auth, and dynamic headers.
- `def validate_transport(self) -> None` — Validate transport-specific configuration.
- `def from_yaml_config(cls, config_dict: Dict[str, Any], config_abs_path: str='') -> 'MCPClientConfig'` — Load from YAML configuration with validation.

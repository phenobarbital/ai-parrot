---
type: Wiki Entity
title: UserMCPServerConfig
id: class:parrot.mcp.registry.UserMCPServerConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Persisted configuration for a user-activated MCP server.
---

# UserMCPServerConfig

Defined in [`parrot.mcp.registry`](../summaries/mod:parrot.mcp.registry.md).

```python
class UserMCPServerConfig(BaseModel)
```

Persisted configuration for a user-activated MCP server.

This document is stored in the ``user_mcp_configs`` DocumentDB collection.
Secret parameters (API keys, tokens) are **never** stored here — they live
in the Vault; ``vault_credential_name`` points to the Vault entry.

Attributes:
    server_name: Registry slug of the activated server.
    agent_id: Agent the server is scoped to.
    user_id: Owner of this configuration.
    params: Non-secret configuration parameters.
    vault_credential_name: Name of the Vault credential that holds
        any secret values (``None`` if no secrets are required).
    active: Soft-delete flag; ``False`` means this config is deactivated.
    created_at: ISO-8601 timestamp of initial creation.
    updated_at: ISO-8601 timestamp of last update.

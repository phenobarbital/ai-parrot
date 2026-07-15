---
type: Wiki Entity
title: MCPPersistenceService
id: class:parrot.handlers.mcp_persistence.MCPPersistenceService
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handles saving and loading user MCP server configurations in DocumentDB.
---

# MCPPersistenceService

Defined in [`parrot.handlers.mcp_persistence`](../summaries/mod:parrot.handlers.mcp_persistence.md).

```python
class MCPPersistenceService
```

Handles saving and loading user MCP server configurations in DocumentDB.

All documents are scoped by the compound key ``(user_id, agent_id,
server_name)``.  Deactivation is a soft-delete that sets ``active=False``
so the configuration can be re-activated in the future without data loss.

Methods:
    save_user_mcp_config: Upsert a config document.
    load_user_mcp_configs: Retrieve all active configs for a user/agent.
    remove_user_mcp_config: Soft-delete a config (sets active=False).

## Methods

- `async def save_user_mcp_config(self, config: UserMCPServerConfig) -> None` — Upsert a user MCP server configuration in DocumentDB.
- `async def load_user_mcp_configs(self, user_id: str, agent_id: str) -> List[UserMCPServerConfig]` — Load all active MCP server configs for a given user and agent.
- `async def remove_user_mcp_config(self, user_id: str, agent_id: str, server_name: str) -> bool` — Soft-delete a user MCP server configuration.

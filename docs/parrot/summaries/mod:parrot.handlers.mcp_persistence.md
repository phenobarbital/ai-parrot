---
type: Wiki Summary
title: parrot.handlers.mcp_persistence
id: mod:parrot.handlers.mcp_persistence
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: MCP Persistence Service — DocumentDB CRUD for user MCP server configs.
relates_to:
- concept: class:parrot.handlers.mcp_persistence.MCPPersistenceService
  rel: defines
- concept: mod:parrot.interfaces.documentdb
  rel: references
- concept: mod:parrot.mcp.registry
  rel: references
---

# `parrot.handlers.mcp_persistence`

MCP Persistence Service — DocumentDB CRUD for user MCP server configs.

Provides save, load, and soft-delete operations for
:class:`~parrot.mcp.registry.UserMCPServerConfig` documents, scoped by
``(user_id, agent_id)``.

The ``user_mcp_configs`` collection is created implicitly on the first write.
Secret values are **never** stored here — they live in the Vault.  The
``vault_credential_name`` field in each document points to the relevant Vault
entry.

Usage::

    service = MCPPersistenceService()
    await service.save_user_mcp_config(config)
    configs = await service.load_user_mcp_configs(user_id, agent_id)
    removed = await service.remove_user_mcp_config(user_id, agent_id, "perplexity")

## Classes

- **`MCPPersistenceService`** — Handles saving and loading user MCP server configurations in DocumentDB.

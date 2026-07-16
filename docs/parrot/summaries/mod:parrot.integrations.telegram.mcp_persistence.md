---
type: Wiki Summary
title: parrot.integrations.telegram.mcp_persistence
id: mod:parrot.integrations.telegram.mcp_persistence
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Telegram MCP Persistence Service — DocumentDB CRUD for /add_mcp configs.
relates_to:
- concept: class:parrot.integrations.telegram.mcp_persistence.TelegramMCPPersistenceService
  rel: defines
- concept: class:parrot.integrations.telegram.mcp_persistence.TelegramMCPPublicParams
  rel: defines
- concept: class:parrot.integrations.telegram.mcp_persistence.UserTelegramMCPConfig
  rel: defines
- concept: mod:parrot.interfaces.documentdb
  rel: references
---

# `parrot.integrations.telegram.mcp_persistence`

Telegram MCP Persistence Service — DocumentDB CRUD for /add_mcp configs.

Stores the *non-secret* subset of each ``/add_mcp`` JSON payload in the
``telegram_user_mcp_configs`` DocumentDB collection, scoped by
``(user_id, name)``.  Secret fields (``token``, ``api_key``, ``username``,
``password``) are **never** stored here — they live in the Vault.  The
``vault_credential_name`` field in each document points to the relevant Vault
entry.

This module is Telegram-scoped and intentionally separate from
:mod:`parrot.handlers.mcp_persistence` which handles catalog-activated MCP
servers (``UserMCPServerConfig`` / ``user_mcp_configs`` collection).

Usage::

    svc = TelegramMCPPersistenceService()
    await svc.save(user_id, name, public_params, vault_name)
    configs = await svc.list(user_id)
    removed = await svc.remove(user_id, name)

## Classes

- **`TelegramMCPPublicParams(BaseModel)`** — Non-secret subset of an /add_mcp payload safe to persist in DocumentDB.
- **`UserTelegramMCPConfig(BaseModel)`** — Persisted non-secret config for a /add_mcp HTTP server.
- **`TelegramMCPPersistenceService`** — CRUD for the ``telegram_user_mcp_configs`` DocumentDB collection.

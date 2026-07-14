---
type: Wiki Entity
title: TelegramMCPPersistenceService
id: class:parrot.integrations.telegram.mcp_persistence.TelegramMCPPersistenceService
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: CRUD for the ``telegram_user_mcp_configs`` DocumentDB collection.
---

# TelegramMCPPersistenceService

Defined in [`parrot.integrations.telegram.mcp_persistence`](../summaries/mod:parrot.integrations.telegram.mcp_persistence.md).

```python
class TelegramMCPPersistenceService
```

CRUD for the ``telegram_user_mcp_configs`` DocumentDB collection.

All documents are scoped by the compound key ``(user_id, name)``.
Deactivation is a soft-delete (``active=False``) so configurations can
be re-activated in the future without data loss.

Mirrors the pattern of :class:`~parrot.handlers.mcp_persistence.MCPPersistenceService`
but is dedicated to the Telegram ``/add_mcp`` free-form flow.

Methods:
    save: Upsert a config document.
    list: Retrieve all active configs for a user.
    read_one: Retrieve a single active config by name.
    remove: Soft-delete a config (sets ``active=False``).

## Methods

- `async def save(self, user_id: str, name: str, params: TelegramMCPPublicParams, vault_credential_name: Optional[str]) -> None` — Upsert a Telegram MCP server configuration in DocumentDB.
- `async def list(self, user_id: str) -> List[UserTelegramMCPConfig]` — Load all active MCP server configs for a given Telegram user.
- `async def read_one(self, user_id: str, name: str) -> Optional[UserTelegramMCPConfig]` — Retrieve a single active Telegram MCP config by name.
- `async def remove(self, user_id: str, name: str) -> tuple[bool, Optional[str]]` — Soft-delete a Telegram MCP server configuration.

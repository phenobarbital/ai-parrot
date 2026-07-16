---
type: Wiki Entity
title: UserTelegramMCPConfig
id: class:parrot.integrations.telegram.mcp_persistence.UserTelegramMCPConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Persisted non-secret config for a /add_mcp HTTP server.
---

# UserTelegramMCPConfig

Defined in [`parrot.integrations.telegram.mcp_persistence`](../summaries/mod:parrot.integrations.telegram.mcp_persistence.md).

```python
class UserTelegramMCPConfig(BaseModel)
```

Persisted non-secret config for a /add_mcp HTTP server.

Attributes:
    user_id: Telegram user identifier in ``tg:<telegram_id>`` format.
    name: Server name (the command's JSON ``name``).
    params: Non-secret connection parameters.
    vault_credential_name: Vault key name (``"tg_mcp_{name}"``) when
        secrets are present; ``None`` for ``auth_scheme=none``.
    active: ``False`` after a soft-delete via :meth:`TelegramMCPPersistenceService.remove`.
    created_at: ISO-8601 UTC timestamp of first insert.
    updated_at: ISO-8601 UTC timestamp of last upsert.

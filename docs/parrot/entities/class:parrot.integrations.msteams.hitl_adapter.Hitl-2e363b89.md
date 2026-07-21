---
type: Wiki Entity
title: HitlCloudAdapter
id: class:parrot.integrations.msteams.hitl_adapter.HitlCloudAdapter
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: CloudAdapter configured for the shared HITL bot identity.
---

# HitlCloudAdapter

Defined in [`parrot.integrations.msteams.hitl_adapter`](../summaries/mod:parrot.integrations.msteams.hitl_adapter.md).

```python
class HitlCloudAdapter(CloudAdapter)
```

CloudAdapter configured for the shared HITL bot identity.

Follows the same ``ConfigurationBotFrameworkAuthentication`` +
``BotFrameworkAdapterSettings`` pattern as the existing
``Adapter(CloudAdapter)`` in ``msteams/adapter.py:18``.

The adapter is *process-level shared*: a single instance is created
during ``setup_teams_hitl()`` and reused across all proactive sends /
inbound webhook calls.

Args:
    app_id: Microsoft App ID for the HITL bot.
    app_password: Microsoft App Password for the HITL bot.
    app_type: App type (defaults to ``"MultiTenant"``).
    tenant_id: AAD tenant ID for single-tenant apps.
    logger: Logger instance. Defaults to module logger.

## Methods

- `async def on_error(self, context: TurnContext, error: Exception) -> None` — Handle unhandled adapter errors.

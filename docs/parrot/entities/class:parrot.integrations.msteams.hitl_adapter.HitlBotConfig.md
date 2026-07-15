---
type: Wiki Entity
title: HitlBotConfig
id: class:parrot.integrations.msteams.hitl_adapter.HitlBotConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Minimal bot configuration shim for the HITL adapter.
---

# HitlBotConfig

Defined in [`parrot.integrations.msteams.hitl_adapter`](../summaries/mod:parrot.integrations.msteams.hitl_adapter.md).

```python
class HitlBotConfig
```

Minimal bot configuration shim for the HITL adapter.

Mirrors the ``BotConfig`` shape expected by
``ConfigurationBotFrameworkAuthentication``.  The HITL adapter uses
dedicated credentials (``MSTEAMS_HITL_APP_ID`` /
``MSTEAMS_HITL_APP_PASSWORD``) separate from any conversational-bot
credentials so the two identities remain independent.

Args:
    app_id: Microsoft App ID for the HITL bot.
    app_password: Microsoft App Password for the HITL bot.
    app_type: App type string (defaults to ``"MultiTenant"``).
    tenant_id: AAD tenant ID (used for single-tenant apps).

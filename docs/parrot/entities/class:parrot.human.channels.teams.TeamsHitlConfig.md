---
type: Wiki Entity
title: TeamsHitlConfig
id: class:parrot.human.channels.teams.TeamsHitlConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Boot configuration for the shared HITL bot identity.
---

# TeamsHitlConfig

Defined in [`parrot.human.channels.teams`](../summaries/mod:parrot.human.channels.teams.md).

```python
class TeamsHitlConfig(BaseModel)
```

Boot configuration for the shared HITL bot identity.

All credential fields must be supplied from navconfig / environment
variables.  Use ``${VAR_NAME}`` style substitution in your config
files — never hardcode secrets here.

Attributes:
    app_id: Microsoft App ID for the HITL bot (``MSTEAMS_HITL_APP_ID``).
    app_password: Microsoft App Password (``MSTEAMS_HITL_APP_PASSWORD``).
    tenant_id: AAD tenant ID (``MSTEAMS_TENANT_ID``).
    graph_client_id: Graph app registration client ID.
    graph_client_secret: Graph app registration client secret.
    graph_tenant_id: Tenant ID for the Graph app (may differ from bot tenant).
    redis_url: Async Redis connection URL.
    route: Webhook route for the HITL bot (default: ``/api/teams-hitl/messages``).
    convref_ttl: ConversationReference cache TTL in seconds (default: 30 days).
    app_type: Bot app type (``"MultiTenant"`` or ``"SingleTenant"``).

Per-agent override (OQ-9 / OQ-9-impl):
    A per-agent HITL identity is exposed via keyed channels on the
    ``HumanInteractionManager``.  Register it as a named entry instead
    of the default ``"teams"``::

        channel = TeamsHumanChannel(adapter, gc, redis, per_agent_config)
        manager.register_channel("teams:my-agent", channel)

    The agent's tier or HITL tool can then reference ``channel="teams:my-agent"``
    to select the dedicated identity.  The default shared identity remains
    at ``"teams"`` for all tiers that do not need a distinct bot appearance.
    Selection mechanism: keyed-channel pattern (simpler than BotConfig at
    construction, avoids deep construction-time coupling).

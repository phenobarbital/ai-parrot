---
type: Wiki Entity
title: MSAgentSDKWrapper
id: class:parrot.integrations.msagentsdk.wrapper.MSAgentSDKWrapper
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: ai-parrot integration wrapper for the Microsoft 365 Agents SDK.
---

# MSAgentSDKWrapper

Defined in [`parrot.integrations.msagentsdk.wrapper`](../summaries/mod:parrot.integrations.msagentsdk.wrapper.md).

```python
class MSAgentSDKWrapper
```

ai-parrot integration wrapper for the Microsoft 365 Agents SDK.

Registers a per-bot HTTP route at
``/api/msagentsdk/{safe_id}/messages`` on the aiohttp application (plus an
optional custom ``config.endpoint`` such as ``/api/messages``), creates a
``CloudAdapter`` (with optional Azure AD auth), and delegates all POST
requests to ``CloudAdapter.process()``.

All ``microsoft_agents.*`` imports are lazy (inside ``__init__``) so
the class can be instantiated even if the optional SDK is not installed
— the error surfaces at startup rather than at import time.

Attributes:
    agent: The ai-parrot bot instance.
    config: Configuration for this integration.
    app: The aiohttp application instance.
    route: The primary HTTP route path operators configure in the channel
        (the custom ``endpoint`` when set, else the per-bot default).
    routes: All HTTP route paths registered for this bot.
    m365_agent: The bridge agent wrapping ``agent``.
    adapter: The ``CloudAdapter`` instance.
    logger: Logger scoped to this wrapper.

## Methods

- `async def handle_request(self, request: web.Request) -> web.Response` — Handle an incoming POST request from Copilot Studio / Teams.
- `async def stop(self) -> None` — Gracefully stop the MS Agent SDK wrapper.

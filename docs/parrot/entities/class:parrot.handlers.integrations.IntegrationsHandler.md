---
type: Wiki Entity
title: IntegrationsHandler
id: class:parrot.handlers.integrations.IntegrationsHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Aiohttp class-based view for the OAuth2 integrations API.
---

# IntegrationsHandler

Defined in [`parrot.handlers.integrations`](../summaries/mod:parrot.handlers.integrations.md).

```python
class IntegrationsHandler(BaseView)
```

Aiohttp class-based view for the OAuth2 integrations API.

URL dispatch is performed by URL suffix inspection:
- ``POST .../{provider}/connect`` → start OAuth2 flow.
- ``POST .../{provider}/enable``  → confirm-enable after popup.
- ``DELETE .../{provider}``       → disconnect.

## Methods

- `async def get(self) -> web.Response` — ``GET /api/v1/agents/integrations/{agent_id}`` — list integrations.
- `async def post(self) -> web.Response` — ``POST`` dispatcher — routes to connect-init or confirm-enable.
- `async def delete(self) -> web.Response` — Handle ``DELETE .../integrations/{agent_id}/{provider}``.

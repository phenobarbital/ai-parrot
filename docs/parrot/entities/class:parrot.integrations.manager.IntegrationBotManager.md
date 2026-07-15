---
type: Wiki Entity
title: IntegrationBotManager
id: class:parrot.integrations.manager.IntegrationBotManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Manages bot integrations for exposed agents.
---

# IntegrationBotManager

Defined in [`parrot.integrations.manager`](../summaries/mod:parrot.integrations.manager.md).

```python
class IntegrationBotManager
```

Manages bot integrations for exposed agents.

Supports:
- Telegram
- MS Teams
- WhatsApp
- MS Agent SDK

## Methods

- `async def load_config(self) -> Optional[IntegrationBotConfig]` — Load configuration.
- `async def startup(self, extra_config: Optional[dict]=None) -> None` — Start all configured bots.
- `async def shutdown(self) -> None` — Shutdown bots.

---
type: Wiki Entity
title: TelegramBotManager
id: class:parrot.integrations.telegram.manager.TelegramBotManager
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Manages Telegram bot lifecycle for exposed agents.
---

# TelegramBotManager

Defined in [`parrot.integrations.telegram.manager`](../summaries/mod:parrot.integrations.telegram.manager.md).

```python
class TelegramBotManager
```

Manages Telegram bot lifecycle for exposed agents.

Responsibilities:
- Load configuration from {ENV_DIR}/telegram_bots.yaml
- Get agent instances from BotManager using chatbot_id
- Start aiogram polling in background tasks
- Handle graceful shutdown

Usage:
    manager = TelegramBotManager(bot_manager)
    await manager.startup()
    # ... application runs ...
    await manager.shutdown()

## Methods

- `async def load_config(self) -> Optional[TelegramBotsConfig]` — Load telegram_bots.yaml from ENV_DIR.
- `async def startup(self) -> None` — Start all configured Telegram bots.
- `async def shutdown(self) -> None` — Stop all Telegram bot polling tasks.
- `def get_active_bots(self) -> List[str]` — Get names of currently active bots.
- `def is_running(self, name: str) -> bool` — Check if a specific bot is running.

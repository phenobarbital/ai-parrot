---
type: Wiki Entity
title: TelegramBotsConfig
id: class:parrot.integrations.telegram.models.TelegramBotsConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Root configuration for all Telegram bots.
---

# TelegramBotsConfig

Defined in [`parrot.integrations.telegram.models`](../summaries/mod:parrot.integrations.telegram.models.md).

```python
class TelegramBotsConfig
```

Root configuration for all Telegram bots.

Loaded from {ENV_DIR}/telegram_bots.yaml.

Example YAML structure:
    agents:
      HRAgent:
        chatbot_id: hr_agent
        welcome_message: "Hello! I'm your HR Assistant."
        # bot_token: optional - defaults to HRAGENT_TELEGRAM_TOKEN env var

## Methods

- `def from_dict(cls, data: Dict[str, Any]) -> 'TelegramBotsConfig'` — Create config from dictionary (YAML parsed data).
- `def validate(self) -> List[str]` — Validate configuration and return list of errors.

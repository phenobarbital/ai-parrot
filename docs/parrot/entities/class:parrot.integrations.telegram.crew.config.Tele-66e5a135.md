---
type: Wiki Entity
title: TelegramCrewConfig
id: class:parrot.integrations.telegram.crew.config.TelegramCrewConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Root configuration for a multi-agent crew in a Telegram supergroup.
---

# TelegramCrewConfig

Defined in [`parrot.integrations.telegram.crew.config`](../summaries/mod:parrot.integrations.telegram.crew.config.md).

```python
class TelegramCrewConfig(BaseModel)
```

Root configuration for a multi-agent crew in a Telegram supergroup.

## Methods

- `def cap_message_length(cls, v: int) -> int` — Telegram messages are capped at 4096 characters.
- `def from_yaml(cls, path: str) -> 'TelegramCrewConfig'` — Load configuration from a YAML file with ${ENV_VAR} substitution.

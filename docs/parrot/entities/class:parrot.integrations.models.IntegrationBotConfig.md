---
type: Wiki Entity
title: IntegrationBotConfig
id: class:parrot.integrations.models.IntegrationBotConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Root configuration for all Bot Integrations.
---

# IntegrationBotConfig

Defined in [`parrot.integrations.models`](../summaries/mod:parrot.integrations.models.md).

```python
class IntegrationBotConfig
```

Root configuration for all Bot Integrations.
Supersedes TelegramBotsConfig.

Loaded from {ENV_DIR}/integrations_bots.yaml.

Example YAML structure:
    agents:
      MyTelegramBot:
        kind: telegram
        chatbot_id: hr_agent
        bot_token: "xxx"
      MyTeamsBot:
        kind: msteams
        chatbot_id: sales_agent
        client_id: "xxx"
        client_secret: "yyy"

## Methods

- `def from_dict(cls, data: Dict[str, Any]) -> 'IntegrationBotConfig'` — Create config from dictionary (YAML parsed data).
- `def validate(self) -> List[str]` — Validate configuration and return list of errors.

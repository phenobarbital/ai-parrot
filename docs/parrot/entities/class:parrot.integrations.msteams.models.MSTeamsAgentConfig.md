---
type: Wiki Entity
title: MSTeamsAgentConfig
id: class:parrot.integrations.msteams.models.MSTeamsAgentConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for a single agent exposed via MS Teams.
---

# MSTeamsAgentConfig

Defined in [`parrot.integrations.msteams.models`](../summaries/mod:parrot.integrations.msteams.models.md).

```python
class MSTeamsAgentConfig
```

Configuration for a single agent exposed via MS Teams.

Attributes:
    name: Agent name.
    chatbot_id: ID/name of the bot in BotManager.
    client_id: Microsoft App ID.
    client_secret: Microsoft App Password.
    kind: Integration type (msteams).
    welcome_message: Custom welcome message.
    commands: Custom commands map.
    dialog: Optional dialog configuration.
    voice_config: Optional voice transcription configuration.

## Methods

- `def APP_ID(self) -> str`
- `def APP_PASSWORD(self) -> str`
- `def APP_TYPE(self) -> str`
- `def APP_TENANTID(self) -> Optional[str]`
- `def voice_enabled(self) -> bool` — Check if voice transcription is enabled.
- `def from_dict(cls, name: str, data: Dict[str, Any]) -> 'MSTeamsAgentConfig'` — Create config from dictionary.

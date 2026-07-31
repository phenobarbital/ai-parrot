---
type: Wiki Entity
title: Chatbot
id: class:parrot.bots.chatbot.Chatbot
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Represents an Bot (Chatbot, Agent) in Navigator.
relates_to:
- concept: class:parrot.bots.base.BaseBot
  rel: extends
---

# Chatbot

Defined in [`parrot.bots.chatbot`](../summaries/mod:parrot.bots.chatbot.md).

```python
class Chatbot(BaseBot)
```

Represents an Bot (Chatbot, Agent) in Navigator.

This class is the base for all chatbots and agents in the ai-parrot framework.

This class can be used in two ways:
    1. Manual creation: bot = Chatbot(name="MyBot", tools=[...])
    2. Database loading: bot = Chatbot(name="MyBot", from_database=True)

## Methods

- `async def configure(self, app=None) -> None` — Load configuration for this Chatbot.
- `def import_kb_class(self, kb_path: str)`
- `async def from_manual_config(self) -> None` — Configure the bot manually without database dependency.
- `async def bot_exists(self, name: str=None, uuid: uuid.UUID=None) -> Union[BotModel, bool]` — Check if the Chatbot exists in the Database.
- `async def from_database(self, bot: Union[BotModel, None]=None) -> None` — Load the Chatbot/Agent Configuration from the Database.
- `async def update_database_config(self, **updates) -> bool` — Update bot configuration in database.
- `async def save_to_database(self) -> bool` — Save current bot configuration to database.
- `def get_configuration_summary(self) -> Dict[str, Any]` — Get a summary of the current bot configuration.
- `async def test_configuration(self) -> Dict[str, Any]` — Test the current bot configuration and return status.
- `async def reload_from_database(self) -> bool` — Reload bot configuration from database.

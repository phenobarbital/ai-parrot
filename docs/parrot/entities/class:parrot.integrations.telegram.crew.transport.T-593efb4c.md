---
type: Wiki Entity
title: TelegramCrewTransport
id: class:parrot.integrations.telegram.crew.transport.TelegramCrewTransport
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Orchestrator for a multi-agent crew in a Telegram supergroup.
---

# TelegramCrewTransport

Defined in [`parrot.integrations.telegram.crew.transport`](../summaries/mod:parrot.integrations.telegram.crew.transport.md).

```python
class TelegramCrewTransport
```

Orchestrator for a multi-agent crew in a Telegram supergroup.

Manages the lifecycle of all bots: a coordinator bot and one aiogram
``Bot`` + ``CrewAgentWrapper`` per configured agent.

Args:
    config: The ``TelegramCrewConfig`` describing the crew setup.
    bot_manager: Optional ``BotManager`` instance for retrieving agents
        by ``chatbot_id``.  When provided, ``start()`` will look up
        agent instances automatically.

## Methods

- `def from_config(cls, config: TelegramCrewConfig, bot_manager: Optional[object]=None) -> 'TelegramCrewTransport'` — Construct a transport from a ``TelegramCrewConfig``.
- `async def start(self) -> None` — Start the crew transport.
- `async def stop(self) -> None` — Stop the crew transport gracefully.
- `async def send_message(self, from_username: str, mention: str, text: str, reply_to_message_id: Optional[int]=None) -> None` — Send a text message from a specific agent bot.
- `async def send_document(self, from_username: str, mention: str, file_path: str, caption: str='', reply_to_message_id: Optional[int]=None) -> None` — Send a document from a specific agent bot.
- `def list_online_agents(self) -> List[AgentCard]` — Return a list of currently active (non-offline) agents.
- `def get_wrapper(self, username: str) -> Optional[CrewAgentWrapper]` — Get the ``CrewAgentWrapper`` for a specific agent.

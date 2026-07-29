---
type: Wiki Entity
title: CoordinatorBot
id: class:parrot.integrations.telegram.crew.coordinator.CoordinatorBot
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Non-agent bot that manages the pinned registry message.
---

# CoordinatorBot

Defined in [`parrot.integrations.telegram.crew.coordinator`](../summaries/mod:parrot.integrations.telegram.crew.coordinator.md).

```python
class CoordinatorBot
```

Non-agent bot that manages the pinned registry message.

Args:
    token: Telegram Bot API token for the coordinator bot.
    group_id: Telegram supergroup chat ID.
    registry: The CrewRegistry tracking active agents.
    username: Telegram username of the coordinator bot.

## Methods

- `async def start(self) -> None` — Initialize the coordinator bot and send the initial pinned registry message.
- `async def stop(self) -> None` — Gracefully shut down the coordinator bot.
- `async def on_agent_join(self, card: AgentCard) -> None` — Handle an agent joining the crew.
- `async def on_agent_leave(self, username: str) -> None` — Handle an agent leaving the crew.
- `async def on_agent_status_change(self, username: str, status: str, task: Optional[str]=None) -> None` — Handle an agent status change.
- `async def update_registry(self) -> None` — Render and edit the pinned registry message.

---
type: Wiki Entity
title: CLIDaemonHumanChannel
id: class:parrot.human.channels.cli.CLIDaemonHumanChannel
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: CLI channel for when the agent runs as a daemon/background service.
relates_to:
- concept: class:parrot.human.channels.base.HumanChannel
  rel: extends
---

# CLIDaemonHumanChannel

Defined in [`parrot.human.channels.cli`](../summaries/mod:parrot.human.channels.cli.md).

```python
class CLIDaemonHumanChannel(HumanChannel)
```

CLI channel for when the agent runs as a daemon/background service.

Interactions are published to a Redis queue. A separate CLI companion
process reads them and lets the human respond interactively.

The companion (cli_companion.py) subscribes to the queue, renders
questions using the interactive CLIHumanChannel, and pushes responses
back through Redis.

Args:
    redis: Redis client instance (asyncio-compatible).
    queue_prefix: Redis key prefix for the interaction queues.

## Methods

- `async def register_response_handler(self, callback: Callable[[HumanResponse], Awaitable[None]]) -> None` — Register the manager's response callback.
- `async def send_interaction(self, interaction: HumanInteraction, recipient: str) -> bool` — Publish interaction to Redis queue for the CLI companion.
- `async def send_notification(self, recipient: str, message: str) -> None` — Send notification via Redis queue.
- `async def cancel_interaction(self, interaction_id: str, recipient: str) -> bool` — Publish cancellation event.
- `async def start_response_listener(self, recipient: str) -> None` — Listen for responses from the CLI companion.

---
type: Wiki Entity
title: AgentService
id: class:parrot.services.agent_service.AgentService
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Standalone asyncio runtime for autonomous AI agents.
---

# AgentService

Defined in [`parrot.services.agent_service`](../summaries/mod:parrot.services.agent_service.md).

```python
class AgentService
```

Standalone asyncio runtime for autonomous AI agents.

Composes:
- ``TaskQueue`` for priority-aware task management
- ``WorkerPool`` for bounded concurrent execution
- ``HeartbeatScheduler`` for periodic agent wake-ups
- ``RedisTaskListener`` for IPC with the web server
- ``DeliveryRouter`` for routing results to delivery channels

Agent resolution uses ``BotManager.get_bot()`` — the same mechanism
used by ``TelegramBotManager`` and ``AutonomousOrchestrator``.

Usage::

    from parrot.services import AgentService, AgentServiceConfig

    config = AgentServiceConfig(redis_url="redis://localhost:6379")
    service = AgentService(config, bot_manager)
    await service.start()
    # ... runs until stop() is called
    await service.stop()

## Methods

- `async def start(self) -> None` — Initialize all components and begin processing.
- `async def stop(self) -> None` — Graceful shutdown of all components.
- `async def submit_task(self, task: AgentTask) -> str` — Submit a task for execution.
- `def get_status(self) -> dict` — Return service status for monitoring.

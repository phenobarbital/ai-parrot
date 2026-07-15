---
type: Wiki Entity
title: HeartbeatScheduler
id: class:parrot.services.heartbeat.HeartbeatScheduler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Schedules periodic agent heartbeats via APScheduler.
---

# HeartbeatScheduler

Defined in [`parrot.services.heartbeat`](../summaries/mod:parrot.services.heartbeat.md).

```python
class HeartbeatScheduler
```

Schedules periodic agent heartbeats via APScheduler.

On each trigger, creates an ``AgentTask`` and submits it via the
provided callback (typically ``AgentService.submit_task``).

Requires ``pip install ai-parrot[scheduler]``.

## Methods

- `def register(self, config: HeartbeatConfig) -> Optional[str]` — Register a heartbeat for an agent.
- `def start(self) -> None` — Start the APScheduler.
- `def stop(self) -> None` — Stop the APScheduler.
- `def registered_count(self) -> int` — Number of registered heartbeats.

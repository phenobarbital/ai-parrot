---
type: Wiki Entity
title: HeartbeatConfig
id: class:parrot.autonomous.heartbeat.HeartbeatConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for a single agent's heartbeat loop.
---

# HeartbeatConfig

Defined in [`parrot.autonomous.heartbeat`](../summaries/mod:parrot.autonomous.heartbeat.md).

```python
class HeartbeatConfig(BaseModel)
```

Configuration for a single agent's heartbeat loop.

Attributes:
    agent_name: Name of the registered agent (must match orchestrator
        registry).
    interval: Seconds between ticks. Must be > 0.
    jitter: Maximum random seconds added to ``interval`` on each tick.
        Set to 0 to disable jitter.
    enabled: When False the agent is skipped during
        :meth:`HeartbeatManager.start`.
    max_consecutive_errors: Number of back-to-back tick errors after
        which the agent's loop is paused automatically.
    mission: Default prompt seed forwarded to the act step. May be
        ``None`` if the strategy builds its own prompt.
    execution_timeout: Seconds to wait for execute_agent before timing
        out. Must be > 0.

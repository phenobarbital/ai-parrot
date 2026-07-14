---
type: Wiki Entity
title: HeartbeatState
id: class:parrot.autonomous.heartbeat.HeartbeatState
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Runtime state for a single agent's heartbeat loop.
---

# HeartbeatState

Defined in [`parrot.autonomous.heartbeat`](../summaries/mod:parrot.autonomous.heartbeat.md).

```python
class HeartbeatState(BaseModel)
```

Runtime state for a single agent's heartbeat loop.

All fields are in-memory only; reset on restart.

Attributes:
    agent_name: Identifies the agent this state belongs to.
    running: True while the heartbeat loop task is active.
    tick_count: Total number of completed ticks (sleep + assess cycle).
    action_count: Number of ticks where ``execute_agent`` was called.
    last_tick_at: UTC timestamp of the most recent tick completion.
    last_action_at: UTC timestamp of the most recent act.
    consecutive_errors: Current run of back-to-back errors; reset on
        success.
    last_error: String representation of the most recent caught
        exception, or ``None``.

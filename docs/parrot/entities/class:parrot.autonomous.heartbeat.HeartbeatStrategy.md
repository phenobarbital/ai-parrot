---
type: Wiki Entity
title: HeartbeatStrategy
id: class:parrot.autonomous.heartbeat.HeartbeatStrategy
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pluggable assess step for the heartbeat loop.
---

# HeartbeatStrategy

Defined in [`parrot.autonomous.heartbeat`](../summaries/mod:parrot.autonomous.heartbeat.md).

```python
class HeartbeatStrategy(ABC)
```

Pluggable assess step for the heartbeat loop.

Implementations define the ``wake → assess → maybe act`` decision:

1. :meth:`build_context` — gather signals (queue depth, memory, etc.)
   into a plain dict.
2. :meth:`should_act` — inspect context, return True if the agent
   should act this tick.
3. :meth:`build_prompt` — construct the mission/task string forwarded
   to ``execute_agent``.

## Methods

- `async def build_context(self, cfg: HeartbeatConfig) -> dict[str, Any]` — Build a context dict for the current tick.
- `async def should_act(self, ctx: dict[str, Any]) -> bool` — Decide whether to act this tick.
- `async def build_prompt(self, ctx: dict[str, Any]) -> str` — Construct the task/prompt string for ``execute_agent``.

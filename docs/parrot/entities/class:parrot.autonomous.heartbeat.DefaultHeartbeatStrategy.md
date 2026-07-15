---
type: Wiki Entity
title: DefaultHeartbeatStrategy
id: class:parrot.autonomous.heartbeat.DefaultHeartbeatStrategy
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Acts when ``has_pending_work()`` returns True, or every *N* ticks.
relates_to:
- concept: class:parrot.autonomous.heartbeat.HeartbeatStrategy
  rel: extends
---

# DefaultHeartbeatStrategy

Defined in [`parrot.autonomous.heartbeat`](../summaries/mod:parrot.autonomous.heartbeat.md).

```python
class DefaultHeartbeatStrategy(HeartbeatStrategy)
```

Acts when ``has_pending_work()`` returns True, or every *N* ticks.

This strategy provides two ways to trigger action:

- **Callable gate**: an optional async ``has_pending_work`` callable is
  called on every tick. If it returns True, the agent acts.
- **Fallback cadence**: if ``has_pending_work`` is not provided (or
  returns False), the agent acts every ``act_every_n_ticks`` ticks.

This keeps the heartbeat semantically distinct from a cron job: it
evaluates real signals and only fires when needed.

Args:
    has_pending_work: Optional async callable with no arguments that
        returns ``True`` when the agent should act.
    act_every_n_ticks: Fallback cadence. The agent acts when
        ``tick_count % act_every_n_ticks == 0 and tick_count > 0``.
        Defaults to 10.

## Methods

- `async def build_context(self, cfg: HeartbeatConfig) -> dict[str, Any]` — Return base context with config and current tick_count placeholder.
- `async def should_act(self, ctx: dict[str, Any]) -> bool` — Decide whether to act this tick.
- `async def build_prompt(self, ctx: dict[str, Any]) -> str` — Return the mission from config, or a sensible default string.

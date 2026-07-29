---
type: Wiki Summary
title: parrot.autonomous.heartbeat
id: mod:parrot.autonomous.heartbeat
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Autonomous Agent Heartbeat.
relates_to:
- concept: class:parrot.autonomous.heartbeat.DefaultHeartbeatStrategy
  rel: defines
- concept: class:parrot.autonomous.heartbeat.HeartbeatConfig
  rel: defines
- concept: class:parrot.autonomous.heartbeat.HeartbeatManager
  rel: defines
- concept: class:parrot.autonomous.heartbeat.HeartbeatState
  rel: defines
- concept: class:parrot.autonomous.heartbeat.HeartbeatStrategy
  rel: defines
- concept: mod:parrot.autonomous.orchestrator
  rel: references
---

# `parrot.autonomous.heartbeat`

Autonomous Agent Heartbeat.

Provides a per-agent async heartbeat loop that implements the
``wake → assess → maybe act`` cycle on top of
:class:`~parrot.autonomous.orchestrator.AutonomousOrchestrator`.

Heartbeat is **not** a cron scheduler: the :class:`HeartbeatStrategy`
assess step (``should_act``) decides whether the agent acts on each tick.
Persistence / replay across restarts is handled by the ledger (feature #4).
App wiring (``on_startup`` / ``on_shutdown``) is deferred to feature #6.

Usage example (manual wiring)::

    from parrot.autonomous.heartbeat import (
        HeartbeatConfig,
        HeartbeatManager,
        DefaultHeartbeatStrategy,
    )

    async def has_work():
        return queue.qsize() > 0

    strategy = DefaultHeartbeatStrategy(has_pending_work=has_work)
    manager = HeartbeatManager(orchestrator, strategy=strategy)
    manager.register(HeartbeatConfig(
        agent_name="my-agent",
        interval=60.0,
        jitter=5.0,
        mission="Check inbox and summarise new messages.",
    ))

    # In on_startup:
    await manager.start()

    # In on_shutdown:
    await manager.stop()

## Classes

- **`HeartbeatConfig(BaseModel)`** — Configuration for a single agent's heartbeat loop.
- **`HeartbeatState(BaseModel)`** — Runtime state for a single agent's heartbeat loop.
- **`HeartbeatStrategy(ABC)`** — Pluggable assess step for the heartbeat loop.
- **`DefaultHeartbeatStrategy(HeartbeatStrategy)`** — Acts when ``has_pending_work()`` returns True, or every *N* ticks.
- **`HeartbeatManager`** — Manages per-agent async heartbeat loops.

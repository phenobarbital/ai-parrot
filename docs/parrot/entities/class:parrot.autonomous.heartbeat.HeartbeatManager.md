---
type: Wiki Entity
title: HeartbeatManager
id: class:parrot.autonomous.heartbeat.HeartbeatManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Manages per-agent async heartbeat loops.
---

# HeartbeatManager

Defined in [`parrot.autonomous.heartbeat`](../summaries/mod:parrot.autonomous.heartbeat.md).

```python
class HeartbeatManager
```

Manages per-agent async heartbeat loops.

Each registered agent gets its own ``asyncio.Task`` running
:meth:`_heartbeat_loop`. The loop mirrors the ``_presence_loop``
pattern from
``parrot.autonomous.transport.filesystem.transport._presence_loop``
(transport.py:296).

Observability:
    :meth:`get_state` / :meth:`get_all_states` return in-memory state
    snapshots for each agent. This state is the base for ``/health`` and
    the ledger (feature #4).

Args:
    orchestrator: The :class:`~parrot.autonomous.orchestrator.
        AutonomousOrchestrator` instance used for the act step.
    strategy: Optional :class:`HeartbeatStrategy` to use for all
        agents. Defaults to :class:`DefaultHeartbeatStrategy`.

## Methods

- `def register(self, cfg: HeartbeatConfig) -> None` — Register an agent for heartbeat monitoring.
- `async def start(self) -> None` — Spawn one heartbeat loop task per enabled registered agent.
- `async def stop(self) -> None` — Cancel all running heartbeat tasks and wait for them to finish.
- `def get_state(self, agent_name: str) -> Optional[HeartbeatState]` — Return the current state for the given agent.
- `def get_all_states(self) -> list[HeartbeatState]` — Return a list of state snapshots for all registered agents.

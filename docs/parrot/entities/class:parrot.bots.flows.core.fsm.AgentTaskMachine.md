---
type: Wiki Entity
title: AgentTaskMachine
id: class:parrot.bots.flows.core.fsm.AgentTaskMachine
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Finite State Machine describing the lifecycle of a single node execution.
---

# AgentTaskMachine

Defined in [`parrot.bots.flows.core.fsm`](../summaries/mod:parrot.bots.flows.core.fsm.md).

```python
class AgentTaskMachine(StateMachine)
```

Finite State Machine describing the lifecycle of a single node execution.

States:
    idle: Node created but not yet scheduled.
    ready: All dependencies satisfied; node is queued for execution.
    running: Node is currently executing.
    completed: Node finished successfully (final — no further transitions).
    failed: Node execution failed (NOT final — ``retry`` is allowed).
    blocked: Node cannot proceed (missing dependencies or resources).

Transitions:
    schedule: idle → ready (dependencies met)
    start: ready → running (begin execution)
    succeed: running → completed (successful completion)
    fail: running / ready / idle → failed (error occurred)
    block: idle / ready → blocked (dependencies not met)
    unblock: blocked → ready (dependencies now satisfied)
    retry: failed → ready (retry after failure)

Example::

    fsm = AgentTaskMachine(agent_name="researcher")
    fsm.schedule()   # idle → ready
    fsm.start()      # ready → running
    fsm.succeed()    # running → completed

## Methods

- `def on_enter_running(self) -> None` — Called when entering the ``running`` state.
- `def on_enter_completed(self) -> None` — Called when entering the ``completed`` state.
- `def on_enter_failed(self) -> None` — Called when entering the ``failed`` state.

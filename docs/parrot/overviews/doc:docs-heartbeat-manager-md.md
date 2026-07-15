---
type: Wiki Overview
title: HeartbeatManager — Per-Agent Autonomous Heartbeat Loop
id: doc:docs-heartbeat-manager-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: Unlike a cron scheduler (which fires unconditionally at fixed intervals),
  the
relates_to:
- concept: mod:parrot.autonomous
  rel: mentions
- concept: mod:parrot.autonomous.heartbeat
  rel: mentions
- concept: mod:parrot.autonomous.orchestrator
  rel: mentions
---

# HeartbeatManager — Per-Agent Autonomous Heartbeat Loop

## Overview

`HeartbeatManager` provides a per-agent async heartbeat loop that implements the
**wake -> assess -> maybe act** cycle on top of `AutonomousOrchestrator`.

Unlike a cron scheduler (which fires unconditionally at fixed intervals), the
heartbeat evaluates a **strategy** on every tick and only calls
`execute_agent()` when the strategy decides action is warranted. This is the
"daily review recipes" pattern: the agent wakes up, checks its signals, and
acts only when there is something to do.

```
HeartbeatManager.start()
   |  (one asyncio.Task per agent)
   v
_heartbeat_loop(agent)  --sleep+jitter--.
   |                                     |
   +-- per-agent lock (skip if busy)     | loop
   +-- ctx = strategy.build_context()    |
   +-- if strategy.should_act(ctx):      |
   |     orchestrator.execute_agent(...) -'
   '-- record(HeartbeatState)  --> get_state() (for /health, ledger)
```

Key properties:

- **One asyncio.Task per agent** with independent interval and jitter.
- **Skip if busy**: a per-agent lock prevents overlapping ticks.
- **Backoff on errors**: consecutive failures auto-pause the agent.
- **Clean lifecycle**: `start()` / `stop()` with proper `CancelledError` handling.
- **Pluggable strategy**: inject your own `HeartbeatStrategy` or use the built-in `DefaultHeartbeatStrategy`.
- **Observability**: query per-agent state (tick count, action count, errors, timestamps) at any time.

## Installation

No additional dependencies required. `HeartbeatManager` uses libraries already
in the project:

- `asyncio` -- task management and locks
- `pydantic` -- configuration and state models

## Quick Start

### 1. Minimal Example

```python
import asyncio
from parrot.autonomous.orchestrator import AutonomousOrchestrator
from parrot.autonomous.heartbeat import (
    HeartbeatConfig,
    HeartbeatManager,
)

async def main():
    orchestrator = AutonomousOrchestrator(bot_manager=my_bot_manager)
    await orchestrator.start()

    manager = HeartbeatManager(orchestrator)
    manager.register(HeartbeatConfig(
        agent_name="inbox-reviewer",
        interval=60.0,
        mission="Check inbox and summarise new messages.",
    ))

    await manager.start()

    # ... application runs ...

    await manager.stop()
    await orchestrator.stop()

asyncio.run(main())
```

### 2. With a Work-Detection Callback

```python
import asyncio
from parrot.autonomous.heartbeat import (
    HeartbeatConfig,
    HeartbeatManager,
    DefaultHeartbeatStrategy,
)

queue: asyncio.Queue = asyncio.Queue()

async def has_work():
    return queue.qsize() > 0

strategy = DefaultHeartbeatStrategy(has_pending_work=has_work)
manager = HeartbeatManager(orchestrator, strategy=strategy)

manager.register(HeartbeatConfig(
    agent_name="queue-processor",
    interval=10.0,
    jitter=2.0,
    mission="Process pending items from the work queue.",
))

await manager.start()
```

### 3. Multiple Agents

```python
manager = HeartbeatManager(orchestrator)

# Fast-polling agent for urgent work
manager.register(HeartbeatConfig(
    agent_name="alert-monitor",
    interval=15.0,
    jitter=1.0,
    max_consecutive_errors=3,
    mission="Check for critical alerts and escalate.",
))

# Slow-polling agent for background tasks
manager.register(HeartbeatConfig(
    agent_name="daily-digest",
    interval=3600.0,   # once per hour
    jitter=60.0,
    mission="Compile and send the daily activity digest.",
))

await manager.start()
```

## Configuration

### HeartbeatConfig

`HeartbeatConfig` is an immutable (frozen) Pydantic model that defines a single
agent's heartbeat behavior. Once created, its fields cannot be changed -- to
update configuration, call `register()` again with a new config.

| Field | Type | Default | Constraint | Description |
|---|---|---|---|---|
| `agent_name` | `str` | (required) | -- | Name of the agent. Must match the orchestrator's registry. |
| `interval` | `float` | `60.0` | `> 0` | Seconds between ticks. |
| `jitter` | `float` | `0.0` | `>= 0` | Maximum random seconds added to `interval` each tick. Set to `0` to disable. |
| `enabled` | `bool` | `True` | -- | When `False`, the agent is skipped during `start()`. |
| `max_consecutive_errors` | `int` | `5` | `>= 1` | Back-to-back tick errors before the agent's loop auto-pauses. |
| `mission` | `str \| None` | `None` | -- | Default prompt seed forwarded to `execute_agent`. May be `None` if the strategy builds its own prompt. |
| `execution_timeout` | `float` | `30.0` | `> 0` | Seconds to wait for `execute_agent` before timing out. A timeout counts as an error toward `max_consecutive_errors`. |

**Example:**

```python
from parrot.autonomous.heartbeat import HeartbeatConfig

config = HeartbeatConfig(
    agent_name="my-agent",
    interval=30.0,
    jitter=5.0,
    max_consecutive_errors=3,
    execution_timeout=60.0,
    mission="Review pending tickets and prioritize urgent items.",
)

# HeartbeatConfig is frozen -- this raises an error:
# config.interval = 10.0  # ValidationError!
```

### HeartbeatState

`HeartbeatState` is a mutable Pydantic model that tracks the runtime state of a
single agent's heartbeat loop. All fields are in-memory only and reset on restart.

| Field | Type | Default | Description |
|---|---|---|---|
| `agent_name` | `str` | (required) | Identifies the agent this state belongs to. |
| `running` | `bool` | `False` | `True` while the heartbeat loop task is active. |
| `tick_count` | `int` | `0` | Total number of completed ticks (sleep + assess cycle). |
| `action_count` | `int` | `0` | Number of ticks where `execute_agent` was called. |
| `last_tick_at` | `datetime \| None` | `None` | UTC timestamp of the most recent tick completion. |
| `last_action_at` | `datetime \| None` | `None` | UTC timestamp of the most recent act. |
| `consecutive_errors` | `int` | `0` | Current run of back-to-back errors; resets to 0 on success. |
| `last_error` | `str \| None` | `None` | String representation of the most recent exception, or `None`. |

## HeartbeatManager API

### Constructor

```python
HeartbeatManager(
    orchestrator: AutonomousOrchestrator,
    *,
    strategy: HeartbeatStrategy | None = None,
)
```

| Parameter | Description |
|---|---|
| `orchestrator` | The `AutonomousOrchestrator` instance used for the act step (`execute_agent`). |
| `strategy` | Optional strategy for all agents. Defaults to `DefaultHeartbeatStrategy()`. |

### Methods

#### `register(cfg: HeartbeatConfig) -> None`

Register an agent for heartbeat monitoring. Calling `register` on an
already-registered agent replaces the config and resets state.

If the manager is already running and the agent is enabled, a heartbeat loop
task is spawned immediately -- dynamically-added agents do not require a
restart.

```python
manager.register(HeartbeatConfig(
    agent_name="new-agent",
    interval=30.0,
    mission="Handle new work items.",
))
# If manager.start() was already called, this agent starts ticking immediately.
```

#### `async start() -> None`

Spawn one heartbeat loop task per enabled registered agent. Safe to call
multiple times; already-running tasks are not duplicated.

```python
await manager.start()
```

#### `async stop() -> None`

Cancel all running heartbeat tasks and wait for them to finish. Handles
`CancelledError` internally; does not raise. After stopping, the manager can
be restarted with `start()`.

```python
await manager.stop()
```

#### `get_state(agent_name: str) -> HeartbeatState | None`

Return the current state for the given agent, or `None` if the agent is not
registered.

```python
state = manager.get_state("inbox-reviewer")
if state:
    print(f"Ticks: {state.tick_count}, Actions: {state.action_count}")
    print(f"Running: {state.running}")
    if state.last_error:
        print(f"Last error: {state.last_error}")
```

#### `get_all_states() -> list[HeartbeatState]`

Return a list of state snapshots for all registered agents. Returns copies of
each state, so callers cannot accidentally mutate internal manager state.

```python
for state in manager.get_all_states():
    print(f"{state.agent_name}: {state.tick_count} ticks, {state.action_count} actions")
```

## Strategy System

The heartbeat's **assess** step is fully pluggable via the `HeartbeatStrategy` ABC.
A strategy decides three things on each tick:

1. **`build_context(cfg)`** -- gather signals (queue depth, memory state, etc.) into a context dict.
2. **`should_act(ctx)`** -- inspect the context and return `True` if the agent should act.
3. **`build_prompt(ctx)`** -- construct the mission/prompt string forwarded to `execute_agent`.

### DefaultHeartbeatStrategy

The built-in strategy provides two trigger mechanisms:

- **Callable gate**: an optional async `has_pending_work` callable is called on
  every tick. If it returns `True`, the agent acts.
- **Fallback cadence**: if `has_pending_work` is not provided (or returns
  `False`), the agent acts every `act_every_n_ticks` ticks (default: 10).

```python
from parrot.autonomous.heartbeat import DefaultHeartbeatStrategy

# Strategy with a work-detection callback
strategy = DefaultHeartbeatStrategy(
    has_pending_work=my_async_check,
    act_every_n_ticks=20,   # fallback: act every 20th tick even without work
)

manager = HeartbeatManager(orchestrator, strategy=strategy)
```

If `has_pending_work` raises an exception, it is logged at warning level and the
fallback cadence is checked instead.

### Custom Strategy

Implement the `HeartbeatStrategy` ABC to create your own decision logic:

```python
from parrot.autonomous.heartbeat import HeartbeatStrategy, HeartbeatConfig
from typing import Any

class MemoryPressureStrategy(HeartbeatStrategy):
    """Act only when the system is under memory pressure."""

    def __init__(self, threshold_mb: float = 500.0):
        self._threshold_mb = threshold_mb

    async def build_context(self, cfg: HeartbeatConfig) -> dict[str, Any]:
        import psutil
        mem = psutil.virtual_memory()
        return {
            "config": cfg,
            "tick_count": 0,  # enriched by HeartbeatManager
            "available_mb": mem.available / (1024 * 1024),
        }

    async def should_act(self, ctx: dict[str, Any]) -> bool:
        return ctx["available_mb"] < self._threshold_mb

    async def build_prompt(self, ctx: dict[str, Any]) -> str:
        available = ctx["available_mb"]
        return (
            f"System memory is low ({available:.0f} MB available). "
            f"Review running processes and free resources."
        )

# Use it:
manager = HeartbeatManager(
    orchestrator,
    strategy=MemoryPressureStrategy(threshold_mb=256.0),
)
```

## Lifecycle & Error Handling

### Tick Lifecycle

Each tick follows this sequence:

```
sleep(interval + random(0, jitter))
    |
    v
lock.locked()? ---- yes ----> skip tick (log debug)
    |                              |
    no                             v
    |                         tick_count += 1
    v
acquire per-agent lock
    |
    v
build_context(cfg)
    |
    v
should_act(ctx)? --- no ----> release lock, tick_count += 1
    |
    yes
    |
    v
build_prompt(ctx)
    |
    v
await wait_for(execute_agent(...), timeout)
    |
    +-- success ----> action_count += 1, consecutive_errors = 0
    |
    +-- error ------> consecutive_errors += 1
    |                     |
    |                     v
    |                 >= max_consecutive_errors? --- yes ----> PAUSE (loop exits)
    |                     |
    |                     no ----> continue loop
    v
release lock, tick_count += 1
```

### Error Backoff

When a tick raises an exception (or times out), the `consecutive_errors`
counter increments. On success, it resets to 0.

When `consecutive_errors` reaches `max_consecutive_errors`, the agent's loop
exits automatically (the agent is "paused"). The agent can be restarted by
calling `start()` again -- error counters are reset at the beginning of each
loop start.

```python
config = HeartbeatConfig(
    agent_name="fragile-agent",
    interval=10.0,
    max_consecutive_errors=3,   # pause after 3 back-to-back errors
    execution_timeout=15.0,     # timeout counts as an error
    mission="Process work items.",
)
```

### Execution Timeout

Each `execute_agent` call is wrapped in `asyncio.wait_for()` with the
configured `execution_timeout`. If the orchestrator takes longer than this,
`asyncio.TimeoutError` is raised, logged at warning level, and counted toward
`consecutive_errors`.

### CancelledError Handling

`stop()` cancels all tasks via `task.cancel()`. Inside each loop,
`asyncio.CancelledError` is always re-raised (never swallowed), ensuring
clean shutdown. `stop()` then gathers all tasks with `return_exceptions=True`
and logs any unexpected exceptions.

## Integration with AutonomousOrchestrator

The `HeartbeatManager` delegates all agent execution to
`AutonomousOrchestrator.execute_agent()`. It does **not** re-implement agent
execution, tool calling, or session management.

```python
from parrot.autonomous.orchestrator import AutonomousOrchestrator
from parrot.autonomous.heartbeat import HeartbeatConfig, HeartbeatManager

# 1. Create and start the orchestrator (as usual)
orchestrator = AutonomousOrchestrator(
    bot_manager=my_bot_manager,
    agent_registry=my_registry,
)
await orchestrator.start()

# 2. Create the heartbeat manager ON TOP of the orchestrator
manager = HeartbeatManager(orchestrator)

# 3. Register agents (must be registered in the orchestrator's agent registry too)
manager.register(HeartbeatConfig(
    agent_name="my-agent",      # must match orchestrator's registry
    interval=60.0,
    mission="Perform periodic review.",
))

# 4. Start heartbeats
await manager.start()

# 5. Application runs... heartbeats tick in the background

# 6. Shutdown (order matters: stop heartbeats first, then orchestrator)
await manager.stop()
await orchestrator.stop()
```

### Coexistence with AgentSchedulerManager

The heartbeat system is **complementary** to `AgentSchedulerManager` (cron), not
a replacement:

| Feature | HeartbeatManager | AgentSchedulerManager |
|---|---|---|
| **Trigger** | Strategy-driven (assess step) | Fixed schedule (cron/interval) |
| **When to use** | Agent should wake up, evaluate signals, and decide | Agent should run at exact times regardless of state |
| **Pattern** | wake -> assess -> maybe act | fire-and-forget |
| **Overlap** | Per-agent lock prevents overlapping ticks | Depends on APScheduler config |
| **Examples** | Inbox review, alert monitoring, queue processing | Daily reports, weekly backups, hourly syncs |

Both can run simultaneously on the same `AutonomousOrchestrator`. They do not
interfere with each other.

## Application Wiring

### With aiohttp

```python
from aiohttp import web
from parrot.autonomous.orchestrator import AutonomousOrchestrator
from parrot.autonomous.heartbeat import HeartbeatConfig, HeartbeatManager

heartbeat_manager: HeartbeatManager | None = None

async def on_startup(app: web.Application):
    global heartbeat_manager
    orchestrator = app["orchestrator"]

    heartbeat_manager = HeartbeatManager(orchestrator)

    # Register agents from config
    for agent_cfg in app["heartbeat_agents"]:
        heartbeat_manager.register(agent_cfg)

    await heartbeat_manager.start()
    app["heartbeat_manager"] = heartbeat_manager

async def on_shutdown(app: web.Application):
    if heartbeat_manager:
        await heartbeat_manager.stop()

app = web.Application()
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)
```

### Health Check Endpoint

```python
async def health_handler(request: web.Request) -> web.Response:
    manager: HeartbeatManager = request.app["heartbeat_manager"]
    states = manager.get_all_states()

    agents = []
    for state in states:
        agents.append({
            "name": state.agent_name,
            "running": state.running,
            "ticks": state.tick_count,
            "actions": state.action_count,
            "last_tick": state.last_tick_at.isoformat() if state.last_tick_at else None,
            "last_action": state.last_action_at.isoformat() if state.last_action_at else None,
            "consecutive_errors": state.consecutive_errors,
            "last_error": state.last_error,
        })

    all_healthy = all(s.running for s in states) if states else True
    return web.json_response({
        "status": "healthy" if all_healthy else "degraded",
        "agents": agents,
    })
```

## Dynamic Registration

Agents can be registered while the manager is already running. The new agent's
heartbeat loop starts immediately without requiring a restart:

```python
await manager.start()

# ... later, in response to an event or API call ...

manager.register(HeartbeatConfig(
    agent_name="dynamic-agent",
    interval=30.0,
    mission="Handle the new workload.",
))
# "dynamic-agent" is already ticking.
```

Re-registering an existing agent replaces its config and resets its state.

## Observability

### Querying State

```python
# Single agent
state = manager.get_state("inbox-reviewer")
if state and state.running:
    print(f"Agent is healthy: {state.tick_count} ticks, {state.consecutive_errors} errors")

# All agents (returns snapshots -- safe to store/serialize)
for state in manager.get_all_states():
    efficiency = (state.action_count / state.tick_count * 100) if state.tick_count > 0 else 0
    print(f"{state.agent_name}: {efficiency:.1f}% action rate")
```

### Logging

The manager logs at several levels:

| Level | What |
|---|---|
| `INFO` | Agent start/stop events |
| `DEBUG` | Tick details, skip-when-busy events, action results |
| `WARNING` | Tick errors, timeouts, `has_pending_work` exceptions |
| `ERROR` | Agent paused after `max_consecutive_errors` |

Configure logging to see heartbeat activity:

```python
import logging
logging.getLogger("parrot.autonomous.heartbeat").setLevel(logging.DEBUG)
```

## Imports

All public symbols are available from both the heartbeat module directly and
the `parrot.autonomous` namespace:

```python
# Direct import
from parrot.autonomous.heartbeat import (
    HeartbeatConfig,
    HeartbeatState,
    HeartbeatStrategy,
    DefaultHeartbeatStrategy,
    HeartbeatManager,
)

# Namespace import (lazy-loaded)
from parrot.autonomous import (
    HeartbeatConfig,
    HeartbeatState,
    HeartbeatStrategy,
    DefaultHeartbeatStrategy,
    HeartbeatManager,
)
```

## FAQ

**Q: How is this different from a cron job?**

A cron job fires unconditionally at a fixed schedule. The heartbeat evaluates a
strategy on every tick and only acts when the strategy says there is work to do.
This prevents wasted agent invocations and lets you express conditions like
"act when the queue has items" or "act when memory is low."

**Q: What happens if `execute_agent` takes longer than the interval?**

The per-agent lock prevents overlapping ticks. If the previous tick is still
running when the next interval elapses, the new tick is skipped (logged at
debug level). The agent does not accumulate a backlog of ticks.

**Q: Can I use different strategies for different agents?**

The current design uses a single strategy for all agents in a `HeartbeatManager`.
To use different strategies, create multiple `HeartbeatManager` instances:

```python
urgent_manager = HeartbeatManager(orchestrator, strategy=UrgentStrategy())
background_manager = HeartbeatManager(orchestrator, strategy=BackgroundStrategy())
```

**Q: Is state persisted across restarts?**

No. `HeartbeatState` is in-memory only and resets when the process restarts.
Persistent state tracking is handled by the ledger system (separate feature).

**Q: Can a paused agent be restarted?**

Yes. Call `start()` again after the agent pauses (due to `max_consecutive_errors`).
Error counters are reset at the beginning of each loop start, so the agent
begins fresh.

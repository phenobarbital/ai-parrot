# AgentService — Standalone Runtime for Autonomous Agents

## Overview

`AgentService` is a standalone asyncio runtime that executes AI agents autonomously, outside the web request cycle. It provides:

- **Priority task queue** with Redis persistence for crash recovery
- **Bounded worker pool** for concurrent agent execution
- **Heartbeat scheduling** via APScheduler (cron and interval triggers)
- **Redis Streams IPC** for receiving tasks from external processes
- **Result delivery** to LOG, Webhook, Telegram, MS Teams, or Email

Agent resolution uses `BotManager.get_bot()` — the same mechanism used by `TelegramBotManager` and the `AutonomyOrchestrator`.

## Architecture

```
                          ┌──────────────────────────────────┐
                          │         AgentService             │
                          │                                  │
  ┌──────────────┐        │  ┌────────────┐  ┌───────────┐  │
  │ Redis Stream │───────►│  │ TaskQueue   │──│WorkerPool │  │
  │ (IPC)        │        │  │ (priority)  │  │ (bounded) │  │
  └──────────────┘        │  └────────────┘  └─────┬─────┘  │
                          │       ▲                 │        │
  ┌──────────────┐        │       │          agent.ask()     │
  │ Heartbeat    │────────│───────┘                 │        │
  │ (APScheduler)│        │                  ┌──────▼──────┐ │
  └──────────────┘        │                  │ BotManager  │ │
                          │                  │ .get_bot()  │ │
  ┌──────────────┐        │                  └──────┬──────┘ │
  │ Client       │───────►│                         │        │
  │ (submit_task)│        │                  ┌──────▼──────┐ │
  └──────────────┘        │                  │ Delivery    │ │
                          │                  │ Router      │ │
                          │                  └─────────────┘ │
                          └──────────────────────────────────┘
```

## Installation

No additional dependencies required. `AgentService` uses libraries already in the project:

- `redis.asyncio` — Redis connections and Streams
- `apscheduler` 3.11.2 — Cron/interval scheduling
- `aiohttp` — HTTP delivery (webhook)
- `pydantic` — Configuration and task models

## Quick Start

### 1. Minimal Example

```python
import asyncio
from parrot.manager import BotManager
from parrot.services import AgentService, AgentServiceConfig, AgentTask

async def main():
    bot_manager = BotManager()
    config = AgentServiceConfig(redis_url="redis://localhost:6379")

    service = AgentService(config, bot_manager)
    await service.start()

    # Submit a task
    task = AgentTask(agent_name="MyAgent", prompt="Hello!")
    await service.submit_task(task)

    # Run until interrupted
    await asyncio.Event().wait()

asyncio.run(main())
```

### 2. Using the Sample Script

```bash
source .venv/bin/activate
python examples/start_agent_service.py

# Or with custom Redis URL:
REDIS_URL=redis://myhost:6379 python examples/start_agent_service.py
```

## Configuration

### AgentServiceConfig

```python
from parrot.services import AgentServiceConfig

config = AgentServiceConfig(
    # Redis connection
    redis_url="redis://localhost:6379",
    redis_db=0,

    # Worker pool
    max_workers=10,                  # Max concurrent agent executions

    # Redis Streams (IPC)
    task_stream="parrot:agent_tasks",
    result_stream="parrot:agent_results",
    consumer_group="agent_service",
    consumer_name=None,              # Auto-generated if not set

    # Timeouts
    task_timeout_seconds=300,        # Per-task execution timeout
    shutdown_timeout_seconds=30,     # Graceful shutdown timeout

    # Heartbeats (see Heartbeat section)
    heartbeats=[],
)
```

### AgentTask

```python
from parrot.services import AgentTask, TaskPriority, DeliveryConfig, DeliveryChannel

task = AgentTask(
    agent_name="ResearchBot",       # Agent registered in BotManager
    prompt="Summarize latest news",
    priority=TaskPriority.HIGH,      # CRITICAL=1, HIGH=3, NORMAL=5, LOW=7, BACKGROUND=9

    # Optional execution context
    user_id="user_123",
    session_id="sess_abc",
    method_name=None,                # Custom method (default: agent.ask())

    # Delivery configuration
    delivery=DeliveryConfig(
        channel=DeliveryChannel.WEBHOOK,
        webhook_url="https://example.com/callback",
    ),

    # Arbitrary metadata
    metadata={"source": "cron_job", "department": "engineering"},
)
```

### Task Priority

Lower value = higher priority. Tasks with equal priority maintain FIFO order.

| Priority | Value | Use Case |
|----------|-------|----------|
| `CRITICAL` | 1 | Urgent alerts, incident response |
| `HIGH` | 3 | User-initiated requests |
| `NORMAL` | 5 | Standard tasks (default) |
| `LOW` | 7 | Heartbeat checks, background sync |
| `BACKGROUND` | 9 | Batch processing, maintenance |

## Delivery Channels

### LOG (Default)

Logs the result — useful for heartbeats and debugging.

```python
delivery = DeliveryConfig(channel=DeliveryChannel.LOG)
```

### Webhook

POSTs a JSON payload to a callback URL.

```python
delivery = DeliveryConfig(
    channel=DeliveryChannel.WEBHOOK,
    webhook_url="https://api.example.com/agent-results",
)
```

**Webhook payload:**
```json
{
  "task_id": "abc123...",
  "agent_name": "MyAgent",
  "success": true,
  "output": "Agent response text...",
  "error": null,
  "execution_time_ms": 1234.5,
  "metadata": {}
}
```

### Telegram

Sends the result as a Telegram message.

```python
delivery = DeliveryConfig(
    channel=DeliveryChannel.TELEGRAM,
    telegram_bot_token="123456:ABC-DEF...",
    telegram_chat_id=987654321,
)
```

### MS Teams

Sends an Adaptive Card to an incoming webhook.

```python
delivery = DeliveryConfig(
    channel=DeliveryChannel.TEAMS,
    teams_webhook_url="https://outlook.office.com/webhook/...",
)
```

### Email

Sends via the `async-notify` email provider.

```python
delivery = DeliveryConfig(
    channel=DeliveryChannel.EMAIL,
    email_recipients=["team@example.com", "manager@example.com"],
    email_subject="Daily Agent Report",
)
```

### Redis Stream

Publishes the result to the response stream for IPC consumption.

```python
delivery = DeliveryConfig(channel=DeliveryChannel.REDIS_STREAM)
```

> **Note:** Results are *always* published to the Redis response stream regardless of the delivery channel. This ensures the `AgentServiceClient` can always retrieve results.

## Heartbeat Scheduling

Register periodic agent wake-ups that fire automatically:

```python
from parrot.services import HeartbeatConfig, DeliveryConfig, DeliveryChannel

config = AgentServiceConfig(
    redis_url="redis://localhost:6379",
    heartbeats=[
        # Every 5 minutes
        HeartbeatConfig(
            agent_name="HealthChecker",
            interval_seconds=300,
            prompt_template="Check system health and report anomalies.",
            delivery=DeliveryConfig(channel=DeliveryChannel.LOG),
        ),

        # Daily at 9 AM
        HeartbeatConfig(
            agent_name="ReportAgent",
            cron_expression="0 9 * * *",
            prompt_template="Generate the daily summary report.",
            delivery=DeliveryConfig(
                channel=DeliveryChannel.EMAIL,
                email_recipients=["team@example.com"],
            ),
        ),

        # Every Monday at 8 AM
        HeartbeatConfig(
            agent_name="WeeklyDigest",
            cron_expression="0 8 * * 1",
            prompt_template="Compile the weekly metrics digest.",
            delivery=DeliveryConfig(
                channel=DeliveryChannel.TEAMS,
                teams_webhook_url="https://outlook.office.com/webhook/...",
            ),
        ),

        # Disabled heartbeat (skipped at startup)
        HeartbeatConfig(
            agent_name="ExperimentalBot",
            interval_seconds=60,
            enabled=False,
        ),
    ],
)
```

Heartbeat tasks are created with `TaskPriority.LOW` so they don't preempt user-initiated work.

## IPC via Redis Streams

### Submitting Tasks from External Processes

Use `AgentServiceClient` to submit tasks from a web server, CLI, or any other process:

```python
from parrot.services import AgentServiceClient, AgentTask

async with AgentServiceClient("redis://localhost:6379") as client:
    # Fire and forget
    task_id = await client.submit_task(
        AgentTask(agent_name="MyAgent", prompt="Analyze this data")
    )

    # Submit and wait for result
    result = await client.submit_and_wait(
        AgentTask(agent_name="MyAgent", prompt="Quick question"),
        timeout=30,
    )
    if result and result.success:
        print(result.output)
```

### Integration with aiohttp Web Server

```python
from aiohttp import web
from parrot.services import AgentServiceClient, AgentTask, DeliveryConfig, DeliveryChannel

client = AgentServiceClient("redis://localhost:6379")

async def handle_async_task(request):
    """Submit an agent task and return immediately."""
    data = await request.json()

    task = AgentTask(
        agent_name=data["agent"],
        prompt=data["prompt"],
        delivery=DeliveryConfig(
            channel=DeliveryChannel.WEBHOOK,
            webhook_url=data.get("callback_url"),
        ),
    )

    await client.connect()
    task_id = await client.submit_task(task)
    return web.json_response({"task_id": task_id, "status": "queued"})
```

## Monitoring

```python
# Get runtime status
status = service.get_status()
print(status)
# {
#   "running": True,
#   "queue_size": 3,
#   "active_workers": 2,
#   "available_slots": 8,
#   "heartbeats": 3
# }
```

## Lifecycle Management

### Graceful Shutdown

`AgentService` handles shutdown in order:

1. Stop heartbeat scheduler (no new heartbeats)
2. Stop Redis listener (no new IPC tasks)
3. Cancel background loops
4. Drain worker pool (wait for active tasks, cancel pending after timeout)
5. Close delivery HTTP sessions
6. Close Redis connection

```python
import signal

service = AgentService(config, bot_manager)
await service.start()

# Register signal handlers
loop = asyncio.get_running_loop()
for sig in (signal.SIGINT, signal.SIGTERM):
    loop.add_signal_handler(sig, lambda: asyncio.create_task(service.stop()))
```

### Crash Recovery

On startup, `TaskQueue.recover()` scans the Redis sorted set for persisted tasks and re-enqueues them. This ensures tasks submitted before a crash are not lost.

## Module Reference

| Module | Class | Purpose |
|--------|-------|---------|
| `parrot.services` | `AgentService` | Main runtime orchestrator |
| `parrot.services` | `AgentServiceClient` | Redis Streams client for submitting tasks |
| `parrot.services` | `AgentServiceConfig` | Service configuration |
| `parrot.services` | `AgentTask` | Task definition with priority and delivery |
| `parrot.services` | `TaskResult` | Execution result |
| `parrot.services` | `TaskPriority` | Priority levels enum |
| `parrot.services` | `TaskStatus` | Task lifecycle states |
| `parrot.services` | `DeliveryChannel` | Delivery channel enum |
| `parrot.services` | `DeliveryConfig` | Channel-specific delivery parameters |
| `parrot.services` | `HeartbeatConfig` | Periodic agent wake-up configuration |

## Testing

```bash
source .venv/bin/activate
python -m pytest tests/test_agent_service.py -v
```

Tests cover models, priority queue ordering, worker pool concurrency, heartbeat registration, delivery routing, service lifecycle, and client operations — all with mocked Redis (no external services required).

## Troubleshooting

### Agent Not Found

```
ValueError: Agent 'MyAgent' not found in BotManager
```

Ensure the agent is registered via YAML config or `BotManager.add_bot()` before submitting tasks. The service uses the same `BotManager.get_bot()` resolution as `TelegramBotManager`.

### Redis Connection Refused

```
ConnectionRefusedError: [Errno 111] Connection refused
```

Verify Redis is running at the configured URL. The service requires Redis 5.0+ for Streams support.

### Task Timeout

```
asyncio.TimeoutError
```

Increase `task_timeout_seconds` in `AgentServiceConfig` (default: 300s), or optimize the agent's processing.

### Heartbeat Not Firing

Check that `enabled=True` on the `HeartbeatConfig` and that either `cron_expression` or `interval_seconds` is set (not both empty).

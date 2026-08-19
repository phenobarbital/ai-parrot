# CLI Agent Daemon Guide

> **Package**: `ai-parrot-integrations[agentd]`
> **Feature**: FEAT-422
> **API Reference**: [docs/agentd.md](../agentd.md)

This guide walks you through running any AI-Parrot agent as a
long-lived CLI daemon — from creating the agent, configuring and
serving the daemon, interacting with it, scheduling recurring jobs,
exposing it to external LLMs over MCP, deploying it as a system
service, and stopping it cleanly.

Every example uses the `FirefliesObsidianAgent` (FEAT-392) as a
concrete, real-world scenario: a daemon that syncs Fireflies.ai
meeting transcripts into a local Obsidian vault on a schedule.

---

## Table of Contents

1. [When to use agentd](#1-when-to-use-agentd)
2. [Creating an agent for the daemon](#2-creating-an-agent-for-the-daemon)
3. [Configuring the daemon](#3-configuring-the-daemon)
4. [Serving the daemon](#4-serving-the-daemon)
5. [Interacting with a running daemon](#5-interacting-with-a-running-daemon)
6. [Scheduling recurring tasks](#6-scheduling-recurring-tasks)
7. [Exposing the daemon over MCP](#7-exposing-the-daemon-over-mcp)
8. [Deploying as a system service](#8-deploying-as-a-system-service)
9. [Stopping the daemon](#9-stopping-the-daemon)

---

## 1. When to use agentd

AI-Parrot offers three ways to run an agent. Pick the one that fits:

| Option | Agents | Lifetime | Client/server split |
|--------|--------|----------|---------------------|
| **Full aiohttp server** | Many | Always on | HTTP API |
| **`parrot agent` REPL** | One | Dies with the terminal | None — in-process |
| **agentd daemon** | One | Long-lived (systemd, supervisord) | UDS socket — consoles, scripts, and MCP clients attach/detach independently |

Choose **agentd** when you want a single, always-available agent that
survives terminal disconnects and that you (or external LLMs) can
reach from any terminal, cron job, or MCP client.

---

## 2. Creating an agent for the daemon

Any class that inherits from `Agent` (or `BasicAgent`) works
out-of-the-box — agentd does not require a special base class. The
daemon resolves your agent from a Python import path
(`module.path:ClassName`) and instantiates it for you.

### 2.1 Minimal agent

```python
# my_agents/hello.py
from parrot.bots.agent import BasicAgent

class HelloAgent(BasicAgent):
    """A minimal agent that answers questions."""

    def __init__(self, **kwargs):
        super().__init__(name="hello", **kwargs)
```

That's it. This agent is already servable:

```bash
parrot serve my_agents.hello:HelloAgent --name hello
```

### 2.2 Agent with custom initialization

When your agent needs parameters (API keys, paths, configuration),
pass them as `kwargs` in the YAML config or via an async factory:

```python
# my_agents/fireflies.py
from parrot.agents.obsidian import FirefliesObsidianAgent

# Option A: agentd instantiates the class with kwargs from the YAML.
# Nothing else needed — the class IS the target.

# Option B: async factory — full control over construction.
async def create_agent():
    """agentd calls this, awaits the coroutine, and uses the result."""
    agent = FirefliesObsidianAgent(
        name="FirefliesObsidianSync",
        vault_path="~/vaults/notes",
        meetings_folder="meetings",
    )
    # Any async setup you need before the daemon starts accepting
    # connections goes here.
    return agent
```

agentd's `resolve_agent()` detects what you hand it:

| Target resolves to | What agentd does |
|---------------------|-----------------|
| A **class** | Instantiates with `kwargs` from config |
| A **callable** (sync/async factory) | Calls it with `kwargs`, awaits if async |
| An **instance** | Uses it as-is |

If the resolved agent has an async `configure()` method, agentd awaits
it automatically before opening the socket.

### 2.3 Exposing agent methods

By default the daemon exposes every public method (no leading
underscore) via the `agent.invoke` RPC. To restrict which methods
external clients can call, set `exposed_methods` in your config:

```yaml
exposed_methods:
  - sync_fireflies_transcripts
  - summarize_transcript
```

When `exposed_methods` is non-empty it acts as an **allowlist** — only
those methods are callable via `/invoke` in the console and via the MCP
`invoke_method` tool. When it's empty (`[]`), `invoke_method` is never
registered over MCP at all (defense in depth).

---

## 3. Configuring the daemon

### 3.1 YAML config (recommended)

Create a YAML file describing your daemon. This is the recommended
approach for anything beyond a quick test:

```yaml
# fireflies-daemon.yaml
name: fireflies-sync

agent:
  target: "parrot.agents.obsidian:FirefliesObsidianAgent"
  kwargs:
    name: "FirefliesObsidianSync"
    vault_path: "~/vaults/notes"
    meetings_folder: "meetings"

exposed_methods:
  - sync_fireflies_transcripts
  - summarize_transcript

scheduler:
  enabled: true
  # Uncomment for persistent schedules that survive restarts:
  # dsn: "postgresql://user:pass@localhost:5432/parrot"
  # redis: true

log_level: INFO
```

### 3.2 Direct target (no YAML)

For a quick spin you can skip the YAML entirely:

```bash
parrot serve parrot.agents.obsidian:FirefliesObsidianAgent \
    --name fireflies-sync \
    --log-level DEBUG
```

`--name` is **required** when no YAML is involved (it becomes the
socket filename and service identity).

### 3.3 Async factory as target

Point the target at a factory function instead of a class:

```yaml
agent:
  target: "my_agents.fireflies:create_agent"
  # kwargs are passed to the factory, not the class
  kwargs: {}
```

Or from the CLI:

```bash
parrot serve my_agents.fireflies:create_agent --name fireflies-sync
```

### 3.4 Configuration reference (quick)

| Field | Default | Notes |
|-------|---------|-------|
| `name` | *(required)* | Socket filename, unit name, log identity |
| `agent.target` | *(required)* | `"module:attr"` — class, instance, or factory |
| `agent.kwargs` | `{}` | Passed to class/factory |
| `socket` | `null` | Explicit UDS path; `null` → `$XDG_RUNTIME_DIR/parrot/<name>.sock` |
| `exposed_methods` | `[]` | Method allowlist; empty = `invoke_method` not registered over MCP |
| `scheduler.enabled` | `true` | `false` skips scheduler bootstrap entirely |
| `scheduler.dsn` | `null` | Postgres DSN for persistent schedules |
| `scheduler.redis` | `false` | Attach a Redis-backed jobstore |
| `log_level` | `"INFO"` | Standard Python level name |
| `shutdown_grace` | `30.0` | Seconds to wait for graceful shutdown |

CLI overrides (`--name`, `--socket`, `--dsn`, `--redis`/`--no-redis`,
`--log-level`) are applied on top of the YAML values.

See [docs/agentd.md](../agentd.md) for the full field reference.

---

## 4. Serving the daemon

### 4.1 Foreground (development)

```bash
# From YAML:
parrot serve fireflies-daemon.yaml

# From target:
parrot serve parrot.agents.obsidian:FirefliesObsidianAgent \
    --name fireflies-sync
```

The daemon runs in the foreground, logs to stdout, and binds a Unix
domain socket. Press `Ctrl+C` to stop.

### 4.2 Verify it's running

From another terminal:

```bash
parrot status fireflies-sync
```

Output:

```
PID           12345
Uptime (s)    42.3
Version       0.1.0
Scheduler     available=True, running=True, jobs=1
Connections   0
```

### 4.3 Background (tmux / screen)

For development sessions where you want the daemon to survive terminal
closes:

```bash
tmux new -d -s fireflies "parrot serve fireflies-daemon.yaml"

# Reconnect later:
tmux attach -t fireflies
```

For production, use systemd or supervisord (see
[§8 Deploying as a system service](#8-deploying-as-a-system-service)).

---

## 5. Interacting with a running daemon

All client commands accept either the service **name** (resolved to
the default socket path) or an explicit **socket path**.

### 5.1 Interactive console (`parrot attach`)

```bash
parrot attach fireflies-sync
```

This opens the same Rich console as `parrot agent`, plus daemon-only
slash commands:

| Command | Description |
|---------|-------------|
| *(any text)* | Chat with the agent (conversation history persists within the connection) |
| `/status` | Daemon status (PID, uptime, scheduler, connections) |
| `/schedules` | `list \| add \| pause \| resume \| remove` scheduled jobs |
| `/invoke <method> [json]` | Call an exposed agent method directly |
| `/help` | Full command listing |
| `Ctrl+D` or `/quit` | Detach (the daemon keeps running) |

**Example session:**

```
$ parrot attach fireflies-sync

Attached to daemon: FirefliesObsidianSync
Type your message to chat. Use /help for slash commands. Ctrl+D to exit.

> Sync my latest meetings from Fireflies
✅ Synced 3 new transcripts to ~/vaults/notes/meetings/

> /invoke sync_fireflies_transcripts {"limit": 5, "skip_existing": true}
{"status": "ok", "synced": 2, "skipped": 3, "errors": []}

> /invoke summarize_transcript {"note_title": "2026-08-18-weekly-standup"}
{"status": "ok", "summary": "The team discussed...", "updated": true}

> /status
PID: 12345 | Uptime: 1h 23m | Scheduler: running (1 job) | Connections: 1

> /quit
```

### 5.2 One-shot questions (`parrot ask`)

Pipe-friendly: renders Markdown on a TTY, plain text otherwise.

```bash
# Ask a question:
parrot ask fireflies-sync "What meetings did I have this week?"

# Use in scripts:
result=$(parrot ask fireflies-sync "Sync my meetings" 2>/dev/null)
echo $?  # 0 on success, 1 on error
```

### 5.3 Direct method invocation (`/invoke`)

From the interactive console, call any method listed in
`exposed_methods`:

```
/invoke sync_fireflies_transcripts {"limit": 10}
/invoke summarize_transcript {"note_title": "2026-08-18-planning", "granularity": "detailed"}
```

Arguments are passed as a JSON object. The daemon calls the method on
the live agent instance and returns the serialized result.

---

## 6. Scheduling recurring tasks

agentd boots `AgentSchedulerManager` headless — no aiohttp needed.
There are two ways to set up recurring jobs.

### 6.1 Decorator schedules (static)

Define schedules directly on your agent class. They are registered
automatically when the daemon starts:

```python
from parrot.scheduler.manager import ScheduleType, schedule
from parrot.bots.agent import BasicAgent


class FirefliesObsidianAgent(BasicAgent):

    @schedule(ScheduleType.INTERVAL, hours=8)
    async def auto_sync(self) -> None:
        """Sync Fireflies transcripts every 8 hours."""
        await self.sync_fireflies_transcripts(limit=20)

    @schedule(ScheduleType.CRON, hour=9, minute=0, day_of_week="mon-fri")
    async def morning_digest(self) -> None:
        """Summarize yesterday's meetings every weekday at 9 AM."""
        # Find yesterday's meetings and summarize them
        ...
```

**Available schedule types:**

| Type | Example kwargs |
|------|---------------|
| `ScheduleType.INTERVAL` | `seconds=`, `minutes=`, `hours=`, `days=` |
| `ScheduleType.CRON` | `hour=`, `minute=`, `day_of_week=`, `month=`, etc. |
| `ScheduleType.DATE` | `run_date=datetime(...)` (one-shot) |

Decorator schedules always work, even without a database — they run
in-memory.

### 6.2 Dynamic schedules (runtime)

Add, pause, resume, or remove schedules at runtime from the
interactive console:

```
# List current schedules:
/schedules list

# Add a new interval schedule:
/schedules add --type interval --hours 4 --method sync_fireflies_transcripts

# Add a cron schedule:
/schedules add --type cron --hour 9 --minute 0 --day-of-week mon-fri \
    --method morning_digest

# Pause a schedule:
/schedules pause <schedule-id>

# Resume it:
/schedules resume <schedule-id>

# Remove it permanently:
/schedules remove <schedule-id>
```

### 6.3 Schedule persistence

Dynamic schedules are **in-memory by default** — they disappear when
the daemon restarts. To persist them across restarts, configure a
Postgres DSN:

```yaml
scheduler:
  enabled: true
  dsn: "postgresql://user:pass@localhost:5432/parrot"
```

| `dsn` | `redis` | Decorator schedules | Dynamic `add/pause/resume/remove` |
|-------|---------|---------------------|-----------------------------------|
| `null` | `false` | ✅ (in-memory) | Accepted but not persisted |
| set | `false` | ✅ | ✅ (persisted in Postgres) |
| set | `true` | ✅ | ✅ (Postgres + Redis jobstore) |

### 6.4 Job event notifications

Subscribed clients receive real-time notifications when jobs execute:

```
⏱ job auto_fireflies-sync_auto_sync ejecutado ✓
```

These lines are flushed between turns in the console — never
mid-stream — so they don't interrupt a conversation.

---

## 7. Exposing the daemon over MCP

`parrot mcp-serve` runs an MCP **stdio** proxy: an MCP client talks
JSON-RPC over stdin/stdout, and every tool call is proxied to the
daemon over its Unix socket.

### 7.1 Register with Claude Code

```bash
claude mcp add fireflies-sync -- parrot mcp-serve fireflies-sync
```

Now Claude Code can discover and call these tools:

| MCP Tool | Always available? | Description |
|----------|-------------------|-------------|
| `ask_agent(prompt)` | ✅ | Chat with the agent (shares history within the MCP session) |
| `agent_info()` | ✅ | Name, class, LLM, tool count, uptime, exposed methods |
| `list_schedules()` | ✅ | Current scheduled jobs |
| `daemon_status()` | ✅ | PID, uptime, scheduler state, active connections |
| `invoke_method(method, kwargs)` | ⚠️ Only when `exposed_methods` is non-empty | Call an allowlisted agent method |

### 7.2 Security note

`invoke_method` lets an external LLM call arbitrary allowlisted
methods on your live agent. Only populate `exposed_methods` with
methods you have deliberately reviewed for MCP exposure. When the list
is empty, `invoke_method` is never registered — external LLMs cannot
discover or call it.

### 7.3 Example: Claude Code using the daemon

After registering, Claude Code can use the agent's tools naturally:

```
User: Sync my Fireflies meetings
Claude: I'll use the fireflies-sync daemon to sync your meetings.
        [calls ask_agent("Sync my latest Fireflies meetings")]
        ✅ Synced 3 new transcripts.
```

---

## 8. Deploying as a system service

### 8.1 systemd — user service (default)

```bash
parrot install-service fireflies-daemon.yaml
```

This writes `~/.config/systemd/user/parrot-fireflies-sync.service`
and prints the follow-up commands:

```bash
systemctl --user daemon-reload
systemctl --user enable --now parrot-fireflies-sync
```

The generated unit uses `Type=notify` — the daemon sends
`sd_notify("READY=1")` once its socket is bound. When `NOTIFY_SOCKET`
is absent (e.g. under supervisord or a plain terminal), this is a
silent no-op.

**Manage the service:**

```bash
# Check status:
systemctl --user status parrot-fireflies-sync

# Follow logs:
journalctl --user -u parrot-fireflies-sync -f

# Stop:
systemctl --user stop parrot-fireflies-sync

# Disable (won't start on boot):
systemctl --user disable parrot-fireflies-sync
```

### 8.2 systemd — system-wide

```bash
parrot install-service fireflies-daemon.yaml --system
```

This **prints the unit to stdout only** — agentd never writes to
`/etc` and never escalates privileges. Install it yourself:

```bash
sudo tee /etc/systemd/system/parrot-fireflies-sync.service <<< "$(parrot install-service fireflies-daemon.yaml --system)"
sudo systemctl daemon-reload
sudo systemctl enable --now parrot-fireflies-sync
```

### 8.3 supervisord

agentd runs in the foreground (no double-fork, no pidfile), so a plain
supervisord program block works:

```ini
[program:parrot-fireflies-sync]
command=/path/to/venv/bin/parrot serve /path/to/fireflies-daemon.yaml
autostart=true
autorestart=true
stdout_logfile=/var/log/parrot/fireflies-sync.log
environment=PYTHONUNBUFFERED="1",FIREFLIES_API_KEY="your-token"
```

---

## 9. Stopping the daemon

### 9.1 Foreground (Ctrl+C)

If you ran `parrot serve` in a terminal, press **Ctrl+C**. The daemon
catches `SIGINT`, waits up to `shutdown_grace` seconds (default: 30)
for the scheduler to drain, then exits.

### 9.2 Signal-based (background processes)

```bash
# Graceful shutdown (same as Ctrl+C):
kill -SIGTERM $(cat /proc/$(pgrep -f "parrot serve.*fireflies")/status | head -1)

# Or if you know the PID from `parrot status`:
kill <pid>
```

The daemon handles both `SIGTERM` and `SIGINT` identically: graceful
shutdown with the configured grace period.

### 9.3 RPC shutdown

From a connected client (console or programmatic):

```
/invoke daemon.shutdown
```

Or via the JSON-RPC protocol directly:

```json
{"jsonrpc": "2.0", "method": "daemon.shutdown", "id": 1}
```

The daemon acknowledges the request and begins graceful shutdown.

### 9.4 systemd

```bash
# User service:
systemctl --user stop parrot-fireflies-sync

# System service:
sudo systemctl stop parrot-fireflies-sync
```

### 9.5 What happens during shutdown

1. The daemon stops accepting new connections.
2. Active connections receive an `event.shutdown` notification.
3. The scheduler is shut down (running jobs are allowed to complete up
   to `shutdown_grace` seconds).
4. The Unix socket file is removed.
5. The process exits with code 0.

---

## Quick Reference

```bash
# ── Serve ──────────────────────────────────────────────────
parrot serve fireflies-daemon.yaml          # from YAML config
parrot serve module:Agent --name my-agent   # direct target

# ── Interact ───────────────────────────────────────────────
parrot attach fireflies-sync                # interactive console
parrot ask fireflies-sync "question"        # one-shot
parrot status fireflies-sync                # health check

# ── Schedule (inside parrot attach) ────────────────────────
/schedules list
/schedules add --type interval --hours 8 --method sync_fireflies_transcripts
/schedules pause <id>
/schedules resume <id>
/schedules remove <id>

# ── Invoke methods (inside parrot attach) ──────────────────
/invoke sync_fireflies_transcripts {"limit": 10}
/invoke summarize_transcript {"note_title": "2026-08-18-standup"}

# ── MCP ────────────────────────────────────────────────────
claude mcp add fireflies-sync -- parrot mcp-serve fireflies-sync

# ── Deploy ─────────────────────────────────────────────────
parrot install-service fireflies-daemon.yaml             # systemd user
parrot install-service fireflies-daemon.yaml --system    # systemd system (stdout only)

# ── Stop ───────────────────────────────────────────────────
Ctrl+C                                           # foreground
systemctl --user stop parrot-fireflies-sync      # systemd
kill -SIGTERM <pid>                              # signal
```

---

## Further Reading

- [agentd API Reference](../agentd.md) — full protocol, error codes,
  wire format
- [Agent CLI Daemon Spec](../../sdd/specs/agent-cli-daemon.spec.md) —
  original design specification
- [Fireflies → Obsidian example](../../examples/agents/fireflies_obsidian_daemon.py) —
  programmatic daemon launch
- [Fireflies daemon YAML](../../examples/agents/fireflies_daemon.yaml) —
  ready-to-use config

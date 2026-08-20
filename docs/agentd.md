# Agent CLI Daemon (agentd)

> **Feature**: FEAT-422 — Agent CLI Daemon
> **Spec**: [sdd/specs/agent-cli-daemon.spec.md](../sdd/specs/agent-cli-daemon.spec.md)
> **Package**: `ai-parrot-integrations[agentd]` (`parrot.integrations.agentd`)

`agentd` runs **one AI-Parrot agent** as a long-lived, foreground *Nix
service (systemd/supervisord-managed), and lets you converse with it from
a terminal, from a one-shot script, or from an external LLM (Claude Code
and friends) over MCP — all while its internal machinery
(`AgentSchedulerManager` jobs, method invocation) keeps working exactly as
it does under the full aiohttp server.

It sits between two existing options:

- The full **aiohttp server** — multi-agent, HTTP API, always running.
- The **in-process `parrot agent` REPL** — single agent, but dies with
  the terminal, no client/server split.

`agentd` is the middle ground: **1 daemon = 1 agent**, reachable over a
Unix domain socket, with thin clients (console, one-shot, MCP) attaching
and detaching independently of the daemon's own lifetime.

---

## Quickstart

```bash
# 1. Run an agent daemon in the foreground, straight from a Python path
#    (class, instance, or sync/async factory) — no YAML needed for a
#    quick spin:
parrot serve my_package.agents:MyAgent --name my-agent

# 2. In another terminal, attach the interactive Rich console:
parrot attach my-agent

# 3. Or fire a one-shot, pipe-friendly question:
parrot ask my-agent "What's the status of order 4821?"

# 4. Pretty-print daemon status:
parrot status my-agent
```

`parrot attach`/`parrot ask`/`parrot status` all accept either the
service **name** (resolved to the default socket path) or an explicit
**socket path**.

---

## YAML configuration

For anything beyond a quick spin — and required for `parrot
install-service` — describe the daemon in a YAML file
(`AgentServiceConfig`, Pydantic v2):

```yaml
name: my-agent                    # required — becomes the socket/unit/log identity
agent:
  target: "my_package.agents:MyAgent"   # required — "module.path:attr"
  kwargs:                         # optional — passed to the class/factory
    verbose: true
socket: null                      # optional — default: $XDG_RUNTIME_DIR/parrot/<name>.sock
scheduler:
  enabled: true                   # default: true
  dsn: null                       # optional Postgres DSN for schedule persistence
  redis: false                    # default: false — attach a Redis jobstore
exposed_methods: []               # default: [] — allowlist for agent.invoke / MCP invoke_method
log_level: "INFO"                 # default: "INFO"
max_line_bytes: 10485760           # default: 10 MB — NDJSON line-size limit
shutdown_grace: 30.0               # default: 30.0 — seconds to wait for graceful shutdown
```

```bash
parrot serve my-agent.yaml
```

### Field reference

| Field | Type | Default | Notes |
|---|---|---|---|
| `name` | `str` | — (required) | Non-empty, no path separators (`/`, `\`) — becomes the socket filename and systemd unit name. |
| `agent.target` | `str` | — (required) | `"module.path:attr"` — resolved as a class (instantiated), an already-constructed instance (used as-is), or a sync/async factory callable (called, awaited if it returns a coroutine). |
| `agent.kwargs` | `dict` | `{}` | Passed to the class/factory when `target` isn't already an instance. |
| `socket` | `Path \| null` | `null` | Explicit UDS path. `null` → `$XDG_RUNTIME_DIR/parrot/<name>.sock`, falling back to `/tmp/parrot-<uid>/<name>.sock`. |
| `scheduler.enabled` | `bool` | `true` | `false` skips the headless scheduler bootstrap entirely. |
| `scheduler.dsn` | `str \| null` | `null` | Postgres DSN. `null` → no DB-backed schedule persistence (decorator schedules still work, in-memory). |
| `scheduler.redis` | `bool` | `false` | Attach a Redis-backed jobstore alongside the always-present in-memory one. |
| `exposed_methods` | `list[str]` | `[]` | Allowlist for `agent.invoke` (RPC) and a **hard requirement** for the MCP `invoke_method` tool to even be registered — empty means `invoke_method` is never exposed over MCP. |
| `log_level` | `str` | `"INFO"` | Standard `logging` level name. |
| `max_line_bytes` | `int` | `10 * 1024 * 1024` | NDJSON line-size limit for the UDS server. |
| `shutdown_grace` | `float` | `30.0` | Seconds `SIGTERM`/`SIGINT` handling waits for scheduler shutdown before forcing ahead. |

CLI overrides on `parrot serve`: `--name`, `--socket`, `--dsn`,
`--redis`/`--no-redis`, `--log-level` — applied on top of either the YAML
file or a direct `module:attr` target (`--name` is required in that
latter case, since there's no YAML to source it from).

---

## Deploying as a service

### systemd (user, default)

```bash
parrot install-service my-agent.yaml
```

Writes `~/.config/systemd/user/parrot-my-agent.service` and prints the
follow-up commands:

```bash
systemctl --user daemon-reload
systemctl --user enable --now parrot-my-agent
```

Generated unit:

```ini
[Unit]
Description=AI-Parrot Agent Daemon: my-agent
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
ExecStart=/path/to/venv/bin/parrot serve /path/to/my-agent.yaml
Restart=on-failure
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
```

- `Type=notify`: the daemon sends a hand-rolled `sd_notify("READY=1")`
  datagram once its socket is bound and ready — no `sdnotify` PyPI
  dependency. When `NOTIFY_SOCKET` is absent (e.g. under supervisord, or
  a plain terminal run), this is a silent no-op — the daemon behaves
  exactly like `Type=simple`.
- `ExecStart` is resolved from `sys.executable`'s own bin directory, so
  it always points at the venv the unit was generated from.
- `journalctl --user -u parrot-my-agent -f` follows the logs (plain,
  timestamp-free format — journald already timestamps every line).

### systemd (system-wide)

```bash
parrot install-service my-agent.yaml --system
```

**Prints the unit to stdout only** — `agentd` never writes to `/etc` and
never escalates privileges. To install it system-wide:

```bash
# copy the printed unit yourself, as root:
sudo tee /etc/systemd/system/parrot-my-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now parrot-my-agent
```

### supervisord

`agentd` never double-forks or writes a pidfile (spec decision: foreground
+ orchestrator-managed, not self-daemonizing), so a plain supervisord
program block works as-is — `Type=notify`'s `sd_notify` call is simply a
no-op here (no `NOTIFY_SOCKET`):

```ini
[program:parrot-my-agent]
command=/path/to/venv/bin/parrot serve /path/to/my-agent.yaml
autostart=true
autorestart=true
stdout_logfile=/var/log/parrot/my-agent.log
environment=PYTHONUNBUFFERED="1"
```

---

## Scheduler modes

`AgentSchedulerManager` boots **headless** — no aiohttp import anywhere in
the daemon's process path — via `start_headless(dsn=..., use_redis=...)`.
Decorator-registered schedules (`@schedule(...)` on your agent's methods)
always work; DB-backed dynamic schedules (`schedules.add/pause/resume/
remove`) need a DSN.

| `scheduler.dsn` | `scheduler.redis` | Jobstores | Decorator schedules | `schedules.add/pause/resume/remove` |
|---|---|---|---|---|
| `null` | `false` | in-memory only | ✅ | proxy errors (no DB to persist to, but calls don't crash the daemon) |
| set | `false` | in-memory + Postgres-backed | ✅ | ✅ |
| set | `true` | in-memory + Postgres + Redis | ✅ | ✅ |

`schedules.list` always works regardless of DSN — it degrades gracefully
to a JobStore-only view (decorator schedules) when no DB is configured.

If `ai-parrot-server` (which owns `AgentSchedulerManager`) isn't
installed at all, the daemon logs a warning and runs without a
scheduler — `schedules.*` RPCs then return application error `1003`
(`SCHEDULER_UNAVAILABLE`) instead of crashing.

### Decorator example

```python
from parrot.scheduler.manager import ScheduleType, schedule

class MyAgent(Agent):
    @schedule(ScheduleType.INTERVAL, seconds=3600)
    async def hourly_digest(self) -> None:
        await self.ask("Summarize today's activity so far.")
```

Once the daemon starts, `register_bot_schedules(agent)` finds every
`@schedule`-decorated method and registers it with APScheduler
automatically — no extra configuration needed. Subscribed clients
(`events.subscribe`) receive `event.job_executed`/`event.job_error`
notifications as jobs run.

---

## Attaching a console / one-shot / MCP client

```bash
# Full interactive console (reuses the existing AgentREPL — same UX as
# `parrot agent`, plus daemon-only slash commands):
parrot attach my-agent

# Inside the console:
#   /status      — daemon.status pretty-printed
#   /schedules   — list|add|pause|resume|remove
#   /invoke <method> [json-kwargs]  — call an allowlisted agent method
#   (queued job-event lines, e.g. "⏱ job auto_my-agent_hourly_digest
#    ejecutado ✓", are flushed between turns, never mid-stream)

# One-shot, pipe-friendly (Markdown on a TTY, plain text otherwise):
parrot ask my-agent "..." | tee output.txt
echo $?   # 0 on success, 1 on error
```

---

## Claude Code sub-agent tool bridge (FEAT-434)

When the served agent's LLM is `claude-agent:*` / `claude-code:*`
(`ClaudeAgentClient`), every turn is delegated to a local Claude Code
sub-agent. **The agent's own registered tools are exposed to that
sub-agent automatically** — no separate configuration, no opt-in list —
as an in-process `mcp__parrot__<tool>` MCP server. Tools keep their open
connections, auth context, `working_memory` and toolkit lifecycle; every
bridged call still goes through the exact same TOOL_CALL guardrails →
`GrantGuard` → `ConfirmationGuard` → compression pipeline as a native
tool call (see [`docs/tools.md`](tools.md) "Claude Agent Tool Bridge" for
the full design).

```yaml
agent:
  target: "parrot.agents.claude_code:make_agent"
  kwargs:
    llm: "claude-agent:claude-sonnet-4-6"
    use_tools: true          # default — set false to opt this agent out
    tools:
      - "MathTool"            # registered normally; bridged automatically
```

See `examples/agents/claude_code_daemon.yaml` for a runnable example —
`parrot ask claude-code "What is sqrt(144)?"` exercises the bridged
`mcp__parrot__math_tool` tool end to end.

**Narrowing budget.** Claude Code loads every exposed MCP tool eagerly at
session `init` — it performs no narrowing of its own (measured: 25
exposed tools -> 25 listed at `init`). `ClaudeAgentRunOptions.
max_exposed_tools` (default `15`) bounds what is handed over each turn,
ranked against the turn's prompt via `ToolManager.rank_tools()`; anything
dropped is logged (count + names), never silently truncated. Set
`expose_parrot_tools: false` on `ClaudeAgentRunOptions` to disable
bridging entirely for a given client.

**Confirming tools.** A tool requiring confirmation still parks the turn
for a real human — never a self-granted switch the sub-agent could flip
itself. See [`docs/hitl-confirmation.md`](hitl-confirmation.md) "Bridged
tools (Claude Code sub-agents)" for the full HITL wiring.

**Auth caveat (already shipped, worth repeating here):** the daemon
drops `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` by default so the
bundled `claude` CLI uses its stored claude.ai / Claude Code login
instead of billing an API key — `sanitize_claude_environment()`
(`parrot.agents.claude_code`). Verify in the daemon log:
`apiKeySource: "none"` means the Claude Code login is in effect;
`apiKeySource: "ANTHROPIC_API_KEY"` means an API key took over (unset it,
or pass `force_cc_auth: false` explicitly if that's what you want).

---

## MCP registration (external LLMs)

`parrot mcp-serve <name|socket>` runs an MCP **stdio** proxy: an MCP
client (Claude Code, another agent framework) talks JSON-RPC over
stdin/stdout, and every tool call is proxied to the daemon over its UDS
socket. All logging goes to stderr — stdout is reserved for the MCP
channel.

```bash
claude mcp add my-agent -- parrot mcp-serve my-agent
```

Exposed tools:

| Tool | Always available? | Notes |
|---|---|---|
| `ask_agent(prompt)` | ✅ | Non-streaming `chat.send`. One MCP process = one daemon connection = one conversation session, so consecutive calls in the same MCP session share history. |
| `agent_info()` | ✅ | Name, class, LLM, tool count, uptime, `exposed_methods`. |
| `list_schedules()` | ✅ | Same payload as `schedules.list` (degrades gracefully without a DSN). |
| `daemon_status()` | ✅ | Same payload as `daemon.status`. |
| `invoke_method(method, kwargs)` | ⚠️ **only when `exposed_methods` is non-empty** | Client-side allowlist check as defense in depth, on top of the daemon's own enforcement. If your config has `exposed_methods: []`, this tool is never even registered — external LLMs cannot discover or call it. |

**Gating warning**: `invoke_method` is powerful — it lets an external LLM
call arbitrary allowlisted methods on your live agent. Only populate
`exposed_methods` with methods you have deliberately reviewed for MCP
exposure.

---

## Protocol appendix

Wire format: **JSON-RPC 2.0** framed as **NDJSON** (one `\n`-terminated
UTF-8 JSON object per line) over a Unix domain socket at
`$XDG_RUNTIME_DIR/parrot/<name>.sock` (fallback `/tmp/parrot-<uid>/
<name>.sock`), directory `0700`, socket file `0600`. One UDS connection =
one conversation session.

### Method table

| Method | Params | Returns |
|---|---|---|
| `chat.send` | `{prompt, stream: bool, metadata?}` | Full `{output, metadata}` response, or `{stream_id}` ack when `stream=true` |
| `agent.info` | — | `{name, class, llm, tools_count, uptime_s, exposed_methods}` |
| `tools.list` | — | `{tools: [...]}` |
| `agent.invoke` | `{method, args?, kwargs?}` | Serialized result of a public agent method (underscore-prefixed methods always rejected; `exposed_methods` acts as an allowlist when non-empty) |
| `schedules.list` | — | Jobs: id, trigger, next_run_time, `source` (`db`/`auto`) |
| `schedules.add` | schedule fields | ack (`AgentSchedule`) |
| `schedules.pause` / `schedules.resume` / `schedules.remove` | `{schedule_id}` | ack |
| `events.subscribe` / `events.unsubscribe` | — | `{subscribed: bool}` |
| `daemon.status` | — | `{pid, uptime_s, version, scheduler: {available, running, jobs}, active_connections}` |
| `daemon.shutdown` | — | ack, then graceful shutdown |
| `hitl.respond` (FEAT-434) | `{interaction_id, response_type, value, respondent?}` | `{ok: true}` — a human's answer to a bridged confirming-tool request; see below |

Streaming (`chat.send` with `stream=true`): the ack `{stream_id}` is
followed by `chat.delta {stream_id, text}` ×N, then exactly one terminal
`chat.complete {stream_id, response, usage}` or `chat.error {stream_id,
error}`. Subscribed clients also receive `event.job_executed`,
`event.job_error`, `event.shutdown`.

**Bridged-HITL notifications (FEAT-434, TASK-2290):** plain-string
`RpcNotification` method names — not listed in the wire-protocol
constants (`protocol.py`), since the notification/dispatch surface
already accepts any string. Every subscribed session receives:
`hitl.request {interaction_id, question, interaction_type, recipient}`,
`hitl.notify {recipient, message}`, `hitl.cancel {interaction_id,
recipient}`. Answer a pending one with `hitl.respond` above.

### Error codes

| Code | Meaning |
|---|---|
| `-32700` | Parse error (malformed JSON) |
| `-32600` | Invalid request |
| `-32601` | Method not found |
| `-32602` | Invalid params |
| `-32603` | Internal error (any uncaught handler exception — message only, full traceback logged daemon-side) |
| `1001` | `AGENT_BUSY` |
| `1002` | `UNKNOWN_AGENT_METHOD` — unknown/private/non-allowlisted `agent.invoke` method |
| `1003` | `SCHEDULER_UNAVAILABLE` — `ai-parrot-server` not installed, or `scheduler.enabled: false` |
| `1004` | `SCHEDULE_NOT_FOUND` |

---

## Related

- Spec: [`sdd/specs/agent-cli-daemon.spec.md`](../sdd/specs/agent-cli-daemon.spec.md)
- Console engine reused as-is: `parrot.cli.repl.AgentREPL` (see `parrot agent`)
- MCP server base reused as-is: `parrot.mcp.local_server.StdioMCPServer`

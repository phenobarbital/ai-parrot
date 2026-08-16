---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Agent CLI Daemon — per-agent *Nix service with Rich console, JSON-RPC/UDS and MCP stdio proxy

**Feature ID**: FEAT-422
**Date**: 2026-08-16
**Author**: Jesus Lara
**Status**: approved
**Target version**: ai-parrot-integrations 0.2.x / ai-parrot-server next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot agents today only live inside the aiohttp web server. There is no
way to run a single agent as a long-lived *Nix service (systemd/supervisord)
and "converse" with it from a terminal while its internal machinery —
`AgentSchedulerManager` (APScheduler) jobs, internal method invocation —
keeps working exactly as it does under the web server. The existing
`parrot agent` REPL (FEAT console-cli-agents) covers in-process standalone
agents and HTTP proxying to the full server, but nothing in between: a
headless per-agent daemon that survives terminal disconnects, with a thin
attachable client.

Feasibility (verified during brainstorm): APScheduler's `AsyncIOScheduler`
only requires a running asyncio event loop — **not** aiohttp. The aiohttp
coupling in `AgentSchedulerManager` is lifecycle-only (`setup(app)`,
`on_startup(app, conn)`, HTTP handlers, navigator `PostgresPool`).

### Goals

- Run **one agent per daemon** as a foreground process (`parrot serve`),
  daemonized by systemd/supervisord (new-style daemon: no fork, no pidfile,
  logs to stdout → journald).
- Expose the daemon over a **Unix domain socket speaking JSON-RPC 2.0**
  (NDJSON framing), authenticated by filesystem permissions.
- **Thin clients** over that socket:
  - `parrot attach <name>` — the existing Rich `AgentREPL`, via a new
    `DaemonAgentProxy` loader (streaming, slash commands, job-event lines).
  - `parrot ask <name> "..."` — one-shot, pipe-friendly.
  - `parrot mcp-serve <name>` — an MCP stdio server proxying tools
    (`ask_agent`, `agent_info`, `list_schedules`, `daemon_status`, gated
    `invoke_method`) to the daemon, so external LLMs (Claude Code, etc.)
    can converse with the agent.
- **Headless scheduler**: `AgentSchedulerManager` boots without aiohttp via
  a new `start_headless()` path, with **lightweight fallback**: Postgres
  persistence only if a DSN is configured, `MemoryJobStore` when Redis is
  absent; decorator schedules (`@schedule`, `@schedule_daily_report`, …)
  always work.
- Agent selection via **Python path** (`module:attr` — class, instance, or
  sync/async factory) plus an optional **YAML config file** for systemd use.
- `parrot install-service <config.yaml>` generates a systemd unit
  (user-level by default; `--system` variant printed, never auto-escalated).

### Non-Goals (explicitly out of scope)

- Multi-agent daemons — the aiohttp server already covers that case
  (decided in brainstorm: 1 daemon = 1 agent).
- Self-daemonization (`--daemon`, double-fork, pidfiles) — rejected in
  brainstorm in favour of foreground + systemd.
- A2A or MCP as the daemon's *internal* wire protocol — rejected in
  brainstorm in favour of JSON-RPC 2.0 over UDS.
- Full TUI (textual), themes, multi-client shared-view sync. Multiple
  concurrent connections ARE allowed, each with its own conversation
  session.
- Dynamic schedule management UI beyond the RPC/slash commands listed here.
- TCP transport / remote network access — UDS only in v1.

---

## 2. Architectural Design

### Overview

A new subsystem `parrot.integrations.agentd` in **ai-parrot-integrations**
implements a per-agent daemon and its clients. The daemon
(`AgentDaemon`) loads exactly one agent (Python-path or YAML config),
optionally boots `AgentSchedulerManager` headless (lazy import from
ai-parrot-server; degrade with a warning if not installed), and serves
JSON-RPC 2.0 over a Unix domain socket. All clients — Rich console,
one-shot `ask`, MCP stdio proxy — are thin consumers of one shared
`AgentDaemonClient`.

The console reuses the existing `AgentREPL` engine unchanged: a new
`DaemonAgentProxy` implements the same duck-typed loader interface as
`ServerAgentProxy` (`load/list_agents/close` + bot-proxy
`ask/ask_stream/configure/get_available_tools/get_tools_count/has_tools`),
and daemon-specific slash commands are added through the existing
`SlashCommandDispatcher.register()` hook.

Resolved-in-brainstorm decisions baked into this design: Option B
(daemon + thin client) over single-process console; 1 daemon = 1 agent;
JSON-RPC 2.0 over UDS; lightweight infra fallback; Python path + config
file for agent selection; foreground-only lifecycle + unit generator.

### Component Diagram

```
 parrot attach <name> ───────┐
 (AgentREPL + DaemonAgentProxy)
                             │        ┌─────────────────────────────────────┐
 parrot ask <name> "..." ────┤  UDS   │ AgentDaemon (parrot serve cfg.yaml) │
 (one-shot)                  ├─JSON──▶│  ┌─────────┐   ┌──────────────────┐ │
                             │ -RPC   │  │ Agent   │   │ AgentScheduler   │ │
 parrot mcp-serve <name> ────┘  2.0   │  │ (single)│   │ Manager          │ │
 (StdioMCPServer → AgentDaemonClient) │  └─────────┘   │ (start_headless) │ │
        ▲                             │        ▲       └──────────────────┘ │
        │ stdio (MCP)                 │  SingleAgentManager (adapter)       │
 Claude Code / external LLM           │  JsonRpcUnixServer + EventBroker    │
                                      └─────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AgentREPL` / `REPLConfig` (`parrot.cli.repl`) | uses | Console engine reused verbatim; fed a `DaemonAgentProxy` |
| `SlashCommandDispatcher` (`parrot.cli.commands`) | extends via `register()` | New `/status`, `/schedules`, `/invoke` commands (daemon mode only) |
| `ServerAgentProxy` / `_ServerBotProxy` (`parrot.cli.loaders`) | pattern reference | `DaemonAgentProxy` mirrors its duck-typed interface |
| `parrot.cli` `LazyGroup` | extends registry dict | New lazy keys `serve`, `attach`, `ask`, `install-service`, `mcp-serve` → `parrot.integrations.agentd.cli`; clear error if ai-parrot-integrations missing |
| `AgentSchedulerManager` (ai-parrot-server `parrot.scheduler.manager`) | refactor + uses | New `start_headless()`; `on_startup()` reimplemented on top of it (no behaviour change for the web server) |
| `StdioMCPServer` / `MCPServerBase` (`parrot.mcp.local_server`, `parrot.mcp.server_base`) | uses | MCP stdio proxy registers `AbstractTool`s that call the daemon client |
| `AbstractTool` (`parrot.tools`) | subclasses | Proxy tools for the MCP server |
| systemd / supervisord | external | `Type=notify` via hand-rolled `sd_notify` datagram (no new dependency); `Type=simple`/supervisord compatible when `NOTIFY_SOCKET` is absent |

### Data Models

```python
# parrot/integrations/agentd/config.py (new — Pydantic v2)
class SchedulerConfig(BaseModel):
    enabled: bool = True
    dsn: str | None = None        # None → no Postgres persistence
    redis: bool = False           # False → MemoryJobStore

class AgentTargetConfig(BaseModel):
    target: str                   # "module.path:attr" — class | instance | factory
    kwargs: dict[str, Any] = {}

class AgentServiceConfig(BaseModel):
    name: str                     # service name → socket / unit / logs
    agent: AgentTargetConfig
    socket: Path | None = None    # default: $XDG_RUNTIME_DIR/parrot/<name>.sock
    scheduler: SchedulerConfig = SchedulerConfig()
    exposed_methods: list[str] = []   # empty → all public async (RPC); MCP invoke_method REQUIRES non-empty
    log_level: str = "INFO"
    max_line_bytes: int = 10 * 1024 * 1024
    shutdown_grace: float = 30.0
```

```python
# parrot/integrations/agentd/protocol.py (new)
class RpcRequest(BaseModel):    # jsonrpc="2.0", id, method, params
class RpcResponse(BaseModel):   # id, result | error{code, message, data?}
class RpcNotification(BaseModel)  # method, params (no id) — chat.delta etc.
```

### Wire Protocol (JSON-RPC 2.0 over UDS, NDJSON framing)

- One JSON object per `\n`-terminated UTF-8 line; configurable line limit
  (default 10 MB). Transport: `asyncio.start_unix_server`.
- Socket at `$XDG_RUNTIME_DIR/parrot/<name>.sock` (fallback
  `/tmp/parrot-<uid>/<name>.sock`), dir `0700`, socket `0600`.
  Stale-socket handling on boot: try-connect → alive ⇒ abort "daemon
  already running"; dead ⇒ unlink and rebind.
- One UDS connection = one conversation session (own `session_id`).

Methods:

| Method | Params | Returns |
|---|---|---|
| `chat.send` | `{prompt, stream: bool, metadata?}` | full response, or `{stream_id}` ack when `stream=true` |
| `agent.info` | — | name, class, llm, tools count, uptime |
| `tools.list` | — | tool names + descriptions |
| `agent.invoke` | `{method, args?, kwargs?}` | serialized result of a public agent method |
| `schedules.list` | — | jobs: id, trigger, next_run_time, origin (decorator/db) |
| `schedules.add/pause/resume/remove` | per-op | ack |
| `events.subscribe` / `events.unsubscribe` | — | ack |
| `daemon.status` | — | pid, uptime, version, scheduler state, active connections |
| `daemon.shutdown` | — | ack, then graceful shutdown |

Streaming: `stream=true` ⇒ ack `{stream_id}`, then notifications on the
same connection: `chat.delta {stream_id, text}` ×N →
`chat.complete {stream_id, response, usage}` | `chat.error {stream_id, error}`.
Subscribed clients also receive `event.job_executed`, `event.job_error`,
`event.shutdown` (fan-out from the existing APScheduler listeners).

Error codes: JSON-RPC standard (−32600/−32601/−32602/−32603) plus
application range: `1001` agent busy, `1002` unknown agent method,
`1003` scheduler unavailable, `1004` schedule not found.
`agent.invoke` rejects underscore-prefixed methods always; when
`exposed_methods` is non-empty it acts as an allowlist for RPC too.

### New Public Interfaces

```python
# parrot/integrations/agentd/service.py
class AgentDaemon:
    def __init__(self, config: AgentServiceConfig): ...
    async def run(self) -> None:      # load agent → scheduler headless → serve → wait signals

class SingleAgentManager:
    """Minimal bot_manager contract for AgentSchedulerManager:
    exposes `_bots` dict, `registry.get_instance()`, `get_crew()`."""

# parrot/integrations/agentd/client.py
class AgentDaemonClient:
    async def connect(cls, socket_path: Path) -> "AgentDaemonClient"
    async def call(self, method: str, **params) -> Any
    def stream(self, prompt: str, **meta) -> AsyncIterator[StreamEvent]
    async def close(self) -> None

# parrot/integrations/agentd/proxy.py
class DaemonAgentProxy:      # loader-compatible: load/list_agents/close
class _DaemonBotProxy:       # ask/ask_stream/configure/get_available_tools/...

# ai-parrot-server: parrot/scheduler/manager.py (refactor)
class AgentSchedulerManager:
    async def start_headless(
        self, *, dsn: str | None = None, use_redis: bool = False
    ) -> None:
        """Boot without aiohttp: pool only if dsn, jobstore per use_redis,
        define_listeners(), scheduler.start(), load_schedules_from_db()
        only when a pool exists."""
    async def stop_headless(self, *, wait: bool = True) -> None
```

CLI surface (Click, lazy-registered in core `parrot` group):

```
parrot serve <config.yaml | module:attr> [--name N] [--socket PATH] [...]
parrot attach <name | socket-path> [--no-stream]
parrot ask <name> "question"            # exit 0/1; Markdown only on TTY
parrot status <name>                    # daemon.status pretty-print
parrot install-service <config.yaml> [--system]
parrot mcp-serve <name | socket-path>   # MCP stdio proxy
```

### Daemon lifecycle

1. Load config → logging to stdout (journald-friendly, no timestamps
   duplication), honour `log_level`.
2. Resolve `target`: class ⇒ instantiate with kwargs; callable ⇒ call
   (await if coroutine); result with async `configure()` ⇒ call it.
3. Scheduler (best-effort): lazy `from parrot.scheduler.manager import
   AgentSchedulerManager`; `ImportError` ⇒ log warning, continue without.
   Else `SingleAgentManager(agent)` + `start_headless(dsn, use_redis)` +
   `register_bot_schedules(agent)`.
4. Socket dir + stale-socket check + `start_unix_server`.
5. Single parseable "ready" log line (socket, agent, scheduler on/off);
   `sd_notify("READY=1")` iff `NOTIFY_SOCKET` set (hand-rolled datagram,
   no dependency; no-op otherwise).
6. SIGTERM/SIGINT ⇒ stop accepting, notify `event.shutdown`,
   `stop_headless(wait=True)` bounded by `shutdown_grace`, agent
   `cleanup()` if present, unlink socket, exit 0.

### Error Handling

- Every RPC handler wrapped: exception ⇒ JSON-RPC error to client
  (message only), traceback to daemon log. The daemon never dies from a
  bad request.
- Stream failure mid-flight ⇒ `chat.error` notification; session stays up.
- Abrupt client disconnect ⇒ cancel that session's streams, drop its
  event subscriptions.
- Console reconnect: 3 retries with short backoff (survives
  `systemctl restart`). Daemon absent ⇒ actionable error suggesting
  `systemctl --user status parrot-<name>` / `parrot serve`.
- Console job-event lines are queued during an active stream and flushed
  after the turn — never interleaved mid-stream.

---

## 3. Module Breakdown

All new code under
`packages/ai-parrot-integrations/src/parrot/integrations/agentd/` unless
stated otherwise.

### Module 1: Protocol
- **Path**: `.../agentd/protocol.py`
- **Responsibility**: NDJSON framing (read/write line codecs, size limit),
  Pydantic models for JSON-RPC 2.0 requests/responses/notifications,
  error-code constants (incl. 1001–1004).
- **Depends on**: nothing new (stdlib + pydantic).

### Module 2: Config
- **Path**: `.../agentd/config.py`
- **Responsibility**: `AgentServiceConfig` + YAML loading, `target`
  resolution (class/instance/factory, sync/async), default socket-path
  computation (XDG fallback).
- **Depends on**: Module 1 (none strictly; shares package).

### Module 3: Headless scheduler bootstrap (refactor, ai-parrot-server)
- **Path**: `packages/ai-parrot-server/src/parrot/scheduler/manager.py`
- **Responsibility**: extract `start_headless()`/`stop_headless()` from
  `on_startup`/`on_shutdown`; web-server path delegates to them —
  zero behaviour change for aiohttp deployments. Jobstore selection:
  Redis only when requested, `MemoryJobStore` otherwise (move the
  unconditional `RedisJobStore` construction out of `__init__`).
- **Depends on**: none (first parallel-safe task).

### Module 4: UDS JSON-RPC server
- **Path**: `.../agentd/server.py`
- **Responsibility**: `JsonRpcUnixServer` — accept loop, per-connection
  session state, method dispatch table, streaming notification writer,
  `EventBroker` (subscribe/fan-out of scheduler/daemon events),
  stale-socket boot logic, permissions.
- **Depends on**: Module 1.

### Module 5: Daemon service
- **Path**: `.../agentd/service.py`
- **Responsibility**: `AgentDaemon` lifecycle (steps 1–6 above),
  `SingleAgentManager` adapter, `sd_notify` helper, RPC method
  implementations binding agent + scheduler to the dispatch table.
- **Depends on**: Modules 1, 2, 3, 4.

### Module 6: Client
- **Path**: `.../agentd/client.py`
- **Responsibility**: `AgentDaemonClient` — connect/retry, request/response
  correlation, stream demultiplexing by `stream_id`, event callback hook,
  socket-path resolution by service name.
- **Depends on**: Module 1.

### Module 7: Console proxy + slash commands
- **Path**: `.../agentd/proxy.py`
- **Responsibility**: `DaemonAgentProxy`/`_DaemonBotProxy` implementing the
  loader duck-type consumed by `AgentREPL`; `/status`, `/schedules …`,
  `/invoke …` slash commands registered via
  `SlashCommandDispatcher.register()`; queued job-event display.
- **Depends on**: Module 6; existing `parrot.cli.repl`, `parrot.cli.commands`.

### Module 8: MCP stdio proxy
- **Path**: `.../agentd/mcp_server.py`
- **Responsibility**: `AbstractTool` wrappers (`ask_agent`, `agent_info`,
  `list_schedules`, `daemon_status`, `invoke_method` — the latter exposed
  ONLY when `exposed_methods` is non-empty) registered on core
  `StdioMCPServer`; one MCP session = one daemon conversation session.
- **Depends on**: Module 6; existing `parrot.mcp.local_server`.

### Module 9: CLI commands + core registration + packaging
- **Path**: `.../agentd/cli.py`; edits to
  `packages/ai-parrot/src/parrot/cli/__init__.py` (lazy keys) and
  `packages/ai-parrot-integrations/pyproject.toml` (`agentd` extra;
  no heavy new deps — rich/prompt_toolkit/click come from core).
- **Responsibility**: `serve`, `attach`, `ask`, `status`,
  `install-service` (unit-file generator, user-level default, `--system`
  prints/su-do-nothing), `mcp-serve`. Graceful "install
  ai-parrot-integrations[agentd]" error in core when the module is absent.
- **Depends on**: Modules 2, 5, 6, 7, 8.

### Module 10: Integration tests & docs
- **Path**: `packages/ai-parrot-integrations/tests/agentd/`,
  `docs/agentd.md`
- **Responsibility**: see §4; usage doc incl. systemd + Claude Code MCP
  registration (`claude mcp add <name> -- parrot mcp-serve <name>`).
- **Depends on**: all above.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_ndjson_split_and_joined_frames` | 1 | Partial/coalesced/oversized lines |
| `test_rpc_models_roundtrip` | 1 | Request/response/notification (de)serialization, error codes |
| `test_config_yaml_and_defaults` | 2 | YAML load, XDG socket default, validation errors |
| `test_target_resolution_matrix` | 2 | class / instance / factory / async factory / bad path |
| `test_start_headless_no_dsn_no_redis` | 3 | MemoryJobStore, no pool, decorator schedules registered |
| `test_on_startup_delegates_to_headless` | 3 | Web path unchanged (mocked app/pool) |
| `test_stale_socket_boot` | 4 | Dead socket unlinked; live socket ⇒ abort |
| `test_invoke_allowlist_and_underscore` | 5 | `_private` always rejected; allowlist enforced |
| `test_client_stream_demux` | 6 | Interleaved deltas of two streams correlate by stream_id |
| `test_daemon_proxy_interface_parity` | 7 | Duck-type parity with `_ServerBotProxy` (shared attribute checklist) |
| `test_unit_file_generation` | 9 | Rendered unit matches expectations; `--system` never writes with sudo |

### Integration Tests
(temp socket + in-process `EchoAgent` fake; no Postgres/Redis)

| Test | Description |
|---|---|
| `test_chat_send_and_stream_end_to_end` | Full daemon: send, stream deltas → complete |
| `test_two_clients_isolated_sessions` | Concurrent connections don't share history |
| `test_scheduler_interval_job_fires_and_event_emitted` | `@schedule(INTERVAL, seconds=1)` runs; subscriber gets `event.job_executed` |
| `test_daemon_without_server_package` | Import of scheduler blocked ⇒ daemon runs, warns, `schedules.*` → error 1003 |
| `test_graceful_shutdown_sigterm` | SIGTERM: event.shutdown, socket removed, exit 0 |
| `test_mcp_stdio_ask_agent` | MCP handshake over stdio + `ask_agent` against fake daemon |
| `test_ask_oneshot_exit_codes` | `parrot ask` prints and exits 0/1 |

### Test Data / Fixtures
```python
@pytest.fixture
async def echo_daemon(tmp_path):
    """AgentDaemon on tmp socket with EchoAgent (ask/ask_stream/configure
    /get_available_tools stubs); yields (daemon_task, socket_path)."""

@pytest.fixture
def agentd_yaml(tmp_path):
    """Minimal valid agent YAML pointing at tests.agentd.fakes:EchoAgent."""
```

---

## 5. Acceptance Criteria

- [ ] `parrot serve tests-fixture.yaml` boots an agent daemon **without
      aiohttp imported in the daemon process path** (asserted in a test via
      module introspection when ai-parrot-server is absent).
- [ ] `AsyncIOScheduler` runs headless: an interval decorator job fires
      under `parrot serve` with no Postgres and no Redis (MemoryJobStore
      fallback), and with a DSN configured the DB path is exercised
      (mocked pool in unit test).
- [ ] Existing web-server scheduler behaviour is unchanged:
      `on_startup`/`on_shutdown` tests pass with the refactor in place.
- [ ] `parrot attach` reuses `AgentREPL` (no console fork): streaming,
      `/status`, `/schedules`, `/invoke`, queued job-event lines.
- [ ] `parrot ask` is pipe-safe (plain text on non-TTY, exit codes).
- [ ] MCP stdio proxy exposes `ask_agent`/`agent_info`/`list_schedules`/
      `daemon_status`; `invoke_method` appears ONLY with non-empty
      `exposed_methods`.
- [ ] Socket is `0600` in a `0700` dir; stale-socket and already-running
      cases handled.
- [ ] SIGTERM shutdown is graceful and bounded by `shutdown_grace`.
- [ ] `parrot install-service` writes a valid user unit; `Type=notify`
      works (sd_notify datagram) and degrades to `Type=simple`/supervisord.
- [ ] Core `parrot` CLI degrades with an actionable message when
      ai-parrot-integrations is not installed.
- [ ] All unit + integration tests pass
      (`pytest packages/ai-parrot-integrations/tests/agentd/ -v`).
- [ ] Docs: `docs/agentd.md` covers YAML schema, systemd, supervisord,
      MCP registration.
- [ ] No breaking changes to existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
from parrot.cli import cli                              # verified: packages/ai-parrot/src/parrot/cli/__init__.py (LazyGroup instance; lazy dict at line 67)
from parrot.cli.repl import AgentREPL, REPLConfig       # verified: packages/ai-parrot/src/parrot/cli/repl.py:58,27
from parrot.cli.commands import SlashCommandDispatcher, SlashCommand  # verified: packages/ai-parrot/src/parrot/cli/commands.py:70
from parrot.cli.loaders import ServerAgentProxy         # verified: packages/ai-parrot/src/parrot/cli/loaders.py:301 (pattern reference)
from parrot.mcp.local_server import StdioMCPServer      # verified: packages/ai-parrot/src/parrot/mcp/local_server.py:36
from parrot.mcp.server_base import MCPServerBase, LocalServerConfig  # verified: packages/ai-parrot/src/parrot/mcp/server_base.py:27,18
from parrot.models.responses import AIMessage           # verified: packages/ai-parrot/src/parrot/models/responses.py:72
# ai-parrot-server (LAZY import inside daemon — optional dependency):
from parrot.scheduler.manager import AgentSchedulerManager, ScheduleType, schedule  # verified: packages/ai-parrot-server/src/parrot/scheduler/manager.py:284
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/scheduler/manager.py
class AgentSchedulerManager:                          # line 284
    def __init__(self, bot_manager: Any = None, **kwargs)   # line 296
        # NOTE: __init__ currently constructs RedisJobStore UNCONDITIONALLY
        # (jobstores dict at line 310) — Module 3 must make Redis optional.
    def register_bot_schedules(self, bot: Any) -> int      # line 1103
    async def load_schedules_from_db(self)                 # line 1200
    def setup(self, app: web.Application) -> web.Application  # line 1463 (aiohttp path — keep)
    async def on_startup(self, app, conn)                  # line 1504 (delegates to new start_headless)
    async def on_shutdown(self, app, conn)                 # line 1549
    # bot_manager contract used by _execute_agent_job:
    #   self.bot_manager._bots (dict), self.bot_manager.registry.get_instance(name),
    #   self.bot_manager.get_crew(name)

# packages/ai-parrot/src/parrot/cli/repl.py
class REPLConfig(BaseModel)                            # line 27
class AgentREPL:                                       # line 58
    async def run(self) -> None                        # line 96
    async def send(self, query: str) -> AIMessage      # line 160
    async def send_stream(self, query: str) -> None    # line 188
    def register_command(self, cmd: SlashCommand) -> None  # line 248

# packages/ai-parrot/src/parrot/cli/loaders.py — duck type DaemonAgentProxy MUST mirror
class _ServerBotProxy:                                 # line 129
    async def configure(self, app: Any = None) -> None # line 162
    async def ask(self, question, session_id=None, user_id=None, output_mode=None, **kwargs) -> Any   # line 169
    async def ask_stream(self, question, session_id=None, user_id=None, output_mode=None, **kwargs)   # line 211 (async generator)
    # plus: get_available_tools(), get_tools_count(), has_tools()
class ServerAgentProxy:                                # line 301
    async def load(self, name: str) -> _ServerBotProxy # line 339
    async def list_agents(self) -> List[Dict[str, Any]]  # line 374
    async def close(self) -> None                      # line 421

# packages/ai-parrot/src/parrot/cli/commands.py
class SlashCommandDispatcher:                          # line 70
    def register(self, cmd: SlashCommand) -> None      # line 86

# packages/ai-parrot/src/parrot/cli/__init__.py
cli._lazy_commands = { ... }                           # line 67 — add serve/attach/ask/install-service/mcp-serve keys

# packages/ai-parrot/src/parrot/mcp/server_base.py
class MCPServerBase(ABC):                              # line 27
    def register_tool(self, tool: AbstractTool)        # line 38
    def register_tools(self, tools: list[AbstractTool])  # line 45
    async def handle_initialize(...) / handle_tools_list(...) / handle_tools_call(...)  # lines 50/68/79

# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC)             # line 234
    # Reserved lifecycle names (FEAT-391): _open/_close/_ensure_open,
    # auto_open/_opened/_open_lock — do NOT redefine in proxy tools.
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AgentDaemon` | `AgentSchedulerManager.start_headless()` (new) | lazy import + call | manager.py:284 (refactor target) |
| `SingleAgentManager` | `AgentSchedulerManager._execute_agent_job` lookups | `_bots` / `registry.get_instance` / `get_crew` | manager.py (job execution path) |
| `DaemonAgentProxy` | `AgentREPL` | constructor loader param (same as ServerAgentProxy) | repl.py:58 |
| daemon slash cmds | `AgentREPL.register_command()` | `SlashCommand` instances | repl.py:248 |
| `mcp_server.py` tools | `StdioMCPServer.register_tools()` | `AbstractTool` subclasses | server_base.py:45 |
| `cli.py` commands | `parrot.cli` `LazyGroup` | `_lazy_commands` dict keys | cli/__init__.py:67 |
| Event fan-out | APScheduler listeners `job_success`/`job_status` | hook added in Module 3/5 | manager.py (define_listeners) |

### Does NOT Exist (Anti-Hallucination)
- ~~`AgentSchedulerManager.start_headless()`~~ — does NOT exist yet; created by Module 3.
- ~~`parrot.integrations.agentd`~~ — entire package is new (Modules 1–9).
- ~~`parrot.integrations.mcp` server helpers~~ — `packages/ai-parrot-integrations/src/parrot/integrations/mcp/` contains ONLY OAuth `auth/` + `state.py`. The stdio MCP server lives in CORE: `parrot.mcp.local_server.StdioMCPServer`.
- ~~`DaemonAgentProxy` / `AgentDaemonClient` / `AgentServiceConfig`~~ — new; do not import until their module task is done.
- ~~`parrot agent --daemon` / existing daemon mode in `parrot.cli`~~ — no daemon support exists in the current REPL loaders (`StandaloneAgentLoader` is in-process; `ServerAgentProxy` is HTTP).
- ~~`sdnotify` package~~ — NOT a dependency; `sd_notify` is a hand-rolled ~10-line UDP datagram helper.
- ~~`schedules.*` RPC without ai-parrot-server~~ — must return error 1003, not crash.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first throughout; `aiohttp` must NOT be imported by any agentd
  module (the point of the feature). Watch transitive imports.
- Pydantic v2 models for config and protocol; Google-style docstrings +
  strict type hints; `self.logger` (never print) — except the MCP stdio
  path where stdout is the JSON-RPC channel: log to stderr (follow
  `LocalMCPServerBase` precedent, local_server.py:18).
- Mirror `ServerAgentProxy` structure/naming for `DaemonAgentProxy` so the
  REPL sees interchangeable loaders.
- Scheduler refactor must be strictly behaviour-preserving for the aiohttp
  path — `setup()/on_startup()/on_shutdown()` signatures unchanged.
- Console UX: reuse `ResponseRenderer` (`parrot.cli.renderer`) — no new
  rendering stack.

### Known Risks / Gotchas
- `AgentSchedulerManager.__init__` builds `RedisJobStore` eagerly (line
  310) — constructing the manager without Redis reachable may fail today;
  Module 3 must defer/condition jobstore creation. Mitigation: jobstore
  selection moves into `start_headless()`/`setup()`.
- Agent construction may still require env/config (navconfig) — the daemon
  inherits the same environment expectations as any standalone bot;
  document required env in `docs/agentd.md`.
- NDJSON line limit: large tool outputs could exceed 10 MB — limit is
  configurable and `chat.delta` chunks keep stream lines small.
- Two daemons racing the same socket: mitigated by try-connect-then-unlink
  boot sequence (still TOCTOU-imperfect; acceptable for per-user sockets).
- MCP `invoke_method` towards an external LLM is powerful — hard
  requirement: allowlist (`exposed_methods`) must be non-empty for the
  tool to even be registered.
- `parrot ask` non-TTY output must not include ANSI (CI/pipe usage).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (none new) | — | rich, prompt_toolkit, click, pydantic, pyyaml come via `ai-parrot` core; scheduler support via optional `ai-parrot-server` install |

Packaging: new extra `ai-parrot-integrations[agentd]` (may be empty or
carry only markers; exists so the core CLI error message can name it).

---

## 8. Open Questions

Decisions resolved during the interactive brainstorm (conversation,
2026-08-16 — no separate brainstorm file):

- [x] ¿Proceso único o daemon + cliente? — *Resolved in brainstorm*: Opción B — daemon + cliente delgado; MCP stdio como cliente adicional del mismo socket.
- [x] ¿Un daemon por agente o multi-agente? — *Resolved in brainstorm*: 1 daemon = 1 agente; multi-agente queda cubierto por el servidor aiohttp.
- [x] ¿Protocolo interno? — *Resolved in brainstorm*: JSON-RPC 2.0 sobre Unix domain socket, NDJSON.
- [x] ¿Infraestructura del scheduler en modo daemon? — *Resolved in brainstorm*: fallback ligero — Postgres/Redis solo si están configurados; MemoryJobStore en su ausencia.
- [x] ¿Cómo se especifica el agente? — *Resolved in brainstorm*: ruta Python (`module:attr`) como base + archivo YAML de config encima.
- [x] ¿Alcance de la consola v1? — *Resolved in brainstorm*: streaming, slash commands (/status /schedules /invoke /tools /clear /quit), multilínea+historial, eventos de jobs intercalados, one-shot `parrot ask`.
- [x] ¿Daemonización? — *Resolved in brainstorm*: foreground puro + generador de unit files (`install-service`); sin double-fork.

Remaining:

- [ ] Naming of the lazy CLI keys: is plain `parrot serve` acceptable, or should it be namespaced (`parrot agentd serve`) to avoid future collisions in the shared LazyGroup? — *Owner: Jesus (decide at Module 9 task)*
- [ ] Should `chat.cancel` (stream cancellation RPC) land in v1 or be deferred? Protocol reserves `stream_id` correlation either way. — *Owner: implementer (default: defer)*
- [ ] Exact serialization for `agent.invoke` results that are not JSON-encodable (fallback `str()` vs error 1002-adjacent code). — *Owner: implementer (default: `_format_result`-style fallback as in manager.py)*

---

## Worktree Strategy

- **Isolation unit**: per-spec — one worktree
  (`feat-422-agent-cli-daemon`), tasks sequential.
- **Parallelizable exceptions**: Module 3 (scheduler headless refactor,
  ai-parrot-server) and Module 1 (protocol) touch disjoint files and could
  run in parallel first; everything else depends on them. Default remains
  sequential in one worktree.
- **Cross-feature dependencies**: none — does not touch `parrot.bots`,
  flows, or embeddings. No pending spec must merge first.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-16 | Jesus Lara (con Claude) | Initial spec from interactive brainstorm |

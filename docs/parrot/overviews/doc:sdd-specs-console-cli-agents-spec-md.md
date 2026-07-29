---
type: Wiki Overview
title: 'Feature Specification: Console CLI Agents'
id: doc:sdd-specs-console-cli-agents-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: When AI-Parrot runs as a webserver (`python run.py`), developers and operators
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.bots.base
  rel: mentions
- concept: mod:parrot.cli
  rel: mentions
- concept: mod:parrot.cli.agent_repl
  rel: mentions
- concept: mod:parrot.cli.repl
  rel: mentions
- concept: mod:parrot.manager.manager
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.registry.registry
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Console CLI Agents

**Feature ID**: FEAT-168
**Date**: 2026-05-13
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.next

---

## 1. Motivation & Business Requirements

### Problem Statement

When AI-Parrot runs as a webserver (`python run.py`), developers and operators
have no way to interact with registered agents from the terminal.  The only
interface is the web API (HTTP/WebSocket).  This forces users to write one-off
scripts or use `curl` to test agent behaviour, inspect tool lists, or run
quick ad-hoc conversations.

A CLI REPL would let any user run `parrot agent security_agent`, get dropped
into an interactive console (`security_agent> `), and talk to the agent
directly — with rich output, streaming, slash commands, and the same
`AgentRegistry` the server uses.

### Goals

- **G1**: Provide an interactive REPL for conversing with any registered agent
  via `parrot agent <name>`.
- **G2**: List all registered agents with metadata via `parrot agent --list`.
- **G3**: Support both standalone mode (no running server) and server mode
  (connect to running webserver via HTTP) in v1.
- **G4**: Deliver a rich console experience: streaming tokens, markdown
  rendering, coloured output, slash commands.
- **G5**: Use `questionary` for interactive agent selection when the name
  argument is omitted.
- **G6**: Support `/tools`, `/info`, `/clear`, `/export`, `/stream`, `/help`,
  `/quit` slash commands inside the REPL.

### Non-Goals (explicitly out of scope)

- Non-interactive / piping mode (`echo query | parrot agent ...`) — deferred
  to a future version.
- `--output-mode` CLI flag to override `TERMINAL` — not needed for v1.
- Persistent sessions across CLI restarts — ephemeral in-memory only for v1.
- Full TUI (Textual) — rejected in brainstorm (see
  `sdd/proposals/console-cli-agents.brainstorm.md` Option C).

---

## 2. Architectural Design

### Overview

The solution follows **Option B** from the brainstorm: Click for the CLI
command structure, `prompt_toolkit` for the async REPL with readline features,
and `rich` for response rendering.

Two execution modes are supported:

1. **Standalone mode** (default): imports `AgentRegistry` in-process, calls
   `get_instance(name)` to create the agent, runs `await agent.configure()`.
   No server required.
2. **Server mode** (`--server [url]`): connects to a running AI-Parrot server
   via HTTP, lists agents from the server's registry, and proxies `ask()`
   calls through the server API.

The REPL loop uses `prompt_toolkit.PromptSession.prompt_async()` for input
(history, tab completion, keybindings) and `rich.console.Console` for output
(markdown, panels, spinners, live streaming).

### Component Diagram

```
parrot agent <name> [--server URL] [--no-stream]
    │
    ├─ CLI layer (Click)
    │   └─ parrot/cli/agent_repl.py
    │       ├─ @click.command("agent")
    │       ├─ --list flag → list_agents()
    │       ├─ --server flag → ServerAgentProxy
    │       └─ (no flag) → StandaloneAgentLoader
    │
    ├─ Agent Loading
    │   ├─ StandaloneAgentLoader
    │   │   └─ AgentRegistry.get_instance(name) → AbstractBot
    │   └─ ServerAgentProxy
    │       └─ HTTP client → server /api/agent/{name}/ask
    │
    ├─ REPL Engine
    │   └─ AgentREPL
    │       ├─ prompt_toolkit.PromptSession (async)
    │       ├─ SlashCommandDispatcher
    │       │   └─ /tools, /info, /clear, /export, /stream, /help, /quit
    │       └─ ResponseRenderer (Rich)
    │           ├─ streaming: rich.live.Live + token accumulation
    │           └─ batch: rich.markdown.Markdown + rich.panel.Panel
    │
    └─ Agent Selection (when name omitted)
        └─ questionary.select() → agent name
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/cli.py` (LazyGroup) | extends | Add `agent` to lazy subcommands dict |
| `AgentRegistry.get_instance()` | uses | Standalone mode agent instantiation |
| `AbstractBot.ask()` | uses | Send prompts, receive `AIMessage` |
| `AbstractBot.ask_stream()` | uses | Streaming mode token delivery |
| `AbstractBot.configure()` | uses | Post-instantiation setup |
| `AbstractBot.get_available_tools()` | uses | `/tools` slash command |
| `OutputMode.TERMINAL` | uses | Default output mode for responses |
| `AIMessage` | consumes | Response model for rendering |
| `BotMetadata` | reads | Agent listing (name, tags, factory) |

### Data Models

```python
from dataclasses import dataclass, field
from typing import Optional, List
from parrot.models.responses import AIMessage


@dataclass
class REPLConfig:
    """Configuration for the agent REPL session."""
    agent_name: str
    streaming: bool = True
    server_url: Optional[str] = None
    session_id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = "cli-user"


@dataclass
class SlashCommand:
    """Registered slash command."""
    name: str
    description: str
    handler: Callable  # async def handler(repl: AgentREPL, args: str) -> None


@dataclass
class ConversationTurn:
    """Single turn in the conversation (for /export)."""
    query: str
    response: AIMessage
    timestamp: datetime
```

### New Public Interfaces

```python
class AgentREPL:
    """Interactive REPL for agent conversation."""

    def __init__(self, bot: AbstractBot, config: REPLConfig) -> None: ...
    async def run(self) -> None: ...
    async def send(self, query: str) -> AIMessage: ...
    async def send_stream(self, query: str) -> AsyncIterator: ...
    def register_command(self, cmd: SlashCommand) -> None: ...


class StandaloneAgentLoader:
    """Load agent from in-process AgentRegistry."""

    async def load(self, name: str) -> AbstractBot: ...
    async def list_agents(self) -> List[BotMetadata]: ...


class ServerAgentProxy:
    """Proxy agent calls to a running AI-Parrot server."""

    def __init__(self, server_url: str) -> None: ...
    async def load(self, name: str) -> AbstractBot: ...
    async def list_agents(self) -> List[dict]: ...
```

---

## 3. Module Breakdown

### Module 1: CLI Command Registration

- **Path**: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
- **Responsibility**: Click command `parrot agent` with `--list`, `--server`,
  `--no-stream` flags.  Entry point that resolves the agent (standalone or
  server), builds `REPLConfig`, and launches `AgentREPL.run()`.
- **Depends on**: Module 2, Module 3, Module 4

### Module 2: Agent Loading (Standalone + Server)

- **Path**: `packages/ai-parrot/src/parrot/cli/loaders.py`
- **Responsibility**: `StandaloneAgentLoader` wraps `AgentRegistry.get_instance()`
  with error handling and fuzzy name matching.  `ServerAgentProxy` implements
  the same interface over HTTP (`aiohttp.ClientSession`).  When no agent name
  is provided, uses `questionary.select()` to present a picker.
- **Depends on**: `parrot.registry.AgentRegistry`, `questionary`

### Module 3: REPL Engine

- **Path**: `packages/ai-parrot/src/parrot/cli/repl.py`
- **Responsibility**: `AgentREPL` class — the prompt_toolkit-based REPL loop.
  Handles input dispatch (slash command vs. agent query), streaming vs. batch
  mode, `Ctrl+C` cancellation, and `Ctrl+D` / `/quit` exit.
- **Depends on**: Module 4, Module 5, `prompt_toolkit`, `rich`

### Module 4: Slash Commands

- **Path**: `packages/ai-parrot/src/parrot/cli/commands.py`
- **Responsibility**: `SlashCommandDispatcher` with built-in commands:
  `/tools`, `/info`, `/clear`, `/export`, `/stream`, `/help`, `/quit`.
  Extensible via `register_command()`.
- **Depends on**: Module 5 (for rendering command output)

### Module 5: Response Renderer

- **Path**: `packages/ai-parrot/src/parrot/cli/renderer.py`
- **Responsibility**: Renders `AIMessage` to terminal via `rich.console.Console`.
  Streaming mode uses `rich.live.Live` with token accumulation.  Batch mode
  renders markdown, code blocks, tool call panels, and usage stats.
- **Depends on**: `rich`, `parrot.models.responses.AIMessage`

### Module 6: Tests

- **Path**: `packages/ai-parrot/tests/cli/`
- **Responsibility**: Unit and integration tests for all modules.
- **Depends on**: All modules

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_slash_command_dispatch` | Module 4 | Dispatch `/tools`, `/info`, etc. to correct handlers |
| `test_slash_command_unknown` | Module 4 | Unknown command prints help |
| `test_standalone_loader_success` | Module 2 | Loads known agent from registry |
| `test_standalone_loader_not_found` | Module 2 | Unknown agent raises error with suggestions |
| `test_standalone_loader_fuzzy_match` | Module 2 | Fuzzy name match suggests closest agent |
| `test_repl_config_defaults` | Module 3 | Default config (streaming=True, etc.) |
| `test_renderer_markdown` | Module 5 | AIMessage with markdown renders correctly |
| `test_renderer_tool_calls` | Module 5 | Tool calls render in panels |
| `test_renderer_usage_stats` | Module 5 | Token usage displayed when present |
| `test_export_json` | Module 4 | `/export` writes valid JSON conversation |
| `test_clear_resets_session` | Module 4 | `/clear` generates new session_id |

### Integration Tests

| Test | Description |
|---|---|
| `test_standalone_agent_roundtrip` | Load agent → configure → ask → receive AIMessage |
| `test_repl_slash_tools` | Start REPL mock → `/tools` → lists tools |
| `test_click_command_list` | `parrot agent --list` prints agent table |
| `test_click_command_agent` | `parrot agent test_bot` invokes REPL (mocked input) |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_agent():
    """A minimal AbstractBot mock for REPL testing."""
    agent = AsyncMock(spec=AbstractBot)
    agent.name = "test_agent"
    agent.get_available_tools.return_value = ["MathTool", "WebSearch"]
    agent.get_tools_count.return_value = 2
    agent.has_tools.return_value = True
    agent.ask.return_value = AIMessage(
        input="test", output="response", response="response",
        model="test", provider="test", usage=CompletionUsage(),
        output_mode=OutputMode.TERMINAL, ...
    )
    return agent


@pytest.fixture
def repl_config():
    return REPLConfig(agent_name="test_agent", streaming=False)
```

---

## 5. Acceptance Criteria

- [ ] `parrot agent --list` displays a Rich table of all registered agents
  with columns: Name, Class, LLM, Tools, Tags
- [ ] `parrot agent <name>` loads the agent via `AgentRegistry.get_instance()`,
  runs `configure()`, and drops into an interactive REPL
- [ ] When agent name is omitted, `questionary.select()` presents a picker
  of available agents
- [ ] The REPL prompt shows `<agent_name>> ` and sends input to `agent.ask()`
  with `output_mode=OutputMode.TERMINAL`
- [ ] Streaming mode (default): tokens appear incrementally via
  `agent.ask_stream()` rendered with `rich.live.Live`
- [ ] `--no-stream` flag: waits for full response, renders with Rich markdown
- [ ] `/tools` lists the agent's available tools
- [ ] `/info` shows agent name, class, LLM provider, model, session_id
- [ ] `/clear` resets conversation history (new session_id)
- [ ] `/export [path]` saves conversation as JSON
- [ ] `/stream` toggles streaming on/off
- [ ] `/help` lists all available slash commands
- [ ] `/quit` and `Ctrl+D` exit cleanly
- [ ] `Ctrl+C` during a response cancels it and returns to the prompt
- [ ] `--server URL` flag connects to a running server and proxies agent
  interactions via HTTP
- [ ] Agent not found: prints error with fuzzy-match suggestions
- [ ] Agent `configure()` failure: prints traceback and exits gracefully
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/cli/ -v`
- [ ] `prompt_toolkit>=3.0` added to `pyproject.toml` dependencies
- [ ] `agent` subcommand registered in `parrot/cli.py` LazyGroup

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# These imports have been confirmed to work:
from parrot.cli import cli                         # parrot/cli.py:28
from parrot.registry import agent_registry         # parrot/registry/__init__.py:7
from parrot.registry.registry import AgentRegistry, BotMetadata  # registry.py:228,42
from parrot.bots.abstract import AbstractBot       # bots/abstract.py:146
from parrot.bots.base import BaseBot               # bots/base.py:31
from parrot.models.outputs import OutputMode       # models/outputs.py:39
from parrot.models.responses import AIMessage      # models/responses.py:72
from parrot.manager.manager import BotManager      # manager/manager.py:86
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/cli.py
class LazyGroup(click.Group):  # line 10
    ...

@click.group(cls=LazyGroup)
def cli():  # line 28
    ...
# Registered subcommands (lines 34-40):
#   setup, conf, install, mcp, autonomous
```

```python
# packages/ai-parrot/src/parrot/registry/registry.py
@dataclass(slots=True)
class BotMetadata:  # line 42
    name: str
    factory: Union[Type[AbstractBot], AgentFactory]
    module_path: str
    file_path: Path
    singleton: bool = False
    tags: Optional[Set[str]] = field(default_factory=set)
    priority: int = 0
    at_startup: bool = False
    dependencies: List[str] = field(default_factory=list)
    startup_config: Dict[str, Any] = field(default_factory=dict)
    bot_config: Optional[Any] = None

    async def get_instance(self, **kwargs) -> AbstractBot:  # line 78
        # Thread-safe instantiation; calls await instance.configure() at line 182
        ...

class AgentRegistry:  # line 228
    def __init__(
        self,
        agents_dir: Optional[Path] = None,
        *,
        extra_agent_dirs: Optional[Iterable[Path]] = None,
    ):  # line 267
        self._registered_agents: Dict[str, BotMetadata] = {}  # line 275

    async def get_instance(
        self,
        name: str,
        request: Optional[web.Request] = None,
        **kwargs,
    ) -> Optional[AbstractBot]:  # line 600
        ...
```

```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin,
                  ToolInterface, VectorInterface):  # line 146
    def __init__(
        self,
        name: str = 'Nav',
        output_mode: OutputMode = OutputMode.DEFAULT,
        ...
    ):  # line 237

    async def configure(self, app=None) -> None:  # line 1131

    def get_available_tools(self) -> List[str]:  # line 3290
    def get_tools_count(self) -> int:  # line 3281
    def has_tools(self) -> bool:  # line 3286
```

```python
# packages/ai-parrot/src/parrot/bots/base.py
class BaseBot(AbstractBot):  # line 31

    async def ask(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        output_mode: OutputMode = OutputMode.DEFAULT,
        **kwargs
    ) -> AIMessage:  # line 717

    async def ask_stream(self, ...) -> AsyncIterator:  # line 1233
```

```python
# packages/ai-parrot/src/parrot/models/outputs.py
class OutputMode(str, Enum):  # line 39
    DEFAULT = "default"
    TERMINAL = "terminal"
    MARKDOWN = "markdown"
    JSON = "json"
    TABLE = "table"
    # ... (30+ modes)
```

```python
# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):  # line 72
    input: str
    output: Any
    response: Optional[str]
    data: Optional[Any]
    tool_calls: List[ToolCall]
    usage: CompletionUsage
    model: str
    provider: str
    output_mode: OutputMode
    metadata: Dict[str, Any]
    created_at: datetime
    response_time: Optional[float]
    # ... (many more fields)
```

```python
# packages/ai-parrot/src/parrot/manager/manager.py
class BotManager:  # line 86
    def __init__(self, ...):  # line 95
        self._bots: Dict[str, AbstractBot]
        self.registry: AgentRegistry  # line 126

    async def get_bot(
        self,
        name: str,
        new: bool = False,
        session_id: str = "",
        **kwargs
    ) -> AbstractBot:  # line 601

    def get_bots(self) -> Dict[str, AbstractBot]:  # line 848
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `agent_repl.py` (Click cmd) | `cli.py` LazyGroup | subcommand registration | `cli.py:34-40` |
| `StandaloneAgentLoader` | `AgentRegistry.get_instance()` | method call | `registry.py:600` |
| `AgentREPL.send()` | `BaseBot.ask()` | method call | `base.py:717` |
| `AgentREPL.send_stream()` | `BaseBot.ask_stream()` | method call | `base.py:1233` |
| `/tools` command | `AbstractBot.get_available_tools()` | method call | `abstract.py:3290` |
| `ResponseRenderer` | `AIMessage` | model consumption | `responses.py:72` |
| Agent listing | `BotMetadata.name`, `.tags` | attribute reads | `registry.py:42-48` |
| Agent selection | `questionary.select()` | library call | `questionary>=2.1.1` in deps |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.cli.agent`~~ — no existing `agent` subcommand in cli.py
- ~~`parrot.repl`~~ — no existing REPL module
- ~~`parrot.cli.repl`~~ — no existing `cli/` subpackage (must be created)
- ~~`AbstractBot.repl()`~~ — no REPL method on bots
- ~~`OutputMode.CONSOLE`~~ — use `TERMINAL`, not `CONSOLE`
- ~~`OutputMode.CLI`~~ — does not exist; use `TERMINAL`
- ~~`prompt_toolkit`~~ — NOT currently in deps (must be added to pyproject.toml)
- ~~`AgentRegistry.list_agents()`~~ — no such method; iterate `_registered_agents`
- ~~`AbstractBot.history`~~ — no conversation history attribute; history managed
  internally by `ask()` via `session_id`
- ~~`AbstractBot.stream()`~~ — the method is `ask_stream()`, not `stream()`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Register the `agent` subcommand in `cli.py`'s LazyGroup dict following the
  existing pattern (lines 34-40): `"agent": "parrot.cli.agent_repl"`.
- Use `asyncio.run()` at the Click command boundary to enter the async world,
  matching the pattern in `examples/basic_agent.py`.
- Use `prompt_toolkit.patch_stdout.patch_stdout()` context manager so Rich
  output doesn't corrupt the prompt_toolkit display.
- All `ask()` / `ask_stream()` calls pass `output_mode=OutputMode.TERMINAL`.
- Use `self.logger = logging.getLogger(__name__)` in all classes.
- Pydantic models for `REPLConfig` and `ConversationTurn`.

### Known Risks / Gotchas

| Risk | Mitigation |
|------|------------|
| `prompt_toolkit` rendering conflicts with `rich` | Use `patch_stdout()` context manager — documented integration pattern |
| Agent `configure()` may require env vars (API keys) that are missing | Catch exceptions, print which config is missing, exit with code 1 |
| `AgentRegistry` loads agents from YAML; YAML may reference DB-only agents | Catch and report gracefully; suggest `--server` for DB-configured agents |
| `Ctrl+C` during streaming may leave partial output | Wrap stream loop in `try/except KeyboardInterrupt`, print newline |
| Server mode: server may be unreachable | `aiohttp.ClientSession` with timeout; print connection error |
| Empty input (just Enter) should not call the LLM | Check `input.strip()` before dispatching |

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `prompt_toolkit` | `>=3.0` | Async REPL with readline features, history, completion |
| `click` | `>=8.1.7` | CLI command structure (already in deps) |
| `rich` | `>=13.0` | Console output, markdown, panels, live streaming (already in deps) |
| `questionary` | `>=2.1.1` | Interactive agent picker when name omitted (already in deps) |

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: The modules are tightly coupled (CLI command → loader →
  REPL → commands → renderer) and share the new `parrot/cli/` subpackage.
  Parallel worktrees would create merge conflicts on the same new files.
- **Cross-feature dependencies**: None.  This feature only adds a new `agent`
  entry in `cli.py`'s LazyGroup and creates new files under `parrot/cli/`.

---

## 8. Open Questions

- [x] Should the `--server` flag be in scope for v1, or deferred? —
  *Resolved in brainstorm*: in scope for v1
- [x] Should `/export` save as JSON or Markdown, or both? —
  *Resolved in brainstorm*: JSON
- [x] Should there be an `--output-mode` CLI flag? —
  *Resolved in brainstorm*: no
- [x] Is `questionary` useful for agent selection when name is omitted? —
  *Resolved in brainstorm*: yes, questionary is useful

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-13 | Jesus Lara | Initial draft from brainstorm |

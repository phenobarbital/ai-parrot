---
type: Wiki Overview
title: 'Brainstorm: Console CLI Agents'
id: doc:sdd-proposals-console-cli-agents-brainstorm-md
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

# Brainstorm: Console CLI Agents

**Date**: 2026-05-13
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

When AI-Parrot runs as a webserver (`python run.py`), developers and operators
have no way to interact with registered agents from the terminal.  The only
interface is the web API (HTTP/WebSocket).  This forces users to write one-off
scripts or use `curl` to test agent behaviour, inspect tool lists, or run
quick ad-hoc conversations.

A CLI REPL would let any user run `parrot agent security_agent`, get dropped
into an interactive console (`security_agent> `), and talk to the agent
directly — with rich output, streaming, slash commands, and the same
`AgentRegistry` the server uses.  This is valuable for:

- **Developers** testing agents locally without spinning up the full web stack.
- **Operators** debugging production agent configs via SSH.
- **DevOps / SRE** running one-off queries against agents in deployed environments.

## Constraints & Requirements

- Must use **Click** (`>=8.1.7`, already in deps) for the CLI command structure.
- Must use the existing **`AgentRegistry`** for agent lookup — same registry
  YAML, same `BotMetadata`, same `get_instance()` path.
- **Standalone mode**: must work without a running webserver — import
  `AgentRegistry` in-process and call `get_instance()` directly.
- **Server mode**: optionally connect to a running server's registry via HTTP
  to list/interact with agents that are already configured.
- Rich terminal output using **`rich`** (`>=13.0`, already in deps).
- **Streaming** via `ask_stream()` is the default; `--no-stream` flag falls
  back to `ask()` with full-response rendering.
- **Ephemeral sessions** (v1) — conversation history in memory, lost on exit.
- **Interactive only** (v1) — no piping or single-shot mode.
- Slash commands: `/tools`, `/clear`, `/info`, `/export`, `/quit`.
- `OutputMode.TERMINAL` for agent responses.
- async/await throughout — run the REPL inside an asyncio event loop.

---

## Options Explored

### Option A: Click + raw `input()` loop with Rich panels

Use Click for the `parrot agent <name>` command, then run a simple `while True`
loop calling `input()` (or `asyncio` equivalent) for user input.  Render
responses via `rich.console.Console` with panels and markdown.

The REPL loop would be a plain `async for` over `input()` wrapped in
`asyncio.to_thread()`.  Slash commands are parsed with a simple prefix check.

Pros:
- Zero new dependencies — Click + Rich are already available.
- Minimal code surface (~200-300 lines).
- Easy to understand and maintain.
- Works in any terminal, including SSH sessions.

Cons:
- No readline-style features (history, tab completion, emacs/vi keybindings)
  unless manually wired via the `readline` stdlib module.
- No multiline input support.
- No syntax highlighting or intelligent prompt handling.
- `input()` blocks the thread — needs `asyncio.to_thread()` wrapping.
- Feels bare-bones compared to modern CLI tools.

Effort: Low

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `click>=8.1.7` | CLI command structure | Already in deps |
| `rich>=13.0` | Console output, markdown, panels, live display | Already in deps |

Existing Code to Reuse:
- `parrot/cli.py` — LazyGroup pattern for registering the `agent` subcommand
- `parrot/registry/registry.py:600` — `AgentRegistry.get_instance()`
- `parrot/bots/abstract.py:717` — `ask()` method
- `parrot/outputs/formatter.py` — existing output formatting

---

### Option B: Click + prompt_toolkit REPL with Rich rendering

Use Click for the outer command, then launch a `prompt_toolkit`-based
async REPL for the interactive session.  `prompt_toolkit` provides readline
features (history, autocompletion, multiline, keybindings) natively with
async support.  Render agent responses through `rich.console.Console`.

The REPL uses `prompt_toolkit.PromptSession` with:
- Custom `completer` for slash commands and agent names.
- In-memory history (v1), extensible to file-based later.
- `prompt_toolkit_patch_stdout()` so Rich output doesn't corrupt the prompt.
- Async integration via `prompt_toolkit`'s native `prompt_async()`.

Pros:
- Full readline experience: history navigation, tab completion, emacs/vi keys.
- Native async support — no `asyncio.to_thread()` hack for input.
- Multiline input via `Meta+Enter` or configurable key bindings.
- Slash command autocompletion out of the box.
- `prompt_toolkit` is battle-tested (used by IPython, pgcli, mycli, xonsh).
- Clean separation: prompt_toolkit handles input, Rich handles output.

Cons:
- Adds one new dependency (`prompt_toolkit>=3.0`).
- Slightly more code (~400-500 lines) for the REPL harness.
- prompt_toolkit has its own rendering engine which can conflict with Rich
  if not patched correctly (solved by `patch_stdout`).

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `click>=8.1.7` | CLI command structure | Already in deps |
| `rich>=13.0` | Console output, markdown, panels, live, spinner | Already in deps |
| `prompt_toolkit>=3.0` | Async REPL, history, completion, keybindings | New dep, ~MIT, widely used |

Existing Code to Reuse:
- `parrot/cli.py` — LazyGroup pattern for registering the `agent` subcommand
- `parrot/registry/registry.py:600` — `AgentRegistry.get_instance()`
- `parrot/bots/abstract.py:717` — `ask()` and `ask_stream()` methods
- `parrot/models/outputs.py:39` — `OutputMode.TERMINAL`
- `parrot/outputs/formatter.py` — output formatting

---

### Option C: Textual TUI (terminal user interface)

Build a full terminal UI with `textual` (by the Rich author).  This gives a
structured layout: a scrollable chat panel, a status bar with agent info/tools,
an input area at the bottom, and a sidebar for tool call visibility.

Pros:
- Professional, polished experience — closer to a real chat client.
- Built-in scrolling, focus management, mouse support.
- Can show tool calls in a side panel while streaming the response.
- `textual` is from the same author as `rich`, so style consistency is free.
- Would differentiate AI-Parrot from other frameworks.

Cons:
- Adds a heavy dependency (`textual>=0.50`).
- Significantly more effort — TUI layout, widget composition, event handling.
- Overkill for operators SSHing into servers (may not render well over SSH).
- Harder to test (TUI testing requires `textual`'s pilot framework).
- Scope creep risk — TUI features tend to expand.

Effort: High

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `click>=8.1.7` | CLI command structure | Already in deps |
| `textual>=0.50` | Terminal UI framework | New dep, heavy, MIT |
| `rich>=13.0` | Underlying rendering | Already in deps |

Existing Code to Reuse:
- `parrot/cli.py` — LazyGroup pattern
- `parrot/registry/registry.py:600` — `AgentRegistry.get_instance()`
- `parrot/bots/abstract.py:717` — `ask()` and `ask_stream()`

---

## Recommendation

**Option B** is recommended because:

- It provides the **right balance** between user experience and implementation
  effort.  The readline features (history, completion, keybindings) make the
  REPL feel professional without the scope and complexity of a full TUI.
- `prompt_toolkit` is the standard for Python REPLs — IPython, pgcli, and
  mycli all use it.  The library is mature (10+ years), well-maintained, and
  has native async support that fits AI-Parrot's event loop.
- Adding one dependency (`prompt_toolkit>=3.0`) is a low cost for what it
  provides.  Option A would eventually need these features anyway, leading
  to ad-hoc reimplementation.
- Option C (Textual TUI) is attractive but its effort/risk ratio is too high
  for v1.  It can be explored as a v2 upgrade later — the REPL architecture
  from Option B would still be reusable as the backend.

**Tradeoff**: we accept one new dependency in exchange for a dramatically
better input experience.  The output side uses Rich exclusively (already
in deps), so no additional cost there.

---

## Feature Description

### User-Facing Behavior

**1. Entry point**: `parrot agent <agent-name>` (or `parrot agent --list` to
see all registered agents).

```
$ parrot agent security_agent
 Loading agent: security_agent ...
 Agent: SecurityAgent (llm: google, tools: 5)

security_agent> What vulnerabilities should I check for in a Django app?
```

**2. Agent listing**: `parrot agent --list` prints a table of registered agents
with name, class, LLM provider, tool count, and tags.

```
$ parrot agent --list
 Registered Agents
┌──────────────────┬─────────────┬──────────┬───────┬────────────┐
│ Name             │ Class       │ LLM      │ Tools │ Tags       │
├──────────────────┼─────────────┼──────────┼───────┼────────────┤
│ security_agent   │ BasicAgent  │ google   │ 5     │ security   │
│ hr_assistant     │ Chatbot     │ openai   │ 3     │ hr         │
│ data_analyst     │ BasicAgent  │ claude   │ 8     │ data       │
└──────────────────┴─────────────┴──────────┴───────┴────────────┘
```

**3. Interactive REPL**: after loading, the user types messages that are sent
to `agent.ask()` (or `agent.ask_stream()` in streaming mode).  Responses are
rendered with Rich (markdown, code blocks, tables).

**4. Slash commands**:

| Command | Behaviour |
|---------|-----------|
| `/tools` | List agent's available tools with descriptions |
| `/info` | Show agent metadata (name, class, LLM, model, session_id) |
| `/clear` | Reset conversation history (new session_id) |
| `/export [path]` | Save conversation to JSON file |
| `/stream` | Toggle streaming on/off |
| `/quit` or `/exit` | Exit the REPL (also `Ctrl+D`) |
| `/help` | Show available commands |

**5. Streaming**: by default, tokens stream to the terminal as they arrive
(using `rich.live.Live`).  `--no-stream` flag or `/stream` command toggles
to full-response rendering.

**6. Standalone mode**: when no server is running, the CLI imports
`AgentRegistry` directly, loads agent config from YAML, instantiates the
agent, and calls `await agent.configure()`.  The experience is identical.

### Internal Behavior

```
parrot agent <name>
    │
    ├─ 1. Import AgentRegistry (or connect to server if --server flag)
    │
    ├─ 2. AgentRegistry.get_instance(name) → AbstractBot
    │     ├─ BotMetadata.get_instance() creates instance
    │     └─ await instance.configure()
    │
    ├─ 3. Build PromptSession (prompt_toolkit)
    │     ├─ Completer: slash commands
    │     ├─ History: InMemoryHistory
    │     └─ Style: custom prompt style
    │
    ├─ 4. REPL loop
    │     ├─ user_input = await session.prompt_async(f"{name}> ")
    │     │
    │     ├─ if starts with "/":
    │     │     dispatch_slash_command(input)
    │     │
    │     ├─ elif streaming:
    │     │     async for chunk in agent.ask_stream(input, output_mode=TERMINAL):
    │     │         rich_console.print(chunk)
    │     │
    │     └─ else:
    │           response: AIMessage = await agent.ask(input, output_mode=TERMINAL)
    │           render_response(response)
    │
    └─ 5. Cleanup on exit (Ctrl+D or /quit)
```

**Key responsibilities**:
- `parrot/cli.py` → registers `agent` subcommand via LazyGroup
- New `parrot/cli/agent_repl.py` → Click command + REPL loop + slash commands
- Uses `AgentRegistry.get_instance()` for both standalone and server modes
- `rich.console.Console` for all output rendering
- `prompt_toolkit.PromptSession` for input with async support

### Edge Cases & Error Handling

| Scenario | Handling |
|----------|----------|
| Agent not found in registry | Print error with closest matches (fuzzy), list available agents |
| Agent `configure()` fails | Print traceback via Rich, suggest checking config/env vars |
| LLM provider unavailable | Catch `ClientError`, print friendly message with provider name |
| Tool execution fails mid-conversation | Show tool error in a Rich panel, continue conversation |
| `Ctrl+C` during response | Cancel current `ask()` / stream, return to prompt |
| `Ctrl+D` at prompt | Clean exit |
| Empty input | Skip silently (no API call) |
| Very long response | Rich handles terminal wrapping; streaming keeps output live |
| No agents registered | Print message suggesting config check, exit gracefully |
| Missing env vars (API keys) | Catch on `configure()`, print which vars are missing |

---

## Capabilities

### New Capabilities
- `cli-agent-repl`: Interactive REPL for conversing with registered agents
- `cli-agent-list`: List all registered agents with metadata table
- `cli-slash-commands`: REPL meta-commands (/tools, /info, /clear, /export, /help)

### Modified Capabilities
- `cli-entry-point`: Extends `parrot/cli.py` LazyGroup with new `agent` subcommand

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/cli.py` | extends | Add `agent` to LazyGroup subcommands |
| `parrot/registry/registry.py` | depends on | Uses `AgentRegistry.get_instance()` |
| `parrot/bots/abstract.py` | depends on | Uses `ask()`, `ask_stream()`, `configure()` |
| `parrot/models/outputs.py` | depends on | Uses `OutputMode.TERMINAL` |
| `parrot/models/responses.py` | depends on | Consumes `AIMessage` |
| `pyproject.toml` | modifies | Adds `prompt_toolkit>=3.0` dependency |
| `parrot/outputs/formatter.py` | depends on | May reuse for response formatting |

No breaking changes.  No data model changes.  No deployment changes.

---

## Code Context

### User-Provided Code

(No code snippets provided by user during discovery.)

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/cli.py:28
class LazyGroup(click.Group):
    # Lazy-loading Click group for subcommands
    ...

@click.group(cls=LazyGroup)
def cli():  # line 28
    ...
# Registered subcommands (lines 34-40):
#   setup, conf, install, mcp, autonomous
```

```python
# From packages/ai-parrot/src/parrot/registry/registry.py:228
class AgentRegistry:
    def __init__(
        self,
        agents_dir: Optional[Path] = None,
        *,
        extra_agent_dirs: Optional[Iterable[Path]] = None,
    ):  # line 267
        self._registered_agents: Dict[str, BotMetadata] = {}  # line 275
        ...

    async def get_instance(
        self,
        name: str,
        request: Optional[web.Request] = None,
        **kwargs,
    ) -> Optional[AbstractBot]:  # line 600
        ...
```

```python
# From packages/ai-parrot/src/parrot/registry/registry.py:42
@dataclass(slots=True)
class BotMetadata:
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
        # Thread-safe instantiation with singleton support
        # Line 182: await instance.configure()
        ...
```

```python
# From packages/ai-parrot/src/parrot/bots/abstract.py:146
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, ToolInterface, VectorInterface):
    def __init__(
        self,
        name: str = 'Nav',
        output_mode: OutputMode = OutputMode.DEFAULT,
        ...
    ):  # line 237
        ...

    async def configure(self, app=None) -> None:  # line 1131
        ...

    def get_available_tools(self) -> List[str]:  # line 3290
        ...
    def get_tools_count(self) -> int:  # line 3281
        ...
    def has_tools(self) -> bool:  # line 3286
        ...
```

```python
# From packages/ai-parrot/src/parrot/bots/base.py:31
class BaseBot(AbstractBot):
    async def ask(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        output_mode: OutputMode = OutputMode.DEFAULT,
        **kwargs
    ) -> AIMessage:  # line 717
        ...

    async def ask_stream(
        self,
        ...
    ) -> AsyncIterator[...]:  # line 1233
        ...
```

```python
# From packages/ai-parrot/src/parrot/models/outputs.py:39
class OutputMode(str, Enum):
    DEFAULT = "default"
    TERMINAL = "terminal"
    MARKDOWN = "markdown"
    JSON = "json"
    TABLE = "table"
    # ... (30+ modes)
```

```python
# From packages/ai-parrot/src/parrot/models/responses.py:72
class AIMessage(BaseModel):
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
# From packages/ai-parrot/src/parrot/manager/manager.py:86
class BotManager:
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
        ...

    def get_bots(self) -> Dict[str, AbstractBot]:  # line 848
        ...
```

#### Verified Imports

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

#### Key Attributes & Constants

- `AgentRegistry._registered_agents` → `Dict[str, BotMetadata]` (registry.py:275)
- `BotMetadata.name` → `str` (registry.py:43)
- `BotMetadata.tags` → `Optional[Set[str]]` (registry.py:48)
- `BotMetadata.factory` → `Union[Type[AbstractBot], AgentFactory]` (registry.py:44)
- `AbstractBot.name` → `str` (abstract.py:237)
- `AIMessage.output` → `Any` (responses.py:74)
- `AIMessage.tool_calls` → `List[ToolCall]` (responses.py:87)
- `AIMessage.usage` → `CompletionUsage` (responses.py:82)
- `OutputMode.TERMINAL` → `"terminal"` (outputs.py:42)

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.cli.agent`~~ — no existing `agent` subcommand in cli.py
- ~~`parrot.repl`~~ — no existing REPL module
- ~~`AbstractBot.repl()`~~ — no REPL method on bots
- ~~`OutputMode.CONSOLE`~~ — there is `TERMINAL`, not `CONSOLE`
- ~~`OutputMode.CLI`~~ — does not exist; use `TERMINAL`
- ~~`prompt_toolkit`~~ — NOT currently in deps (must be added)
- ~~`AgentRegistry.list_agents()`~~ — no such method; iterate `_registered_agents`
- ~~`AbstractBot.history`~~ — no conversation history attribute; history is managed by `ask()` internally via session_id

---

## Parallelism Assessment

- **Internal parallelism**: Limited — the CLI command, REPL loop, slash commands,
  and response renderer are tightly coupled.  The agent listing subcommand could
  be developed independently from the REPL, but it's ~50 lines.  Best worked
  sequentially in one worktree.
- **Cross-feature independence**: High — this feature touches only `cli.py` (one
  line to add the subcommand) and adds new files.  No conflicts with in-flight
  ontology/RAG/MCP specs.
- **Recommended isolation**: `per-spec` (all tasks sequential in one worktree)
- **Rationale**: The tasks share the REPL module and build on each other (command
  → REPL → slash commands → streaming).  Parallel worktrees would create merge
  conflicts on the same new files.

---

## Open Questions

- [x] Should the `--server` flag (connect to running server via HTTP) be in scope
  for v1, or deferred? — *Owner: Jesus*: in scope for v1
- [x] Should `/export` save as JSON (machine-readable) or Markdown (human-readable),
  or both? — *Owner: Jesus*: json
- [x] Should there be an `--output-mode` CLI flag to override the default
  `TERMINAL` mode (e.g., `--output-mode json` for scripting)? — *Owner: Jesus*: no
- [x] Is `questionary` (already in deps) useful for agent selection when name
  is omitted (interactive picker), or is `--list` + explicit name sufficient? — *Owner: Jesus*: questionary useful.

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Agent Terminal Workspace for `parrot agent`

**Feature ID**: FEAT-573
**Date**: 2026-09-18
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.next

> **Source**: `sdd/proposals/new-ui-cli-agents.brainstorm.md` (accepted 2026-09-18,
> Recommended Option **B — Native Textual Agent Workspace**, all seven open
> questions resolved). This spec **absorbs and supersedes FEAT-519**
> (`sdd/specs/new-cli-infra.spec.md`, draft, never decomposed): its inline
> fixes become this feature's inline mode, and its Textual rejection (U1) is
> reversed by explicit user decision. Design research transcript:
> `sdd/state/FEAT-573/design_research/`.

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot agent {agent_id}` should feel like an interactive agent application: a
usable composer, readable conversation, discoverable commands, and visible
progress. The current implementation already uses Rich for completed answers
and prompt_toolkit for input, but its default streaming path writes raw text to
stdout (`renderer.py:257`), so the good Markdown renderer is reachable only via
`--no-stream`. Three point workarounds stack on that seam instead of a fix
(`Console(file=sys.__stdout__)` at `agent_repl.py:25`/`repl.py:128`/`renderer.py:80`,
`_BlockingSafeFile` at `renderer.py:22-56`, `_mute_stream_loggers` at
`repl.py:33-58`). Adding Rich alone therefore does not address the request.

The users are developers and operators interacting with registered Parrot
agents. A successful first version keeps input and navigation responsive during
generation, renders Markdown consistently, shows tool activity while it happens,
resumes a prior conversation, and recovers cleanly from cancellation and errors.

Two further defects surfaced during research and are in scope because the
accepted design cannot work without fixing them:

- **Server mode targets routes that do not exist.** `_ServerBotProxy` posts to
  `/api/agent/{name}/ask` and lists via `/api/agents` (`loaders.py:233`, `:394`,
  `:424`); the server registers neither (`manager/manager.py:2285-2290`,
  `:2482`, `:2493`). Its "streaming" is a locally simulated 50-character
  chunker over a completed answer (`loaders.py:274-288`).
- **No live tool progress reaches any presenter.** `BaseBot.ask_stream` yields
  `str` deltas and one final `AIMessage` (`bots/base.py:1990-2004`, `:2127`);
  tool activity is visible only in the final `AIMessage.tool_calls`. The
  lifecycle event system already emits `BeforeToolCallEvent` /
  `AfterToolCallEvent` / `ToolCallFailedEvent` from `AbstractTool.execute()`
  (`tools/abstract.py:946`, `:1130`, `:1172`) — nobody in the CLI subscribes.

### Goals

- **G1 — Workspace.** A full-screen Textual application: scrollable transcript
  with auto-follow, persistent multiline composer, collapsible tool details,
  slash-command completion, status/footer showing *waiting* vs *streaming* vs
  *running tool*. (Brainstorm capability `agent-terminal-workspace`.)
- **G2 — Mode selection.** `--ui auto|inline|tui`, default `auto`: TUI when
  stdin and stdout are TTYs and `TERM` is not `dumb`, inline Rich otherwise.
  Non-TTY never emits full-screen escapes, never opens the picker, and reads
  queries line by line. (`agent-ui-mode-selection`.)
- **G3 — One turn lifecycle for both presenters.** A presentation-neutral
  `TurnEvent` stream (deltas, tool started/finished/failed, completed, failed,
  cancelled) produced by one `TurnRunner`, consumed by the inline REPL and the
  TUI alike. (`agent-turn-presentation`.)
- **G4 — Live tool progress.** Standalone and server backends surface tool
  events while tools run, correlated to the active turn; backends without the
  capability degrade to final tool details.
- **G5 — Conversation resume.** `--session <id|last>` and `/resume` re-render a
  prior session from bot-owned memory (`AbstractBot.get_conversation_history`,
  `bots/abstract.py:2360`) without inventing a parallel store.
- **G6 — Persistent input history.** Composer history survives launches, per
  agent, under the parrot home directory; distinct from conversation resume.
- **G7 — Inline fixes absorbed from FEAT-519.** Shared `Console`, `LiveRegion`
  "one writer at a time" discipline extracted from `devloop/renderer.py:82-107`,
  streamed Markdown at batch fidelity, real post-turn hook for `agentd`, the
  three stacked workarounds deleted, logs never interleave by construction.
- **G8 — Canonical server transport.** Server mode uses routes the server
  actually registers, with typed SSE frames carrying deltas, tool events and
  the final message.
- **G9 — Explicit cancellation.** Ctrl+C during a turn cancels the active task,
  closes the stream, keeps the partial answer visibly marked *interrupted*, and
  never records the cancelled turn as completed.
- **G10 — Preserve contracts.** `parrot agent <name>`, optional picker, `--list`,
  `--server`, `--no-stream`, every slash command's data contract (`/clear`
  resets the session, `/export` JSON shape), identity propagation
  (`session_id`, `user_id`, `OutputMode.TERMINAL`, `permission_context`), and
  the FEAT-266 device-code bootstrap are unchanged in behaviour.

### Non-Goals (explicitly out of scope)

- **Toad / ACP adapter** (brainstorm Option C) and a **prompt_toolkit
  full-screen app** (Option D) — rejected in brainstorm; Toad requires
  Python ≥3.14, outside `requires-python >=3.11,<3.14` (`pyproject.toml:18`).
- **Embedded shell, file attachments, session switching, concurrent
  sessions** — resolved out of v1 in the brainstorm.
- **FEAT-519 G7 / Module 5 (generalised `cli/wizard.py`)** — not needed by the
  workspace; deferred to a follow-up spec. Everything else in FEAT-519
  (Modules 1–4, 6, 7, 8) is absorbed here.
- **Migrating the `parrot/human/` HITL surface** (FEAT-519 D2) — unchanged;
  `/create_agent` keeps using `CLIHumanChannel` through a controlled screen
  suspension (§2).
- **Live tool events over the agentd protocol.** The daemon stream yields only
  `delta` / `complete` / `error` (`agentd/client.py:98`); the daemon backend
  reports `live_tool_events=False` and shows final tool details. Adding a
  `chat.tool_event` notification is a separate agentd feature.
- **A server-side conversation-history endpoint.** None exists; resume is
  standalone-only in v1 (see §8 Q9).
- **A new authentication transport for server mode beyond a bearer token**
  (see §8 Q8).
- `cli/tool_worker.py` (`sys.stdout.write` there is an IPC protocol) and
  `parrot/clients/*` are untouched.

---

## 2. Architectural Design

### Overview

The feature is layered so that **the UI never becomes a second agent
implementation**:

1. **Shared console layer** — `parrot/cli/console.py` (new): `get_console()`
   singleton and `LiveRegion` (start/stop/pause/resume/update + `modal()`),
   extracted from devloop's proven `RunView.pause/resume` pattern
   (`devloop/renderer.py:82-107`). `LiveRegion` degrades to sequential printing
   when the console is not a terminal. This is FEAT-519 Module 1, verbatim in
   intent.
2. **Mode + state** — `parrot/cli/modes.py` (new): `UIMode`, `resolve_ui_mode()`,
   `cli_state_dir()` (honours `PARROT_HOME`, default `~/.parrot`, same
   convention as `knowledge/wiki/project.py:1009` and `conf.py:556`), the
   per-agent input-history path and the per-agent `SessionPointer` file.
3. **Turn events + runner** — `parrot/cli/events.py` (new) defines the Pydantic
   `TurnEvent` union and `BackendCapabilities`; `parrot/cli/session.py` (new)
   defines `TurnRunner`, the *single* execution boundary: it calls
   `bot.ask()` / `bot.ask_stream()` with the identity kwargs the REPL passes
   today (`repl.py:212-218`, `:249-255`), converts `str`/`AIMessage` yields into
   `TextDelta`/`TurnCompleted`, owns the cancellable active task, subscribes to
   the global lifecycle registry for tool events **scoped to the active turn**,
   records display history, runs post-turn hooks, and loads prior history for
   resume.
4. **Turn scope** — `parrot/core/events/lifecycle/turn_scope.py` (new, core):
   a `ContextVar` set around each turn plus a `where=` predicate factory. Tool
   events are emitted from within the turn's task tree, and both `emit_nowait`
   and global forwarding use `loop.create_task()` (navigator-eventbus 0.3.0,
   verified), which copies the emitter's context — so the predicate isolates
   exactly this turn's tool events, in the CLI *and* in a multi-tenant server.
   This is the correlation mechanism; trace ids are **not** used for filtering
   because a tool mints a fresh root trace whenever no `PermissionContext`
   carries one (`tools/abstract.py:938-939`).
5. **Presenters** — inline: `AgentREPL` (`repl.py`) + `ResponseRenderer`
   (`renderer.py`) now consume `TurnEvent`s and render inside a `LiveRegion`;
   TUI: `parrot/cli/tui/` (new package) `AgentWorkspaceApp` with transcript,
   composer, tool panels, status bar, log drawer. Both implement one
   `CommandContext` protocol so slash commands stay shared (`commands.py`).
6. **Backends** — standalone (`StandaloneAgentLoader`, unchanged),
   server (`ServerAgentProxy` / `_ServerBotProxy` rewritten against
   `GET /api/v1/bots`, `GET /api/v1/chatbots/{name}`,
   `POST /api/v1/agents/chat/{agent_id}`, `POST /bots/{bot_id}/stream/sse`,
   bearer token), daemon (`_DaemonBotProxy`, adapted; `attach` uses the new
   post-turn hook). `StreamHandler.stream_sse` gains `tool_event` frames.
7. **Entry point** — `agent_repl.py` gains `--ui`, `--session`, `--user`,
   `--token`, resolves the mode, and lazily imports the TUI only when chosen.

Resolved brainstorm decisions reflected here: Textual is the UI framework
(new core dependency `textual>=8.2,<9`, resolver-verified: `uv pip install
--dry-run textual` → 8.2.8 against rich 15.0.0); `--ui auto` default with the
non-TTY rules above; v1 includes core workspace + persistent input history +
conversation resume + live tool progress; cancellation is local (no remote
rollback claimed); FEAT-519 is superseded, not layered.

### Component Diagram

```
 parrot agent <name> [--ui auto|inline|tui] [--session ID|last] [--server URL --token T]
        │  agent_repl.py — resolve_ui_mode(), load bot, banner, permission ctx
        ▼
 ┌──────────────────────── parrot/cli/session.py ────────────────────────┐
 │ TurnRunner(bot, config, capabilities)                                  │
 │   run_turn(query) ─► AsyncIterator[TurnEvent]                          │
 │     ├─ turn_scope(turn_id)  ◄── core/events/lifecycle/turn_scope.py    │
 │     ├─ get_global_registry().subscribe(Before/After/ToolCallFailed,    │
 │     │        where=in_turn_scope(turn_id))  → ToolStarted/Finished/…    │
 │     ├─ bot.ask_stream(...) str → TextDelta ; AIMessage → TurnCompleted  │
 │     └─ cancel() → CancelledError → aclose() → TurnCancelled(partial)    │
 │   load_history(session_id) ◄── bot.get_conversation_history()          │
 │   add_post_turn_hook(cb) ; history: list[ConversationTurn]             │
 └───────────────┬───────────────────────────────┬────────────────────────┘
                 │                               │
     inline (UIMode.INLINE)              tui (UIMode.TUI)
 ┌───────────────▼───────────────┐   ┌───────────▼──────────────────────┐
 │ AgentREPL (repl.py)           │   │ AgentWorkspaceApp (tui/app.py)    │
 │  prompt_async in region.modal │   │  TranscriptView ─ TurnPanel        │
 │  ResponseRenderer (renderer)  │   │   ├ Markdown + MarkdownStream      │
 │   └ LiveRegion (console.py)   │   │   └ ToolActivity (Collapsible)     │
 │  FileHistory (modes.py path)  │   │  Composer(TextArea) + completion   │
 │  batch/non-TTY line mode      │   │  StatusBar · LogDrawer · Footer    │
 └───────────────┬───────────────┘   │  @work(exclusive) turn worker      │
                 │                    │  App.suspend() for HITL prompts    │
                 │                    └───────────┬──────────────────────┘
                 └────────────── CommandContext ──┘   (commands.py protocol)
                                       │
            SlashCommandDispatcher — /tools /info /clear /export /stream
                                   /resume /help /quit /create_agent (+agentd)

 Backends behind the same duck type (ask / ask_stream / get_*tools*):
   StandaloneAgentLoader ──► AbstractBot           capabilities: stream ✓ tools ✓ resume ✓
   ServerAgentProxy ───────► _ServerBotProxy       stream ✓(SSE) tools ✓(SSE frames) resume ✗
   DaemonAgentProxy ───────► _DaemonBotProxy       stream ✓ tools ✗ resume ✗

 Server: StreamHandler.stream_sse  ─ turn_scope + global registry ─► {"type":"tool_event"} frames
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ResponseRenderer` (`renderer.py:59`) | modifies | streams into a `LiveRegion`; renders `TurnEvent`s and resumed history; `_BlockingSafeFile` deleted |
| `AgentREPL` (`repl.py:92`) | modifies | delegates execution to `TurnRunner`; `prompt_async()` inside `region.modal()`; `add_post_turn_hook`; `FileHistory`; Ctrl+C cancels the active task; `_mute_stream_loggers` deleted |
| `REPLConfig` (`repl.py:61`) | extends | `ui_mode`, `resume_session_id`, `server_token`, `history_enabled`; `user_id` becomes `Optional[str]` |
| `SlashCommandDispatcher` (`commands.py:70`) | modifies | handlers typed against `CommandContext`; `/resume` added; `/quit` keeps `SystemExit` |
| `agent_repl.py` (`:49`, `:75`) | modifies | `--ui`, `--session`, `--user`, `--token`; mode resolution; TUI lazy import; `get_console()` |
| `StandaloneAgentLoader` (`loaders.py:56`) | unchanged | loading and picker (`questionary`, `:160`) kept |
| `ServerAgentProxy` / `_ServerBotProxy` (`loaders.py:341`, `:169`) | rewrites | canonical routes, SSE parsing, bearer token, capabilities |
| `StreamHandler.stream_sse` (`handlers/stream.py:64`) | modifies | `tool_event` frames via `turn_scope`; text frames keep the `{"content": ...}` shape |
| `RunView` (`devloop/renderer.py:26`) | modifies | delegates `pause/resume/_live` to `LiveRegion`; envelope handlers unchanged |
| `DevLoopConsole` (`devloop/console.py`) | modifies | gate prompts use `region.modal()` instead of pause/resume pairs (`:907/:940/:969/:1102/:1114/:1119/:1133/:1138/:1146`) |
| `agentd/cli.py` `attach` (`:156-199`) | modifies | `repl.add_post_turn_hook(...)`; `_wrap_with_event_drain` (`:205`) deleted; `get_console()` |
| `_DaemonBotProxy` (`agentd/proxy.py:62`) | extends | `capabilities` property; `ask_stream` unchanged shape |
| `AbstractBot` (`bots/abstract.py`) | uses | `ask` (`:4533`), `ask_stream` (`:4588`), `get_conversation_history` (`:2360`), `get_tools_count/has_tools/get_available_tools` (`:4339-4348`), `cleanup` (`:5017`) — **no changes** |
| Lifecycle events (`core/events/lifecycle/__init__.py`) | uses + extends | `get_global_registry`, `BeforeToolCallEvent`, `AfterToolCallEvent`, `ToolCallFailedEvent`; new `turn_scope.py` sibling module |
| `sdd/specs/new-cli-infra.spec.md` (`:24`) | supersedes | status line → `superseded by FEAT-573` |
| `packages/ai-parrot/pyproject.toml` (`:131-136`) | modifies | adds `textual>=8.2,<9` |

### Data Models

```python
# parrot/cli/modes.py  (NEW)
class UIMode(str, Enum):
    AUTO = "auto"; INLINE = "inline"; TUI = "tui"

class SessionPointer(BaseModel):
    """Last conversation session used with an agent (for ``--session last``)."""
    agent_name: str
    last_session_id: str
    updated_at: datetime

# parrot/cli/events.py  (NEW) — presentation-neutral turn lifecycle
class TurnEventKind(str, Enum):
    STARTED = "started"; DELTA = "delta"; TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"; TOOL_FAILED = "tool_failed"
    COMPLETED = "completed"; FAILED = "failed"; CANCELLED = "cancelled"

class TurnEvent(BaseModel):
    kind: TurnEventKind
    turn_id: str
    seq: int                                  # monotonic per turn, starts at 0
    at: datetime = Field(default_factory=datetime.now)

class TurnStarted(TurnEvent):   query: str; streaming: bool
class TextDelta(TurnEvent):     text: str
class ToolStarted(TurnEvent):   call_id: str; tool_name: str; args_summary: dict[str, Any]
class ToolFinished(TurnEvent):  call_id: str; tool_name: str; duration_ms: float; result_status: str; result_size_bytes: int
class ToolFailed(TurnEvent):    call_id: str; tool_name: str; duration_ms: float; error_type: str; error_message: str
class TurnCompleted(TurnEvent): text: str; message: Any            # AIMessage or backend response object
class TurnFailed(TurnEvent):    error_type: str; error_message: str; partial_text: str
class TurnCancelled(TurnEvent): partial_text: str

class BackendCapabilities(BaseModel):
    streaming: bool = True
    live_tool_events: bool = False
    usage: bool = False
    resume: bool = False
```

`call_id` is the tool event's `trace_context.span_id` — the same `TraceContext`
object is passed to the Before/After/Failed emits of one execution
(`tools/abstract.py:948`, `:1132`, `:1172`), so the id is stable across the
three and unique per call even when the tool minted a fresh root trace.
`args_summary` is the already-truncated, JSON-safe dict the lifecycle event
carries (`events/tool.py:18`); presenters never receive raw arguments or results
through live events — results appear only in the final `AIMessage.tool_calls`.

`REPLConfig` (`repl.py:61`) gains: `ui_mode: UIMode = UIMode.AUTO`,
`resume_session_id: Optional[str] = None`, `server_token: Optional[str] = None`,
`history_enabled: bool = True`; `user_id: Optional[str] = "cli-user"`.

### New Public Interfaces

Signatures only (FEAT-545); bodies belong to task blueprints. Every module's
skeleton is in §3.

```python
# parrot/cli/console.py
def get_console() -> Console: ...
class LiveRegion:
    def __init__(self, console: Optional[Console] = None, *, refresh_per_second: int = 8, transient: bool = False) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def update(self, renderable: Any) -> None: ...
    @contextlib.contextmanager
    def modal(self) -> Iterator[None]: ...
    @property
    def is_terminal(self) -> bool: ...

# parrot/cli/modes.py
def resolve_ui_mode(requested: UIMode, *, stdin_isatty: bool, stdout_isatty: bool, term: Optional[str]) -> UIMode: ...
def cli_state_dir() -> Path: ...
def history_path(agent_name: str) -> Path: ...
def load_session_pointer(agent_name: str) -> Optional[SessionPointer]: ...
def save_session_pointer(agent_name: str, session_id: str) -> None: ...

# parrot/core/events/lifecycle/turn_scope.py
TURN_SCOPE: ContextVar[Optional[str]]
@contextlib.contextmanager
def turn_scope(turn_id: str) -> Iterator[None]: ...
def in_turn_scope(turn_id: str) -> Callable[[LifecycleEvent], bool]: ...

# parrot/cli/session.py
class TurnInProgressError(RuntimeError): ...
class TurnRunner:
    def __init__(self, bot: Any, config: REPLConfig, *, capabilities: Optional[BackendCapabilities] = None) -> None: ...
    @property
    def is_active(self) -> bool: ...
    def run_turn(self, query: str) -> AsyncIterator[TurnEvent]: ...
    def cancel(self) -> bool: ...
    async def load_history(self, session_id: str) -> list[ConversationTurn]: ...
    def reset_session(self) -> str: ...
    def add_post_turn_hook(self, hook: PostTurnHook) -> None: ...

# parrot/cli/commands.py
class RendererProtocol(Protocol): print / render / render_error / render_table / render_info / render_history
class CommandContext(Protocol):
    bot: Any; config: REPLConfig; history: list[ConversationTurn]
    renderer: RendererProtocol; dispatcher: "SlashCommandDispatcher"; runner: "TurnRunner"
    def suspend(self) -> ContextManager[None]: ...

# parrot/cli/repl.py
class AgentREPL:  # now also a CommandContext
    def add_post_turn_hook(self, hook: PostTurnHook) -> None: ...
    async def run_batch(self, lines: Iterable[str]) -> int: ...

# parrot/cli/tui/app.py
class AgentWorkspaceApp(App[int]):
    def __init__(self, *, bot: Any, config: REPLConfig, runner: TurnRunner, dispatcher: SlashCommandDispatcher, history: History) -> None: ...

# parrot/cli/loaders.py
class ServerAgentProxy:
    def __init__(self, server_url: str, timeout: int = 30, *, token: Optional[str] = None) -> None: ...
class _ServerBotProxy:
    capabilities: BackendCapabilities
    async def ask_stream(...) -> AsyncIterator[Union[str, ToolStarted, ToolFinished, ToolFailed, _ServerResponse]]: ...
```

---

## 3. Module Breakdown

> These map to Task Artifacts in `/sdd-task`. Module numbering is the
> dependency order; the Worktree Strategy section gives the graph.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M0: dependency + supersession | yes | `textual>=8.2,<9` after `rich>=13.0` in `pyproject.toml:131`; status line edit at `new-cli-infra.spec.md:24` | — |
| M1: shared console | yes | signatures fixed above; extraction of `devloop/renderer.py:82-107`; `refresh_per_second=8, transient=False` | — |
| M2: modes + state paths | yes | rules in skeleton; `PARROT_HOME` env, `~/.parrot/cli/…`, files `0o600` | — |
| M3: turn scope | yes | `ContextVar` + predicate; no other behaviour | — |
| M4: turn events | yes | models above, verbatim | — |
| M5: TurnRunner | yes | contract in skeleton incl. cancellation order and hook timing | — |
| M6: renderer on LiveRegion | yes | FEAT-519 Module 2 + `render_turn_event` + `render_history` | — |
| M7: CommandContext + `/resume` | yes | Protocol fixed; handler signature `(ctx, args)`; `/quit` raises `SystemExit` unchanged | — |
| M8: AgentREPL | yes | loop shape fixed in skeleton | — |
| M9: server proxy rewrite | yes | routes, frame grammar and token header fixed; list payload shape flagged for verification | — |
| M10: server SSE tool frames | yes | frame grammar fixed | — |
| M11: TUI app + widgets | **partial** | layout, bindings, states and widget classes fixed; visual CSS values free | CSS theming is the coder's call |
| M12: TUI command adapter + log drawer | yes | routing rules fixed | — |
| M13: entry point | yes | option names/defaults and non-TTY rules fixed | — |
| M14: devloop convergence | yes | mechanical delegation; zero behaviour change | — |
| M15: agentd migration | yes | hook + capabilities + console | — |
| M16: tests | yes | §4 matrix | — |
| M17: docs | yes | `docs/cli/parrot-agent.md` | — |

### Module 0: Dependency and FEAT-519 supersession
- **Path**: `packages/ai-parrot/pyproject.toml`, `sdd/specs/new-cli-infra.spec.md`
- **Responsibility**: add `"textual>=8.2,<9",` to core dependencies (next to
  `"rich>=13.0"` at `pyproject.toml:131`); run `uv lock` and verify resolution
  for Python 3.11, 3.12 and 3.13; change `**Status**: draft`
  (`new-cli-infra.spec.md:24`) to `**Status**: superseded by FEAT-573
  (sdd/specs/new-ui-cli-agents.spec.md)`.
- **Depends on**: nothing (foundation; **exclusive** — lockfile).
- **Interface Skeleton**: none (configuration only). Textual 8.2.8 requires
  `rich>=14.2.0` and `python>=3.9` (verified from the wheel metadata);
  installed rich is 15.0.0.

### Module 1: Shared console layer
- **Path**: `packages/ai-parrot/src/parrot/cli/console.py` *(new)*
- **Responsibility**: process-wide `Console` and the `LiveRegion` modal
  discipline (FEAT-519 Module 1). No `file=sys.__stdout__` bypass, no
  `_BlockingSafeFile`.
- **Depends on**: nothing in this spec.
- **Interface Skeleton**:
  ```python
  # parrot/cli/console.py  (new)
  import contextlib
  from typing import Any, Iterator, Optional
  from rich.console import Console          # verified: renderer.py:13
  from rich.live import Live                # verified: devloop/renderer.py:15

  def get_console() -> Console:
      """Return the process-wide shared Rich Console (created on first call).

      Tests may replace it via ``set_console(console)``; ``reset_console()``
      restores lazy creation.
      """

  def set_console(console: Optional[Console]) -> None:
      """Override (or clear) the shared console. Test seam."""

  class LiveRegion:
      """Managed ``rich.live.Live`` area with 'one writer at a time' discipline.

      Extraction of ``RunView.pause/resume/run_live`` (devloop/renderer.py:82-107):
      ``Live(renderable, console=..., refresh_per_second=8, transient=False)``.
      When ``console.is_terminal`` is False every ``update()`` prints the
      renderable once, sequentially, and ``modal()`` is a no-op — piping stays
      clean (no cursor-control sequences).
      """
      def __init__(self, console: Optional[Console] = None, *, refresh_per_second: int = 8, transient: bool = False) -> None: ...
      def start(self) -> None:
          """Start the Live display (idempotent)."""
      def stop(self) -> None:
          """Stop the Live display, leaving the last frame on screen (idempotent)."""
      def pause(self) -> None:
          """``Live.stop()`` so another writer may own the terminal."""
      def resume(self) -> None:
          """``Live.start()`` after a pause; no-op if never started."""
      def update(self, renderable: Any) -> None:
          """Replace the region content (repainted on the next refresh tick)."""
      @contextlib.contextmanager
      def modal(self) -> Iterator[None]:
          """Pause for the duration of a prompt/modal interaction, then resume."""
      @property
      def is_terminal(self) -> bool:
          """``console.is_terminal`` of the bound console."""
  ```

### Module 2: UI mode resolution and CLI state paths
- **Path**: `packages/ai-parrot/src/parrot/cli/modes.py` *(new)*
- **Responsibility**: `UIMode`, `resolve_ui_mode`, state directory and the two
  per-agent files (input history, session pointer).
- **Depends on**: nothing in this spec.
- **Interface Skeleton**:
  ```python
  # parrot/cli/modes.py  (new)
  class UIMode(str, Enum): ...                       # see §2 Data Models
  class SessionPointer(BaseModel): ...

  def resolve_ui_mode(requested: UIMode, *, stdin_isatty: bool, stdout_isatty: bool, term: Optional[str]) -> UIMode:
      """Resolve AUTO to INLINE or TUI; pass INLINE/TUI through.

      Rules: TUI iff ``stdin_isatty and stdout_isatty and (term or '').lower() != 'dumb'``.
      Explicit ``TUI`` on a non-TTY raises ``UIModeError`` (caller exits 2).
      Returns never ``AUTO``.
      """

  def is_interactive(*, stdin_isatty: bool, stdout_isatty: bool) -> bool:
      """True when both streams are TTYs; False selects batch/line mode."""

  def cli_state_dir() -> Path:
      """``$PARROT_HOME`` or ``~/.parrot`` (conf.py:556 / wiki/project.py:1009 convention) + ``cli``; created ``0o700``."""

  def agent_slug(agent_name: str) -> str:
      """Filesystem-safe slug: lowercase, ``[^a-z0-9._-]`` → ``_``."""

  def history_path(agent_name: str) -> Path:
      """``cli_state_dir()/history/<slug>.txt`` — prompt_toolkit FileHistory format; file mode ``0o600``."""

  def load_session_pointer(agent_name: str) -> Optional[SessionPointer]:
      """Read ``cli_state_dir()/sessions/<slug>.json``; None when absent or invalid."""

  def save_session_pointer(agent_name: str, session_id: str) -> None:
      """Atomic write (tmp + ``os.replace``) of the pointer file, mode ``0o600``."""
  ```

### Module 3: Turn scope (core lifecycle helper)
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/turn_scope.py` *(new)*
- **Responsibility**: correlate lifecycle events with the turn/request that
  caused them, via a `ContextVar` copied into every `create_task`.
- **Depends on**: nothing in this spec (uses `LifecycleEvent` from
  `navigator_eventbus.lifecycle.base`, re-exported at
  `core/events/lifecycle/__init__.py:19`).
- **Interface Skeleton**:
  ```python
  # parrot/core/events/lifecycle/turn_scope.py  (new)
  from contextvars import ContextVar
  from parrot.core.events.lifecycle import LifecycleEvent   # verified: lifecycle/__init__.py:19

  TURN_SCOPE: ContextVar[Optional[str]] = ContextVar("parrot_turn_scope", default=None)

  @contextlib.contextmanager
  def turn_scope(turn_id: str) -> Iterator[None]:
      """Set ``TURN_SCOPE`` to ``turn_id`` for the body; always reset on exit."""

  def in_turn_scope(turn_id: str) -> Callable[[LifecycleEvent], bool]:
      """Predicate for ``EventRegistry.subscribe(where=...)``: True when the
      emitting context's ``TURN_SCOPE`` equals ``turn_id``.

      Correct because ``EventRegistry.emit_nowait`` and the global-registry
      forwarder schedule ``emit`` with ``loop.create_task`` (navigator-eventbus
      0.3.0), which copies the emitter's ``contextvars.Context``.
      """
  ```
  Also export both names from `core/events/lifecycle/__init__.py` (`__all__`).

### Module 4: Turn event model
- **Path**: `packages/ai-parrot/src/parrot/cli/events.py` *(new)*
- **Responsibility**: the Pydantic models in §2 Data Models plus
  `BackendCapabilities` and `PostTurnHook`.
- **Depends on**: nothing in this spec.
- **Interface Skeleton**:
  ```python
  # parrot/cli/events.py  (new)
  from parrot.cli.commands import ConversationTurn      # verified: commands.py:38
  PostTurnHook = Callable[["CommandContext", ConversationTurn], Awaitable[None]]
  # + the TurnEvent family and BackendCapabilities exactly as in §2 Data Models
  def summarize_message_text(message: Any) -> str:
      """``output`` if str, else ``response``, else ``json.dumps(output)`` — mirrors renderer.py:98-112."""
  ```

### Module 5: TurnRunner (execution boundary)
- **Path**: `packages/ai-parrot/src/parrot/cli/session.py` *(new)*
- **Responsibility**: one place that talks to the bot; produces `TurnEvent`s;
  owns cancellation, tool-event subscription, display history, post-turn hooks,
  resume loading, session reset.
- **Depends on**: M2 (`save_session_pointer`), M3, M4.
- **Interface Skeleton**:
  ```python
  # parrot/cli/session.py  (new)
  from parrot.models.outputs import OutputMode                     # verified: repl.py:24 (TERMINAL at outputs.py:29)
  from parrot.core.events.lifecycle import (                      # verified: lifecycle/__init__.py:21-22, :39-41
      get_global_registry, BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent)
  from parrot.core.events.lifecycle.turn_scope import turn_scope, in_turn_scope   # M3

  class TurnInProgressError(RuntimeError):
      """Raised by ``run_turn`` while another turn is active (one turn per session)."""

  class TurnRunner:
      """Runs conversation turns against a bot-like backend and yields TurnEvents.

      Identity kwargs are exactly those AgentREPL passes today (repl.py:212-218,
      :249-255): ``session_id``, ``user_id``, ``output_mode=OutputMode.TERMINAL``,
      ``permission_context``. ``user_id=None`` is omitted from the call.
      """
      def __init__(self, bot: Any, config: REPLConfig, *, capabilities: Optional[BackendCapabilities] = None) -> None:
          """``capabilities`` defaults to ``getattr(bot, 'capabilities', None)`` or standalone defaults
          (streaming=True, live_tool_events=True, usage=True, resume=bot has ``get_conversation_history``)."""
      history: list[ConversationTurn]        # display/export history (ConversationTurn, commands.py:38)
      @property
      def is_active(self) -> bool: ...
      @property
      def capabilities(self) -> BackendCapabilities: ...

      async def run_turn(self, query: str) -> AsyncIterator[TurnEvent]:
          """Yield TurnStarted, then TextDelta/Tool* events, then exactly one terminal
          event (TurnCompleted | TurnFailed | TurnCancelled).

          Order of operations: (1) raise TurnInProgressError if active; (2) mint
          ``turn_id``; (3) subscribe the three tool events on
          ``get_global_registry()`` with ``where=in_turn_scope(turn_id)`` when
          ``capabilities.live_tool_events``; (4) inside ``turn_scope(turn_id)``
          call ``bot.ask_stream`` (streaming) or ``bot.ask`` (batch); str yields →
          TextDelta; an object with ``output`` (AIMessage or backend response) →
          the completion message; Tool* events from the backend iterator (server
          proxy) are forwarded as-is; (5) on ``asyncio.CancelledError`` call
          ``aclose()`` on the iterator and yield TurnCancelled(partial); (6) on
          other exceptions yield TurnFailed(partial) — never re-raise to the
          presenter; (7) finally unsubscribe, run post-turn hooks only after
          TurnCompleted, append a ConversationTurn only for COMPLETED turns,
          and ``save_session_pointer``.
          """
      def cancel(self) -> bool:
          """Cancel the active turn's task; True if one was active."""
      async def load_history(self, session_id: str) -> list[ConversationTurn]:
          """Resume support: ``bot.get_conversation_history(user_id, session_id)``
          (bots/abstract.py:2360) → map each memory ``ConversationTurn``
          (memory/abstract.py:102: ``user_message``, ``assistant_response``,
          ``tool_invocations``, ``timestamp``, ``error``) to a CLI
          ``ConversationTurn`` with a ``_ResumedResponse`` (``output``,
          ``response``, ``tool_calls`` built from ``tool_invocations``, ``usage=None``).
          Returns [] when the backend lacks ``resume`` or history is None; also
          sets ``config.session_id`` and replaces ``self.history``.
          """
      def reset_session(self) -> str:
          """New ``uuid4`` session id (``/clear`` semantics, commands.py:228-230); clears history; returns the id."""
      def add_post_turn_hook(self, hook: PostTurnHook) -> None:
          """Register a coroutine awaited after each COMPLETED turn, before control returns to the presenter."""
  ```

### Module 6: Renderer on the shared layer
- **Path**: `packages/ai-parrot/src/parrot/cli/renderer.py` *(modifies)*
- **Responsibility**: FEAT-519 Module 2 — stream Markdown into a `LiveRegion`
  instead of `sys.stdout.write` (`renderer.py:257`); delete `_BlockingSafeFile`
  (`:22-56`); console via `get_console()` (`:80-82`). Add `render_turn_event`,
  `render_history`, `render_tool_started`. Keep every existing public method
  and the zero-argument constructor (agentd constructs `ResponseRenderer()`,
  `agentd/cli.py:158`; fixture at `tests/cli/conftest.py`).
- **Depends on**: M1, M4.
- **Interface Skeleton**:
  ```python
  # parrot/cli/renderer.py  (modifies renderer.py:59)
  class ResponseRenderer:
      def __init__(self, console: Optional[Console] = None, region: Optional[LiveRegion] = None) -> None:
          """Defaults: ``get_console()`` and a lazily created ``LiveRegion``. Tests inject both."""
      def render(self, response: AIMessage) -> None: ...                       # unchanged contract, renderer.py:89
      def render_stream_start(self) -> None:
          """Reset the buffer and ``region.start()``."""                       # replaces renderer.py:233
      def render_stream_chunk(self, text: str) -> None:
          """Append to ``_stream_buffer``; ``region.update(Markdown(buffer))`` — throttled by the region's refresh tick; never touches ``sys.stdout``."""  # replaces renderer.py:248
      def render_stream_end(self, response: Optional[AIMessage] = None) -> None:
          """``region.stop()``, then tool panels/usage as today (renderer.py:262-280)."""
      def render_turn_event(self, event: TurnEvent) -> None:
          """Dispatch: TextDelta→render_stream_chunk; ToolStarted→dim '⏵ tool <name> …' line;
          ToolFinished/ToolFailed→dim status line; TurnCancelled→'[yellow]Interrupted[/yellow]' + partial kept;
          TurnFailed→render_error-style panel with partial preserved."""
      def render_history(self, turns: list[ConversationTurn], *, session_id: str) -> None:
          """Resumed transcript: header 'Resumed session <id> (N turns)', then each turn as 'you> …' + Markdown."""
      def render_usage_unknown(self) -> None:
          """'[dim]tokens: n/a[/dim]' — unknown usage is never shown as zero."""
  ```

### Module 7: CommandContext protocol and `/resume`
- **Path**: `packages/ai-parrot/src/parrot/cli/commands.py` *(modifies)*
- **Responsibility**: decouple handlers from `AgentREPL` by typing the first
  handler argument as `CommandContext`; route session mutations through
  `ctx.runner`; add `/resume`; keep `/quit` raising `SystemExit` (hosts catch
  it) and `/export`'s JSON shape (`commands.py:257-264`).
- **Depends on**: M4, M5.
- **Interface Skeleton**:
  ```python
  # parrot/cli/commands.py  (modifies commands.py:22-166 + handlers)
  class RendererProtocol(Protocol):
      def print(self, *args: Any, **kwargs: Any) -> None: ...
      def render(self, response: Any) -> None: ...
      def render_error(self, error: Exception) -> None: ...
      def render_table(self, headers: List[str], rows: List[List[str]], title: Optional[str] = None) -> None: ...
      def render_info(self, lines: List[tuple[str, str]]) -> None: ...
      def render_history(self, turns: List["ConversationTurn"], *, session_id: str) -> None: ...

  class CommandContext(Protocol):
      """What a slash-command handler may touch. Implemented by AgentREPL (inline) and TUICommandContext (tui/adapter.py)."""
      bot: Any
      config: "REPLConfig"
      renderer: RendererProtocol
      dispatcher: "SlashCommandDispatcher"
      runner: "TurnRunner"
      @property
      def history(self) -> List["ConversationTurn"]: ...           # == runner.history
      def suspend(self) -> ContextManager[None]:
          """Yield the terminal to a foreign prompt (HITL, device code): inline → ``LiveRegion.modal()``; TUI → ``App.suspend()``."""

  @dataclass
  class SlashCommand:                         # commands.py:23 — unchanged fields
      handler: Callable[["CommandContext", str], Awaitable[None]]

  class SlashCommandDispatcher:               # commands.py:70
      async def dispatch_async(self, input_text: str, ctx: "CommandContext") -> bool: ...   # param renamed repl→ctx
      def get_completions(self) -> List[str]: ...                                          # unchanged

  async def _cmd_clear(ctx, args) -> None:    # commands.py:221 → uses ctx.runner.reset_session()
  async def _cmd_resume(ctx, args) -> None:
      """``/resume <session_id|last>``: resolve 'last' via load_session_pointer(config.agent_name);
      turns = await ctx.runner.load_history(id); renderer.render_history(...); error when capabilities.resume is False."""
  async def _cmd_create_agent(ctx, args) -> None:   # commands.py:347 → body runs inside ``with ctx.suspend():``
  ```

### Module 8: AgentREPL on TurnRunner (inline presenter)
- **Path**: `packages/ai-parrot/src/parrot/cli/repl.py` *(modifies)*
- **Responsibility**: FEAT-519 Module 3 plus TurnRunner adoption: delete
  `_STREAM_LOG_FLOOR`/`_mute_stream_loggers`/`_restore_stream_loggers`
  (`repl.py:30-58`) and their call sites (`:247`, `:279`); console via
  `get_console()` (`:128`); `PromptSession(history=FileHistory(history_path(...)))`
  when `config.history_enabled` (`:147-150`); `prompt_async` inside
  `region.modal()` (`:157`); a turn runs as an `asyncio.Task` so Ctrl+C
  (`KeyboardInterrupt`, `:190`) calls `runner.cancel()` and awaits the task;
  `send`/`send_stream` become thin wrappers over `runner.run_turn` +
  `renderer.render_turn_event` (kept for `tests/cli/test_integration.py`);
  `run_batch` for non-TTY; `add_post_turn_hook` delegates to the runner.
- **Depends on**: M1, M2, M5, M6, M7.
- **Interface Skeleton**:
  ```python
  # parrot/cli/repl.py  (modifies repl.py:61-303)
  class REPLConfig(BaseModel):                       # repl.py:61
      agent_name: str
      streaming: bool = True
      server_url: Optional[str] = None
      session_id: str = Field(default_factory=lambda: str(uuid4()))
      user_id: Optional[str] = "cli-user"            # was str; None ⇒ omit from bot calls (server mode default)
      permission_context: Optional[Any] = None
      ui_mode: UIMode = UIMode.AUTO
      resume_session_id: Optional[str] = None
      server_token: Optional[str] = None
      history_enabled: bool = True

  class AgentREPL:                                   # repl.py:92 — implements CommandContext
      def __init__(self, bot: AbstractBot, config: REPLConfig, renderer: ResponseRenderer, *, runner: Optional[TurnRunner] = None) -> None: ...
      runner: TurnRunner
      @property
      def history(self) -> List[ConversationTurn]: ...      # alias of runner.history (tests read repl.history)
      async def run(self) -> None:
          """Interactive loop. If ``config.resume_session_id`` is set, load and render it first.
          Each prompt inside ``self.renderer.region.modal()``; each agent turn as a task; Ctrl+C → cancel."""
      async def run_batch(self, lines: Iterable[str]) -> int:
          """Non-TTY mode: one turn per non-empty stdin line, slash commands allowed, plain sequential output,
          exit code 0 (or 1 if any turn FAILED)."""
      async def send(self, query: str) -> AIMessage: ...          # via runner (batch), unchanged signature repl.py:200
      async def send_stream(self, query: str) -> None: ...       # via runner (stream), unchanged signature repl.py:228
      def register_command(self, cmd: SlashCommand) -> None: ... # repl.py:296 unchanged
      def add_post_turn_hook(self, hook: PostTurnHook) -> None: ...
      def suspend(self) -> ContextManager[None]: ...             # renderer.region.modal()
  # _StreamedResponse (repl.py:305) is kept as the batch fallback proxy.
  ```

### Module 9: Server backend rewrite
- **Path**: `packages/ai-parrot/src/parrot/cli/loaders.py` *(modifies `:169-468`)*
- **Responsibility**: replace the phantom routes with the canonical server API
  and parse the SSE frame grammar of Module 10. Standalone loader untouched.
- **Depends on**: M4, M10 (frame grammar; the parser tolerates absence of
  `tool_event` frames so it also works against an older server).
- **Interface Skeleton**:
  ```python
  # parrot/cli/loaders.py  (modifies)
  class ServerAgentProxy:                                          # loaders.py:341
      def __init__(self, server_url: str, timeout: int = 30, *, token: Optional[str] = None) -> None:
          """``token`` → ``Authorization: Bearer <token>`` on every request (server routes sit behind
          navigator-auth's global middleware; AgentTalk is ``@is_authenticated()``, handlers/agent.py:111)."""
      async def load(self, name: str) -> "_ServerBotProxy":
          """``GET {server}/api/v1/chatbots/{name}`` (BotHandler, chat.py:166-186; 404 ⇒ AgentLoadError) — replaces loaders.py:394."""
      async def list_agents(self) -> List[Dict[str, Any]]:
          """``GET {server}/api/v1/bots`` (ChatbotHandler.get → ``_get_all``, bots.py:649-660) — replaces loaders.py:424.
          Payload shape is (unverified — check before use): accept a JSON list or ``{"agents": [...]}``; each item must expose ``name``."""

  class _ServerBotProxy:                                           # loaders.py:169
      capabilities: BackendCapabilities   # streaming=True, live_tool_events=True, usage=True, resume=False
      async def ask(self, question, session_id=None, user_id=None, output_mode=None, **kwargs) -> "_ServerResponse":
          """``POST {server}/api/v1/agents/chat/{name}`` JSON ``{"query": question, "session_id":…, "stream": false}``
          plus ``user_id`` only when not None (AgentTalk gives an explicit body user_id precedence over the
          authenticated identity, agent.py:879-902) — replaces loaders.py:233."""
      async def ask_stream(self, question, session_id=None, user_id=None, output_mode=None, **kwargs):
          """``POST {server}/bots/{name}/stream/sse`` (stream.py:467) JSON ``{"prompt": question, "session_id":…, ["user_id":…]}``;
          parse ``data:`` lines: ``{"content": str}`` → yield str; ``{"type": "tool_event", "data": {...}}`` → yield
          ToolStarted/ToolFinished/ToolFailed; ``{"type": "ai_message", "data": {...}}`` → build the final
          ``_ServerResponse``; ``[DONE]`` ends; ``error:`` lines raise AgentLoadError. Replaces the local chunker loaders.py:274-288."""

  class _ServerResponse:                                           # loaders.py:315
      """Now also carries ``tool_calls`` (list of ToolCall-like objects) and ``usage`` (CompletionUsage-like) when the
      ``ai_message`` frame provides them (AIMessage.to_dict() == model_dump(), responses.py:302-304)."""

  async def _iter_sse(resp: aiohttp.ClientResponse) -> AsyncIterator[str]:
      """Yield the payload of each ``data:`` event (lines joined until a blank line). No new dependency."""
  ```

### Module 10: Server SSE tool-event frames
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/stream.py` *(modifies `stream_sse`, `:64-110`)*
- **Responsibility**: during a streamed turn, subscribe to the global lifecycle
  registry for tool events scoped to this request and emit them as SSE frames
  between text frames. Keep existing frame shapes for current consumers.
- **Depends on**: M3.
- **Interface Skeleton**:
  ```python
  # parrot/handlers/stream.py  (modifies stream.py:64)
  from parrot.core.events.lifecycle import get_global_registry, BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent
  from parrot.core.events.lifecycle.turn_scope import turn_scope, in_turn_scope

  class StreamHandler(BaseHandler):                                # stream.py:13
      async def stream_sse(self, request: web.Request) -> web.StreamResponse:
          """Frame grammar (each ``data: <json>\\n\\n``):
             {"content": "<delta>"}                                             — unchanged
             {"type": "tool_event", "data": {"event": "started"|"finished"|"failed", "call_id": <span_id>,
                                              "tool_name": str, "args_summary": {...} | "duration_ms": float,
                                              "result_status": str, "result_size_bytes": int | "error_type": str,
                                              "error_message": str, "at": iso8601}}   — NEW
             {"type": "ai_message", "data": <AIMessage.to_dict()>}                — unchanged
             [DONE]                                                             — unchanged
          Implementation: mint ``turn_id``; subscribe the three events with ``where=in_turn_scope(turn_id)``;
          callbacks put frames on an ``asyncio.Queue``; run ``bot.ask_stream`` inside ``turn_scope(turn_id)``
          and drain the queue between deltas and after the stream ends; ``finally`` unsubscribe.
          Callbacks are async and must not await the response (they only enqueue)."""
  ```

### Module 11: Textual workspace (app + widgets)
- **Path**: `packages/ai-parrot/src/parrot/cli/tui/__init__.py`, `tui/app.py`,
  `tui/widgets.py`, `tui/app.tcss` *(new)*
- **Responsibility**: the full-screen presenter over `TurnRunner`. Textual 8.2.8
  API verified for: `App.run_async`, `App.suspend()` (context manager),
  `App.run_test()`/`Pilot.press`, `@work`, `Binding`, `Markdown.get_stream() →
  MarkdownStream.write()/stop()` (async), `TextArea`, `Collapsible`,
  `VerticalScroll.anchor()/scroll_end()`, `ModalScreen`, `events.Resize`,
  `events.Paste`.
- **Depends on**: M1 (console only for banner), M4, M5, M7, M12.
- **Fixed design**:
  - Layout: `Header` (agent · mode · session short id) / `TranscriptView`
    (`VerticalScroll`) of `TurnPanel`s / `ToolDrawer`-less: each `TurnPanel` has a
    user `Static`, an assistant `Markdown` (streamed via `MarkdownStream`), and a
    `ToolActivity` (`Collapsible`, collapsed by default, one row per `call_id`
    with state ⏵ running / ✓ done (ms) / ✗ failed) / `Composer` (`TextArea`) /
    `StatusBar` (`Static`: idle · waiting · streaming · running tool <name> ·
    cancelling · tokens or "n/a") / `Footer` (bindings).
  - Bindings: `enter` send · `ctrl+j` **and** `shift+enter` newline · `up`/`down`
    history when the cursor is on the first/last line · `tab` complete a `/`
    command prefix · `pageup`/`pagedown` scroll · `end` resume auto-follow ·
    `ctrl+c` cancel active turn (idle: second press within 2 s quits) · `ctrl+d`
    quit · `f2` toggle all tool panels · `f3` toggle log drawer · `ctrl+l` = `/clear`.
  - One turn at a time: submitting while active → `notify("A request is running — Ctrl+C cancels")`, input kept.
  - Auto-follow: `TranscriptView.anchor()` while following; any manual scroll
    up sets `following=False`; `end` or a new submission re-anchors.
  - Caps: at most 200 `TurnPanel`s kept mounted (older removed with one
    "(N earlier turns hidden — /export saves all)" `Static`); per-turn text
    above 512 KiB is truncated with a marker; `runner.history` is never capped.
  - Narrow terminals (`width < 60`): tool panels collapse and status bar hides
    usage before the composer shrinks.
  - Resize (`events.Resize`) and exit restore the terminal (Textual owns the
    alternate screen); `App.exit(return_code=…)` maps to the process exit code.
- **Interface Skeleton**:
  ```python
  # parrot/cli/tui/app.py  (new)
  from textual.app import App, ComposeResult
  from textual.binding import Binding
  from textual import work

  class AgentWorkspaceApp(App[int]):
      """Full-screen agent workspace. Return value is the process exit code."""
      CSS_PATH = "app.tcss"
      BINDINGS = [...]                                        # exactly the list above
      def __init__(self, *, bot: Any, config: REPLConfig, runner: TurnRunner, dispatcher: SlashCommandDispatcher,
                   history: History, resume_turns: Optional[list[ConversationTurn]] = None) -> None: ...
      def compose(self) -> ComposeResult: ...
      async def on_mount(self) -> None:
          """Render ``resume_turns`` if any; focus the composer; install the log drawer handler (M12)."""
      async def submit(self, text: str) -> None:
          """Slash command → dispatcher.dispatch_async(text, self.command_context); else start the turn worker."""
      @work(exclusive=True, group="turn")
      async def _run_turn(self, query: str) -> None:
          """async for event in runner.run_turn(query): self.transcript.apply(event); self.status.apply(event)"""
      def action_cancel_turn(self) -> None: ...
      def action_toggle_tools(self) -> None: ...
      def action_toggle_logs(self) -> None: ...
      def action_resume_follow(self) -> None: ...

  # parrot/cli/tui/widgets.py  (new)
  class TranscriptView(VerticalScroll):
      following: reactive[bool]
      def begin_turn(self, event: TurnStarted) -> "TurnPanel": ...
      async def apply(self, event: TurnEvent) -> None: ...
      def append_renderable(self, renderable: Any) -> None:
          """Command output / notices as a Static between turns."""
  class TurnPanel(Vertical):
      async def apply(self, event: TurnEvent) -> None: ...
  class ToolActivity(Collapsible):
      def start(self, ev: ToolStarted) -> None: ...
      def finish(self, ev: ToolFinished) -> None: ...
      def fail(self, ev: ToolFailed) -> None: ...
  class Composer(TextArea):
      class Submitted(Message): text: str
      def __init__(self, *, history: History, completions: Callable[[], List[str]]) -> None: ...
  class StatusBar(Static):
      def apply(self, event: TurnEvent) -> None: ...
  class LogDrawer(RichLog): ...
  ```

### Module 12: TUI command adapter, log routing, suspension
- **Path**: `packages/ai-parrot/src/parrot/cli/tui/adapter.py` *(new)*
- **Responsibility**: `TUICommandContext` (implements `CommandContext`) with a
  `TUIRenderer` (implements `RendererProtocol`) that appends Rich renderables
  to the transcript; `suspend()` wraps `App.suspend()` for `/create_agent`
  HITL prompts and any device-code interaction; a `logging.Handler` that
  routes root-logger records to the `LogDrawer` while the app runs (installed
  on mount, removed on unmount; no handler level mutation anywhere else);
  `SystemExit` from `/quit` is caught in `submit()` and mapped to `App.exit(0)`.
- **Depends on**: M7, M11.
- **Interface Skeleton**:
  ```python
  # parrot/cli/tui/adapter.py  (new)
  class TUIRenderer:                        # RendererProtocol
      def __init__(self, transcript: "TranscriptView") -> None: ...
      def print(self, *args, **kwargs) -> None: ...            # Text.from_markup for str args
      def render(self, response: Any) -> None: ...
      def render_error(self, error: Exception) -> None: ...
      def render_table(self, headers, rows, title=None) -> None: ...
      def render_info(self, lines) -> None: ...
      def render_history(self, turns, *, session_id: str) -> None: ...
  class TUICommandContext:                  # CommandContext
      def __init__(self, app: "AgentWorkspaceApp", bot, config, runner, dispatcher) -> None: ...
      def suspend(self) -> ContextManager[None]:
          """``self.app.suspend()`` — Textual restores the terminal, the foreign prompt runs, the app redraws."""
  class DrawerLogHandler(logging.Handler):
      def __init__(self, drawer: "LogDrawer") -> None: ...
      def emit(self, record: logging.LogRecord) -> None:
          """``drawer.write`` via ``app.call_from_thread`` when off-loop, else directly."""
  ```

### Module 13: Entry point wiring
- **Path**: `packages/ai-parrot/src/parrot/cli/agent_repl.py` *(modifies)*
- **Responsibility**: options, mode resolution, non-TTY rules, TUI launch.
  Preserve the FEAT-266 permission bootstrap (`:124-133`), the bot-cleanup
  `finally` (`:154-163`), `--list` (`:97-100`, `_handle_list :166`) and the
  banner (`_print_banner :211`, now through `get_console()`).
- **Depends on**: M2, M5, M8, M9, M11.
- **Interface Skeleton**:
  ```python
  # parrot/cli/agent_repl.py  (modifies agent_repl.py:28-163)
  @click.command("agent")
  @click.argument("name", required=False, default=None)
  @click.option("--list", "list_agents", is_flag=True)
  @click.option("--server", default=None, metavar="URL")
  @click.option("--no-stream", is_flag=True)
  @click.option("--ui", type=click.Choice(["auto", "inline", "tui"]), default="auto", show_default=True,
                help="Interface: full-screen workspace (tui), classic inline console (inline), or detect (auto).")
  @click.option("--session", "session", default=None, metavar="ID|last", help="Resume a prior conversation session.")
  @click.option("--user", "user_id", default=None, metavar="USER_ID", help="Identity sent with each request.")
  @click.option("--token", envvar="PARROT_SERVER_TOKEN", default=None, help="Bearer token for --server mode.")
  @click.option("--no-history", is_flag=True, help="Do not persist composer history.")
  def agent(name, list_agents, server, no_stream, ui, session, user_id, token, no_history) -> None: ...

  async def _run(...) -> None:
      """Sequence: loader → --list → mode = resolve_ui_mode(UIMode(ui), stdin_isatty=sys.stdin.isatty(),
      stdout_isatty=sys.stdout.isatty(), term=os.environ.get('TERM')) → if not interactive and name is None:
      exit 2 'agent name required when stdin is not a terminal' → picker only when interactive → load bot →
      permission ctx (unchanged) → config (user_id = user_id or (None if server else 'cli-user'),
      resume_session_id resolved from 'last' via load_session_pointer) → runner = TurnRunner(bot, config,
      capabilities=getattr(bot, 'capabilities', None)) → INLINE & interactive: AgentREPL.run();
      INLINE & non-TTY: AgentREPL.run_batch(sys.stdin); TUI: ``from parrot.cli.tui.app import AgentWorkspaceApp``
      (lazy) → ``await app.run_async()`` → SystemExit(code)."""
  ```

### Module 14: devloop convergence
- **Path**: `packages/ai-parrot/src/parrot/cli/devloop/renderer.py`, `devloop/console.py` *(modifies)*
- **Responsibility**: FEAT-519 Module 6 — `RunView` keeps its constructor and
  `poll_once`/handlers, but `pause`/`resume`/`_live` (`devloop/renderer.py:82-96`,
  `:103-107`) delegate to a `LiveRegion`; `DevLoopConsole` replaces each manual
  `pause()`…`resume()` pair (`console.py:907/:940/:969`, `:1102/:1114`,
  `:1119/:1133`, `:1138/:1146`) with `with view.region.modal():`. **No
  behaviour change**; `tests/cli/devloop/` stays green.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # parrot/cli/devloop/renderer.py  (modifies devloop/renderer.py:26-110)
  class RunView:
      region: LiveRegion                    # replaces self._live / self._paused
      def pause(self) -> None: ...          # → self.region.pause()
      def resume(self) -> None: ...         # → self.region.resume()
      async def run_live(self, stop_event: Optional[asyncio.Event] = None) -> None:
          """Same loop; ``region.start()``/``region.update(self._build_display())``/``region.stop()``."""
  ```

### Module 15: agentd migration
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/cli.py`,
  `agentd/proxy.py` *(modifies)*
- **Responsibility**: FEAT-519 Module 7 — `_run_attach` (`cli.py:156`)
  registers `repl.add_post_turn_hook(...)` that prints `proxy.drain_events()`
  (`proxy.py:237`); delete `_wrap_with_event_drain` (`cli.py:205-230`); module
  `Console()` (`cli.py:30`) → `get_console()`; `_DaemonBotProxy` (`proxy.py:62`)
  gains `capabilities = BackendCapabilities(streaming=True, live_tool_events=False, usage=False, resume=False)`;
  daemon slash handlers (`proxy.py:374`) are typed against `CommandContext`
  (they only use `renderer.print/render_table/render_info` and `config`).
- **Depends on**: M7, M8.
- **Interface Skeleton**:
  ```python
  # parrot/integrations/agentd/cli.py  (modifies)
  async def _run_attach(name_or_socket: str, no_stream: bool) -> None:
      """... repl = AgentREPL(bot=bot, config=config, renderer=renderer)
      register_daemon_commands(repl, proxy)
      repl.add_post_turn_hook(_drain_events_hook(proxy))   # replaces _wrap_with_event_drain(repl, proxy) at cli.py:183"""
  def _drain_events_hook(proxy: DaemonAgentProxy) -> PostTurnHook:
      """Return ``async def hook(ctx, turn)`` that prints each drained line dim via ``ctx.renderer.print``."""
  ```

### Module 16: Tests
- **Path**: `packages/ai-parrot/tests/cli/` (+ `tests/cli/tui/`), `packages/ai-parrot-server/tests/handlers/`, `packages/ai-parrot-integrations/tests/agentd/`
- **Responsibility**: §4. Keep `test_integration.py` (FEAT-168) green with
  minimal edits (the `repl.history` alias and unchanged `send`/`send_stream`
  signatures exist for that reason).
- **Depends on**: all modules above.

### Module 17: Documentation
- **Path**: `docs/cli/parrot-agent.md` *(new)*, `docs/agentd.md` (one-line note that `attach` uses the post-turn hook)
- **Responsibility**: modes, keybindings, resume, history location, server
  mode routes/token, non-TTY usage, troubleshooting (TERM=dumb, piping).
- **Depends on**: M13.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_live_region_non_tty_prints_sequentially` | M1 | `Console(file=StringIO())` (not a terminal): `update()` prints once, output has no `\x1b[` cursor-control sequences, `modal()` is a no-op |
| `test_live_region_modal_pauses_and_resumes` | M1 | with a terminal console (`force_terminal=True`, `file=StringIO`), `modal()` calls `Live.stop()` then `Live.start()` (spy) |
| `test_get_console_singleton_and_override` | M1 | same object twice; `set_console` replaces; `reset_console` restores |
| `test_resolve_ui_mode_matrix` | M2 | parametrised over (tty,tty,term) → INLINE/TUI; `TERM=dumb` → INLINE; explicit TUI on non-TTY raises |
| `test_state_paths_honour_parrot_home_and_perms` | M2 | `monkeypatch.setenv("PARROT_HOME", tmp)`; files created `0o600`, dir `0o700`; slug sanitisation |
| `test_session_pointer_roundtrip_and_invalid_json` | M2 | save → load equal; corrupt file → None |
| `test_turn_scope_predicate_survives_create_task` | M3 | set scope, `create_task` an emitter, predicate True inside, False in another task |
| `test_turn_event_seq_monotonic_and_terminal_once` | M4/M5 | fake bot yields 3 deltas + AIMessage → STARTED, 3 DELTA, 1 COMPLETED; `seq` 0..4 |
| `test_runner_batch_mode_uses_ask` | M5 | `streaming=False` → `bot.ask` called with `session_id`, `output_mode=OutputMode.TERMINAL`, `permission_context`; `user_id` omitted when None |
| `test_runner_live_tool_events_scoped` | M5 | inside `scope()` from lifecycle, a fake tool emits Before/After with the runner's turn scope → ToolStarted/ToolFinished with equal `call_id`; events emitted outside the scope are ignored |
| `test_runner_cancel_yields_cancelled_and_closes_stream` | M5 | slow async generator; `cancel()` → `TurnCancelled(partial_text)`; generator `aclose` called; history length unchanged; hooks not run |
| `test_runner_failure_preserves_partial` | M5 | generator raises after 2 deltas → `TurnFailed(partial_text=…)`, no exception escapes |
| `test_runner_rejects_second_turn` | M5 | `TurnInProgressError` while active |
| `test_runner_load_history_maps_memory_turns` | M5 | fake `get_conversation_history` returns memory `ConversationHistory` with 2 turns and a `tool_invocations` entry → 2 CLI turns, `tool_calls` populated, `config.session_id` updated |
| `test_runner_post_turn_hook_after_completed_only` | M5 | hook called once per COMPLETED, never on CANCELLED/FAILED |
| `test_renderer_stream_chunk_never_writes_stdout` | M6 | `capsys`: `render_stream_chunk` writes nothing to `sys.stdout`; region `update` called with `Markdown` |
| `test_renderer_partial_markdown_does_not_raise` | M6 | unclosed code fence and table mid-stream |
| `test_renderer_usage_unknown_not_zero` | M6 | `usage=None` → "n/a", never `total=0` |
| `test_renderer_render_history` | M6 | header + N turns rendered |
| `test_dispatcher_uses_command_context` | M7 | a minimal `CommandContext` stub (no `AgentREPL`) runs `/tools`, `/info`, `/clear`, `/help`; `/clear` calls `runner.reset_session` |
| `test_cmd_resume_last_and_missing_capability` | M7 | `last` resolves via pointer; `capabilities.resume=False` → error message, no call |
| `test_cmd_export_contract_unchanged` | M7 | JSON keys `session_id, agent_name, user_id, exported_at, turns[]` |
| `test_repl_ctrl_c_cancels_active_turn` | M8 | inject `KeyboardInterrupt` while a turn task runs → `runner.cancel()` awaited, "Interrupted" rendered, prompt loop continues |
| `test_repl_file_history_used_when_enabled` | M8 | `PromptSession` built with `FileHistory(history_path(agent))`; `history_enabled=False` → `InMemoryHistory` |
| `test_repl_run_batch_plain_output` | M8 | two stdin lines → two turns, exit 0, no ANSI cursor-control in output |
| `test_repl_no_logger_level_mutation` | M8 | root handler levels identical before/after a streamed turn |
| `test_server_proxy_routes_and_token` | M9 | `aiohttp` test server: `/api/v1/bots`, `/api/v1/chatbots/{name}`, `/api/v1/agents/chat/{name}` hit with `Authorization: Bearer`; `user_id` absent when None |
| `test_server_proxy_sse_parsing` | M9 | fixture stream of `content` / `tool_event` / `ai_message` / `[DONE]` frames → str, ToolStarted, ToolFinished, final response with `tool_calls` and `usage` |
| `test_server_proxy_sse_without_tool_frames` | M9 | older server (no `tool_event`) still yields text and final |
| `test_stream_sse_emits_tool_event_frames` | M10 | fake bot whose `ask_stream` executes a fake `AbstractTool` → frames contain `tool_event` started/finished between deltas; concurrent second request's events do not leak (two scopes) |
| `test_tui_submit_streams_and_follows` | M11 | `App.run_test()`: type + `enter` → panel appears, deltas rendered, transcript anchored |
| `test_tui_second_submit_rejected_while_active` | M11 | notify shown, composer text kept |
| `test_tui_ctrl_c_cancels_then_quits` | M11 | first `ctrl+c` during turn → cancelled panel; idle double press → app exits code 0 |
| `test_tui_tool_activity_rows` | M11 | ToolStarted/Finished/Failed rows and states; `f2` toggles collapse |
| `test_tui_history_navigation_and_completion` | M11 | `up` recalls previous entry; `/he` + `tab` → `/help` |
| `test_tui_scrollback_stops_follow_end_resumes` | M11 | scroll up → `following=False`; `end` → True |
| `test_tui_resize_narrow_collapses_details` | M11 | `run_test(size=(50, 20))` → tool panels collapsed, composer visible |
| `test_tui_slash_quit_exits_cleanly` | M12 | `/quit` → `SystemExit` caught → `App.exit(0)` |
| `test_tui_logs_routed_to_drawer` | M12 | a `logging.warning` during a turn lands in the drawer, not in the transcript |
| `test_agent_command_ui_option_and_non_tty_rules` | M13 | `CliRunner`: `--ui tui` non-TTY → exit 2; no name non-TTY → exit 2; `--ui inline` runs REPL; `--session last` resolves pointer |
| `test_agent_command_lazy_tui_import` | M13 | with `--ui inline`, `parrot.cli.tui` not in `sys.modules` |
| `test_runview_delegates_to_live_region` | M14 | `pause/resume` call region; existing `tests/cli/devloop/test_renderer.py` unchanged and green |
| `test_attach_uses_post_turn_hook` | M15 | `_wrap_with_event_drain` absent; drained lines printed after a turn |

### Integration Tests
| Test | Description |
|---|---|
| `test_inline_end_to_end_fake_bot` | `CliRunner` + patched `StandaloneAgentLoader`: two queries and `/export` in batch mode; exported JSON has 2 turns |
| `test_tui_end_to_end_fake_bot_with_tools` | `run_test()` with a fake bot that emits lifecycle tool events under the runner's scope; final panel shows tool details and usage |
| `test_server_mode_end_to_end` | `aiohttp` test app mounting a real `StreamHandler` + minimal `bots`/`chatbots` views; CLI proxy streams deltas and tool frames |
| `test_resume_roundtrip_standalone` | fake bot with `InMemoryConversation`: run a turn, restart with `--session last`, history rendered |
| `test_existing_feat168_suite` | `pytest packages/ai-parrot/tests/cli/test_integration.py -v` passes unmodified except the two documented edits |

### Test Data / Fixtures
```python
# tests/cli/conftest.py additions (existing fixtures mock_agent/repl_config/renderer/... kept)
@pytest.fixture
def quiet_console():
    """Console(file=io.StringIO(), force_terminal=True, width=100) installed via set_console(); reset after."""

@pytest.fixture
def fake_streaming_bot():
    """AsyncMock bot whose ask_stream yields deltas then an AIMessage-like object; ask returns the same object;
    exposes get_conversation_history returning a memory ConversationHistory when asked."""

@pytest.fixture
def lifecycle_scope():
    """with parrot.core.events.lifecycle.scope() as reg: yield reg  — isolates the global registry."""

@pytest.fixture
def tool_emitting_bot(lifecycle_scope):
    """Bot whose ask_stream, between two deltas, runs a fake AbstractTool subclass so Before/After events are
    emitted inside the caller's task context (and therefore inside the runner's turn_scope)."""

@pytest.fixture
def sse_frames():
    """List of bytes: data:{"content":"Hel"} / data:{"type":"tool_event",...} / data:{"type":"ai_message",...} / data:[DONE]"""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC1 (G2)** `parrot agent <name>` on a TTY with `TERM≠dumb` starts the Textual workspace; `--ui inline` starts the inline console; `--ui tui` on a non-TTY exits 2 with a hint.
- [ ] **AC2 (G2)** Piping works: `printf 'hi\n' | parrot agent <name>` produces plain text with no `\x1b[?1049h` (alternate screen) and no cursor-control sequences; omitting the name on a non-TTY exits 2 without opening the picker.
- [ ] **AC3 (G1)** During generation the composer accepts input, PageUp/PageDown scroll the transcript, scrolling back stops auto-follow and `End` resumes it.
- [ ] **AC4 (G1)** A second submission while a turn is active is rejected with a visible notice and the typed text is kept; nothing is queued.
- [ ] **AC5 (G3)** Inline and TUI presenters consume the same `TurnRunner.run_turn()` stream; `grep -n "ask_stream\|bot.ask(" packages/ai-parrot/src/parrot/cli/repl.py packages/ai-parrot/src/parrot/cli/tui/*.py` is empty (only `session.py` calls the bot).
- [ ] **AC6 (G4)** With a standalone agent that calls a tool, a tool row appears while the tool runs (before the final message) and is updated with duration on completion; events from other turns are not shown.
- [ ] **AC7 (G4)** In server mode the same behaviour holds over SSE `tool_event` frames; against a server without those frames the client still renders text and final tool details.
- [ ] **AC8 (G4)** Tool details and usage are shown only when supplied; unknown usage renders `n/a`, never `0`; no tool row is ever inferred from model text.
- [ ] **AC9 (G5)** `parrot agent <name> --session last` and `/resume <id>` render the prior conversation from `bot.get_conversation_history()` and continue it under the same `session_id`; backends with `resume=False` print an explicit error.
- [ ] **AC10 (G6)** Composer history persists across launches in `$PARROT_HOME/cli/history/<slug>.txt` with mode `0o600`; `--no-history` disables it; conversation resume does not depend on it.
- [ ] **AC11 (G7)** `grep -n 'sys.stdout.write' packages/ai-parrot/src/parrot/cli/renderer.py` is empty; `_BlockingSafeFile`, `_mute_stream_loggers`, `_restore_stream_loggers`, `_STREAM_LOG_FLOOR` and every `file=sys.__stdout__` are deleted from `cli/`.
- [ ] **AC12 (G7)** Exactly one `Console(` construction remains in `parrot/cli/` (inside `console.py`); `agent_repl.py`, `repl.py`, `renderer.py`, `devloop/renderer.py`, `devloop/console.py` and `agentd/cli.py` obtain it via `get_console()`.
- [ ] **AC13 (G7)** Streamed responses render Markdown, code highlighting and wrapping at the same fidelity as `--no-stream`.
- [ ] **AC14 (G7)** Log records emitted during a stream do not interleave with streamed tokens, and no code path mutates logging handler levels (inline: rendered inside the `LiveRegion`; TUI: routed to the log drawer).
- [ ] **AC15 (G7)** `AgentREPL.add_post_turn_hook()` exists and `agentd attach` uses it; `_wrap_with_event_drain` is deleted.
- [ ] **AC16 (G8)** No reference to `/api/agent/` or `/api/agents` remains in `loaders.py`; server mode uses `GET /api/v1/bots`, `GET /api/v1/chatbots/{name}`, `POST /api/v1/agents/chat/{agent_id}`, `POST /bots/{bot_id}/stream/sse`, sending `Authorization: Bearer` when `--token`/`PARROT_SERVER_TOKEN` is set and omitting `user_id` unless `--user` was given.
- [ ] **AC17 (G8)** `StreamHandler.stream_sse` emits `tool_event` frames scoped to its own request; two concurrent SSE requests never receive each other's tool events (test).
- [ ] **AC18 (G9)** Ctrl+C during a turn cancels the active task, closes the async iterator, marks the partial answer *interrupted*, does not append a history turn and does not run post-turn hooks; Ctrl+C at an idle prompt does not exit (inline hint / TUI double-press).
- [ ] **AC19 (G9)** A backend exception mid-stream preserves the prompt and partial answer, shows a recoverable error, and never automatically replays the request.
- [ ] **AC20 (G10)** `/clear` issues a new `session_id` and clears the transcript; `/export` JSON keys are unchanged; `/stream` toggles; `/tools`, `/info`, `/help`, `/quit`, `/exit` and agentd's `/status`, `/schedules`, `/invoke` work in both modes.
- [ ] **AC21 (G10)** `bot.ask`/`bot.ask_stream` receive `session_id`, `output_mode=OutputMode.TERMINAL` and `permission_context` exactly as before; the FEAT-266 device-code bootstrap and the bot `cleanup()` on exit are unchanged.
- [ ] **AC22** The TUI is imported lazily: `parrot.cli.tui` is not in `sys.modules` after `parrot agent --ui inline` or `--list`; `import parrot.cli` does not import `textual`.
- [ ] **AC23** `pyproject.toml` declares `textual>=8.2,<9`; `uv lock` resolves for Python 3.11, 3.12 and 3.13; no other new runtime dependency.
- [ ] **AC24** `sdd/specs/new-cli-infra.spec.md` status reads `superseded by FEAT-573`.
- [ ] **AC25** `pytest packages/ai-parrot/tests/cli/ -v` (incl. `test_integration.py` and `devloop/`), `pytest packages/ai-parrot-server/tests/handlers/test_stream*.py -v`, `pytest packages/ai-parrot-integrations/tests/agentd/ -v` pass; `ruff check` and `mypy` clean on changed files.
- [ ] **AC26** `docs/cli/parrot-agent.md` documents modes, keys, resume, history location, server mode and non-TTY usage.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified on `dev` at `4c787a527`
> (2026-09-18). Line numbers are for the files as read today; re-verify before
> editing if `cli/` moves.

### Verified Imports
```python
from rich.console import Console                      # verified: renderer.py:13
from rich.markdown import Markdown                    # verified: renderer.py:14
from rich.panel import Panel                          # verified: renderer.py:15
from rich.table import Table                          # verified: renderer.py:16
from rich.text import Text                            # verified: renderer.py:17
from rich.live import Live                            # verified: devloop/renderer.py:15
from rich.console import Console, Group               # verified: devloop/renderer.py:14
from prompt_toolkit import PromptSession              # verified: repl.py:14
from prompt_toolkit.completion import WordCompleter   # verified: repl.py:15
from prompt_toolkit.history import InMemoryHistory    # verified: repl.py:16
from prompt_toolkit.history import FileHistory        # verified: importable, prompt_toolkit 3.0.47 (append_string/load_history_strings/get_strings)
from prompt_toolkit.patch_stdout import patch_stdout  # verified: repl.py:17
import questionary                                    # verified: loaders.py:17 (core dep pyproject.toml:165)
import aiohttp                                        # verified: loaders.py:16
from parrot.bots.abstract import AbstractBot          # verified: repl.py:21
from parrot.cli.commands import ConversationTurn, SlashCommand, SlashCommandDispatcher   # verified: repl.py:22
from parrot.cli.renderer import ResponseRenderer      # verified: repl.py:23, agent_repl.py:22, agentd/cli.py:19
from parrot.cli.repl import AgentREPL, REPLConfig     # verified: agent_repl.py:21, agentd/cli.py:20
from parrot.cli.identity import bot_declares_o365_device_code, build_cli_permission_context   # verified: agent_repl.py:19
from parrot.cli.loaders import AgentLoadError, ServerAgentProxy, StandaloneAgentLoader        # verified: agent_repl.py:20
from parrot.models.outputs import OutputMode          # verified: repl.py:24 (TERMINAL = "terminal", outputs.py:29)
from parrot.models.responses import AIMessage         # verified: repl.py:25
from parrot.models.basic import ToolCall, CompletionUsage   # verified: basic.py:23, :48
from parrot.core.events.lifecycle import (            # verified: core/events/lifecycle/__init__.py:19-22, :39-41, :91-97
    LifecycleEvent, EventRegistry, get_global_registry, scope, EventEmitterMixin,
    BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent, BeforeInvokeEvent, AfterInvokeEvent)
from navigator_eventbus.lifecycle.trace import TraceContext   # verified: navigator-eventbus 0.3.0 (new_root(), child(), trace_id, span_id)
from parrot.memory.abstract import ConversationHistory, ConversationTurn as MemoryTurn   # verified: memory/abstract.py:274, :102
from parrot.auth.permission import PermissionContext  # verified: auth/permission.py:81
# Textual 8.2.8 (to be added by M0; verified against the wheel in an isolated target dir):
from textual.app import App, ComposeResult
from textual.screen import Screen, ModalScreen
from textual.widgets import Markdown, TextArea, Input, Footer, Header, Static, Collapsible, RichLog, Label
from textual.widgets._markdown import MarkdownStream  # Markdown.get_stream() -> MarkdownStream; async write()/stop()
from textual.containers import VerticalScroll, Vertical, Horizontal
from textual import work, on, events
from textual.binding import Binding
from textual.message import Message
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/cli/agent_repl.py
console = Console(file=sys.__stdout__, force_terminal=True)                     # line 25  (TO BE DELETED → get_console())
def agent(name: Optional[str], list_agents: bool, server: Optional[str], no_stream: bool) -> None   # line 49
async def _run(name, list_agents, server, no_stream) -> None                    # line 75  (permission ctx 124-133; REPLConfig 138-144; repl.run 147; cleanup finally 154-163)
async def _handle_list(loader, renderer, server) -> None                        # line 166
def _print_banner(bot: object, name: str, server: Optional[str]) -> None        # line 211

# packages/ai-parrot/src/parrot/cli/repl.py
_STREAM_LOG_FLOOR = logging.WARNING                                             # line 30  (TO BE DELETED)
def _mute_stream_loggers() -> dict[int, int]                                    # line 33  (TO BE DELETED)
def _restore_stream_loggers(saved: dict[int, int]) -> None                      # line 52  (TO BE DELETED)
class REPLConfig(BaseModel):                                                    # line 61
    agent_name: str; streaming: bool = True; server_url: Optional[str] = None   # lines 82-84
    session_id: str = Field(default_factory=lambda: str(uuid4()))               # line 85
    user_id: str = "cli-user"; permission_context: Optional[Any] = None         # lines 86-87
class AgentREPL:                                                                # line 92
    def __init__(self, bot: AbstractBot, config: REPLConfig, renderer: ResponseRenderer) -> None   # line 109 (console at 128)
    async def run(self) -> None                                                 # line 131 (PromptSession 147-150; patch_stdout 154; prompt_async 157; dispatch 179; KeyboardInterrupt 190)
    async def send(self, query: str) -> AIMessage                               # line 200 (bot.ask kwargs 212-218)
    async def send_stream(self, query: str) -> None                             # line 228 (mute 247; ask_stream kwargs 249-255; chunk loop 256-271; restore 279)
    def register_command(self, cmd: SlashCommand) -> None                       # line 296
class _StreamedResponse: def __init__(self, query: str, output: str) -> None    # lines 305, 317 (output/response/tool_calls=[]/usage=None)

# packages/ai-parrot/src/parrot/cli/renderer.py
class _BlockingSafeFile                                                         # lines 22-56 (TO BE DELETED)
class ResponseRenderer:                                                         # line 59
    def __init__(self) -> None   # console = Console(file=_BlockingSafeFile(sys.__stdout__), force_terminal=True)   # lines 69, 80-82
    def render(self, response: AIMessage) -> None                               # line 89  (output/response fallback 98-112)
    def _render_tool_calls(self, tool_calls: List[Any]) -> None                 # line 124 (uses .name/.arguments/.result/.error)
    def _render_usage(self, usage: Any) -> None                                 # line 153
    def render_error(self, error: Exception) -> None                            # line 175
    def render_table(self, headers, rows, title=None) -> None                   # line 195
    def render_info(self, lines: List[tuple[str, str]]) -> None                 # line 215
    def render_stream_start(self) -> None                                       # line 233
    def render_stream_chunk(self, text: str) -> None                            # line 248 (sys.stdout.write at 257 — ROOT CAUSE)
    def render_stream_end(self, response: Optional[AIMessage] = None) -> None   # line 262
    def print(self, *args: Any, **kwargs: Any) -> None                          # line 282

# packages/ai-parrot/src/parrot/cli/commands.py
@dataclass class SlashCommand: name: str; description: str; handler: Callable   # line 23
@dataclass class ConversationTurn: query: str; response: Any; timestamp: datetime; def to_dict()   # lines 38, 51
class SlashCommandDispatcher:                                                   # line 70
    def register(self, cmd: SlashCommand) -> None                               # line 86
    async def dispatch_async(self, input_text: str, repl: "AgentREPL") -> bool  # line 95
    def get_completions(self) -> List[str]                                      # line 130
    def _register_builtins(self) -> None                                        # line 142 (list 144-163: tools, info, clear, export, stream, create_agent, help, quit)
async def _cmd_tools / _cmd_info / _cmd_clear / _cmd_export / _cmd_stream / _cmd_help / _cmd_quit / _cmd_create_agent   # lines 173, 193, 221, 238, 279, 291, 308, 347
# _cmd_clear resets session_id + history (228-230); _cmd_export payload keys (258-264); _cmd_quit raises SystemExit(0) (319); _cmd_create_agent builds CLIHumanChannel(console=repl.renderer.console) (373)

# packages/ai-parrot/src/parrot/cli/loaders.py
class AgentLoadError(Exception): def __init__(self, agent_name, suggestions=None, message=None)   # lines 24, 32
class StandaloneAgentLoader: async def load(name) / list_agents() / select_agent()   # lines 56, 107, 132, 141 (questionary.select 160)
class _ServerBotProxy:                                                          # line 169
    def __init__(self, name: str, server_url: str, session: aiohttp.ClientSession) -> None   # line 183
    async def ask(self, question, session_id=None, user_id=None, output_mode=None, **kwargs) -> Any   # line 209 (POST /api/agent/{name}/ask at 233 — PHANTOM ROUTE)
    async def ask_stream(self, question, session_id=None, user_id=None, output_mode=None, **kwargs)  # line 251 (local 50-char chunker 274-288)
    def get_available_tools() / get_tools_count() / has_tools()                 # lines 290, 298, 306
class _ServerResponse: def __init__(self, data: Dict[str, Any])                 # lines 315, 324 (output/response/tool_calls=[]/usage=None)
class ServerAgentProxy:                                                         # line 341
    def __init__(self, server_url: str, timeout: int = 30) -> None              # line 352
    async def load(self, name: str) -> _ServerBotProxy                          # line 379 (GET /api/agent/{name} at 394 — PHANTOM ROUTE)
    async def list_agents(self) -> List[Dict[str, Any]]                         # line 414 (GET /api/agents at 424 — PHANTOM ROUTE)
    async def select_agent(self) -> str                                         # line 440
    async def close(self) -> None                                               # line 461

# packages/ai-parrot/src/parrot/cli/__init__.py
@click.group(cls=LazyGroup) def cli()                                           # line 104
cli._lazy_commands = {..., "agent": "parrot.cli.agent_repl", ...}               # lines 117-119 (function must stay named `agent`)

# packages/ai-parrot/src/parrot/cli/devloop/renderer.py
class RunView: def __init__(self, host, console=None, *, run_id="")            # lines 26, 29
    def pause(self) / resume(self) / stop(self)                                 # lines 82, 88, 94 (Live.stop()/Live.start())
    async def run_live(self, stop_event=None)  # Live(..., refresh_per_second=8, transient=False)   # lines 98, 103-107
# packages/ai-parrot/src/parrot/cli/devloop/console.py — patch_stdout import :17, RunView( :781/:804, patch_stdout() :816,
#   prompt_async("devloop> ") :885, pause/resume pairs :907/:940/:969, :1102/:1114, :1119/:1133, :1138/:1146

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, EventEmitterMixin, ToolInterface, VectorInterface, ABC)   # line 201
    self.conversation_memory: Optional[ConversationMemory] = None              # line 575
    def memory_key_id(self) -> str                                              # line 1951 (property)
    async def get_conversation_history(self, user_id: str, session_id: str, chatbot_id: Optional[str] = None) -> Optional[ConversationHistory]   # line 2360
    async def save_conversation_turn(self, user_id, session_id, turn, *, compaction=None) -> None   # line 2378 (sole writer — CLI never calls it)
    def get_tools_count(self) -> int / has_tools(self) -> bool / get_available_tools(self) -> List[str]   # lines 4339, 4344, 4348
    async def ask(self, question, session_id=None, user_id=None, ..., output_mode=OutputMode.DEFAULT, ..., trace_context=None, **kwargs) -> AIMessage   # line 4533
    async def ask_stream(self, question, session_id=None, user_id=None, ...) -> AsyncIterator[Union[str, AIMessage]]   # line 4588 (str deltas, final AIMessage)
    async def cleanup(self) -> None                                             # line 5017
# packages/ai-parrot/src/parrot/bots/base.py — BaseBot.ask_stream :1733 (permission_context :1747, trace_context :1751, **kwargs);
#   BeforeInvokeEvent + self._current_trace_context :1785-1790; client deltas yielded :2004; final `yield ai_message` :2127

# packages/ai-parrot/src/parrot/memory/abstract.py
@dataclass class ConversationTurn:  turn_id, user_id, user_message, assistant_response, context_used, tools_used, timestamp, metadata,
    chatbot_id, tool_invocations: List[ToolInvocation], error, token_count, state, schema_version, norm_version   # lines 102-132
@dataclass class ConversationHistory: session_id, user_id, chatbot_id, turns: List[ConversationTurn], created_at, updated_at, metadata   # lines 274-283
class ConversationMemory(ABC): async def get_history(self, user_id, session_id, chatbot_id=None) -> Optional[ConversationHistory]   # lines 335, 429

# packages/ai-parrot/src/parrot/models/responses.py — class StreamChunk :53; class AIMessage :75 (output :78, response :79,
#   usage: CompletionUsage :101, tool_calls: List[ToolCall] :115, def to_dict() -> model_dump() :302)
# packages/ai-parrot/src/parrot/models/basic.py — class ToolCall(id, name, arguments, result, error, execution_time) :23; class CompletionUsage :48

# packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py
class BeforeToolCallEvent(LifecycleEvent): tool_name, tool_class, args_summary: dict   # line 12
class AfterToolCallEvent(LifecycleEvent): tool_name, duration_ms, result_status, result_size_bytes   # line 30
class ToolCallFailedEvent(LifecycleEvent): tool_name, duration_ms, error_type, error_message   # line 74
# every LifecycleEvent has trace_context: TraceContext (trace_id, span_id, parent_span_id) and timestamp
# packages/ai-parrot/src/parrot/tools/abstract.py — AbstractTool.execute :872; tool_tc = pctx.trace_context.child() if pctx else TraceContext.new_root() :938-939;
#   BeforeToolCallEvent emit_nowait :946-951; AfterToolCallEvent await emit :1130-1132; ToolCallFailedEvent :1172 — all three share tool_tc
# navigator_eventbus.lifecycle.registry.EventRegistry (0.3.0):
#   def subscribe(self, event_type: Type[E], callback: AsyncSubscriber, *, where: Optional[Callable[[E], bool]] = None, forward_to_bus: bool = False) -> str
#   def unsubscribe(self, subscription_id: str) -> bool ; async def emit(event) ; def emit_nowait(event)  # emit_nowait → loop.create_task(self.emit(event))
#   _forward_to_global_safely(event) → asyncio task on the running loop (context copied) when the global registry has a matching subscriber

# packages/ai-parrot-server/src/parrot/handlers/stream.py
class StreamHandler(BaseHandler)                                                # line 13 (no per-view auth decorator; global middleware, see docstring 18-30)
    def _extract_stream_params(self, payload, *extra_ignored_keys) -> (prompt, kwargs)   # line 57 ('prompt' key; rest → ask_stream kwargs)
    async def stream_sse(self, request) -> web.StreamResponse                   # line 64 (frames: {'content': chunk} :90; {'type':'ai_message','data':…} :95; [DONE] :97; 'error:' :106)
    def configure_routes(self, app)   # add_post('/bots/{bot_id}/stream/sse') :467, ndjson :469, chunked :471, add_get ws :473   # line 446
# packages/ai-parrot-server/src/parrot/manager/manager.py — /api/v1/chat/{chatbot_name} ChatHandler :2286; /api/v1/agents/chat/{agent_id}[/{method_name}] AgentTalk :2289-2290;
#   /api/v1/chatbots[/{name}] BotHandler :2488-2489; ChatbotHandler.configure(app, "/api/v1/bots") :2482; StreamHandler().configure_routes :2493-2494
# packages/ai-parrot-server/src/parrot/handlers/agent.py — @is_authenticated() @user_session() class AgentTalk(BaseView) :111-113;
#   async def post :1462 (stream=true → chunked text/plain with a trailing "\n\x00" metadata envelope :1501-1502); user_id precedence: explicit body first :879-902
# packages/ai-parrot-server/src/parrot/handlers/chat.py — class BotHandler(BaseView) :594? (GET :118: with chatbot_name → info dict :166-186 (404 when unknown); without → welcome message)
# packages/ai-parrot-server/src/parrot/handlers/bots.py — class ChatbotHandler :424; async def get :649 ("GET /api/v1/bots — list all agents" → _get_all(); "/{id}" → _get_one)

# packages/ai-parrot-integrations/src/parrot/integrations/agentd/cli.py — console = Console() :30; def attach :146; async def _run_attach :156
#   (register_daemon_commands :182; _wrap_with_event_drain :183); def _wrap_with_event_drain :205 (TO BE DELETED); def _print_drained_events :232
# packages/ai-parrot-integrations/src/parrot/integrations/agentd/proxy.py — class _DaemonResponse :39; class _DaemonBotProxy :62 (ask :87, ask_stream :113 — yields str deltas only);
#   class DaemonAgentProxy :178 (drain_events :237); def register_daemon_commands(repl: AgentREPL, proxy) :374
# packages/ai-parrot-integrations/src/parrot/integrations/agentd/client.py — class StreamEvent(kind: "delta"|"complete"|"error", text, response, usage, error) :98

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py — def parrot_home() -> Path (PARROT_HOME env, default ~/.parrot) :1009
# packages/ai-parrot/src/parrot/conf.py — _parrot_home_default = str(Path.home() / ".parrot") :556
# packages/ai-parrot/pyproject.toml — requires-python ">=3.11,<3.14" :18; "rich>=13.0" :131; "prompt_toolkit>=3.0" :136; "questionary>=2.1.1" :165
# sdd/specs/new-cli-infra.spec.md — **Status**: draft :24
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `LiveRegion` | `rich.live.Live` | `Live(..., refresh_per_second=8, transient=False)`; `stop()/start()` for pause/resume | `devloop/renderer.py:82-92, 103-107` |
| `ResponseRenderer.render_stream_chunk` | `LiveRegion.update(Markdown(buffer))` | replaces `sys.stdout.write` | `renderer.py:257` |
| `TurnRunner.run_turn` | `bot.ask_stream(question=…, session_id=…, user_id=…, output_mode=OutputMode.TERMINAL, permission_context=…)` | same kwargs as today | `repl.py:249-255`; `bots/abstract.py:4588` |
| `TurnRunner.run_turn` (batch) | `bot.ask(...)` | same kwargs | `repl.py:212-218`; `bots/abstract.py:4533` |
| `TurnRunner` tool events | `get_global_registry().subscribe(BeforeToolCallEvent…, cb, where=in_turn_scope(id))` | predicate on `TURN_SCOPE` | `lifecycle/__init__.py:21-22`; registry `subscribe` signature |
| `TurnRunner.load_history` | `bot.get_conversation_history(user_id, session_id)` | returns `ConversationHistory` or None | `bots/abstract.py:2360-2367` |
| `AgentREPL.run` | `PromptSession(history=FileHistory(history_path(agent)))` inside `region.modal()` | replaces `InMemoryHistory` + bare `prompt_async` | `repl.py:147-157` |
| `_ServerBotProxy.ask_stream` | `POST /bots/{bot_id}/stream/sse` | SSE `data:` frames | `stream.py:467, 86-97` |
| `_ServerBotProxy.ask` | `POST /api/v1/agents/chat/{agent_id}` (`stream=false`) | JSON | `manager.py:2289`; `agent.py:1462-1478` |
| `ServerAgentProxy.load` / `list_agents` | `GET /api/v1/chatbots/{name}` / `GET /api/v1/bots` | JSON | `manager.py:2489, 2482`; `chat.py:166-186`; `bots.py:649-660` |
| `StreamHandler.stream_sse` | `turn_scope` + global registry | enqueue frames between deltas | `stream.py:86-97` |
| `agentd attach` | `AgentREPL.add_post_turn_hook` | replaces instance monkeypatch | `agentd/cli.py:183, 205-230` |
| `RunView` | `LiveRegion` | delegation | `devloop/renderer.py:40-41, 82-96` |
| `TUICommandContext.suspend` | `textual.app.App.suspend()` | context manager restoring the terminal | Textual 8.2.8 (verified) |
| `AgentWorkspaceApp` transcript | `Markdown.get_stream()` → `MarkdownStream.write(fragment)` / `stop()` | async streaming Markdown | Textual 8.2.8 (verified) |

### Does NOT Exist (Anti-Hallucination)
- ~~`GET/POST /api/agent/{name}`, `/api/agent/{name}/ask`, `/api/agents`~~ — **the server registers none of these**; the current proxy is broken against the real server. Real routes are listed above.
- ~~server SSE `tool_event` frames~~ — do not exist yet; **M10 adds them**. Today `stream_sse` emits only `{'content': …}`, `{'type': 'ai_message', …}`, `[DONE]`.
- ~~a conversation-history HTTP endpoint~~ — none under `/api/v1/agents/...` or `/api/v1/chat/...`; server-mode resume is impossible without one (§8 Q9).
- ~~`parrot.cli.console`, `parrot.cli.modes`, `parrot.cli.events`, `parrot.cli.session`, `parrot.cli.tui`~~ — the modules this spec creates; none exist today.
- ~~`parrot.core.events.lifecycle.turn_scope`~~ — created by M3.
- ~~`AgentREPL.add_post_turn_hook`, `.on_turn_end`, `.hooks`~~ — no hook mechanism exists in `repl.py`; that is why `agentd` monkeypatches (`agentd/cli.py:205-230`).
- ~~`ResponseRenderer.render_markdown()`, `.render_live()`, `.render_turn_event()`, `.render_history()`~~ — not real today; the last two are added by M6.
- ~~`EventRegistry.subscribe(..., forward_to_global=...)`~~ — `docs/lifecycle_events.md` describes such a flag but the real signature (navigator-eventbus 0.3.0) is `subscribe(event_type, callback, *, where=None, forward_to_bus=False)`. Forwarding to the global registry is a property of the *emitting* registry (`EventEmitterMixin._init_events(forward_to_global=True)`), not of a subscription.
- ~~`bot.events.subscribe(BeforeToolCallEvent, …)` receiving tool events~~ — tool events are emitted on the **tool's** registry and forwarded to the **global** registry; the bot's registry never sees them. Subscribe on `get_global_registry()`.
- ~~filtering tool events by `trace_context.trace_id == the turn's trace id`~~ — unreliable: `AbstractTool.execute` mints `TraceContext.new_root()` when no `PermissionContext` carries a trace (`tools/abstract.py:938-939`), and `ToolManager` does not inject the bot's `_current_trace_context`. Use `turn_scope` (M3).
- ~~`ToolManager.add_result_hook`~~ **exists** (`tools/manager.py:2721`, sync `fn(tool_name, result, metadata)`) but fires only after success and carries raw results — not used here; lifecycle events are the seam.
- ~~`_DaemonBotProxy` tool events / `chat.tool_event`~~ — the daemon stream has `delta|complete|error` only (`agentd/client.py:98`).
- ~~`import textual`~~ — **not installed** in the venv today (resolver dry-run confirms `textual==8.2.8` would install cleanly); M0 adds the dependency. Never import it at module level of `parrot.cli` or `agent_repl.py`.
- ~~`ConversationMemory.list_sessions()` / a "recent sessions" API~~ — not verified to exist; `--session last` uses the CLI-owned pointer file, not memory enumeration.
- ~~`sdd/tasks/index/new-cli-infra.json`~~ — FEAT-519 was never decomposed; nothing of it is implemented.
- ~~`RunView` as a reusable agent-console class~~ — coupled to dev-loop `SessionHost` semantics; extract the *pattern* into `LiveRegion`, do not instantiate it for `parrot agent`.

### Configuration References
- `PARROT_HOME` (env, existing convention) — base of `cli_state_dir()`.
- `PARROT_SERVER_TOKEN` (env, new) — default for `--token`.
- `TERM` (env) — `dumb` forces inline.
- No new keys in `parrot/conf.py`.

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks.

### Patterns to Follow
- **Homologate, don't invent.** `LiveRegion` is an extraction of
  `devloop/renderer.py:82-107`; keep `refresh_per_second=8, transient=False`.
- **One writer at a time.** Inline: every `prompt_async()` and every foreign
  prompt (questionary, HITL, device code) runs inside `region.modal()`. TUI:
  Textual owns the screen; foreign prompts run inside `App.suspend()`.
- **One execution boundary.** Only `parrot/cli/session.py` calls `bot.ask` /
  `bot.ask_stream` (AC5). Presenters consume `TurnEvent`s.
- **Never touch `clients/base.py`, `bots/abstract.py`, `bots/base.py`.** Live tool
  events come from the existing lifecycle emits plus the `turn_scope` ContextVar.
- **Backend duck type unchanged.** Loaders return objects with `ask`,
  `ask_stream`, `get_available_tools`, `get_tools_count`, `has_tools`, `name`;
  the new optional `capabilities` attribute is read with `getattr`.
- **Lazy TUI import** in `agent_repl.py` only when the resolved mode is TUI.
- Async-first, `self.logger`, Google docstrings, strict typing, Pydantic v2 for
  the new models; `black` 120 cols; `ruff` TID251 bans hold.

### Known Risks / Gotchas
- **Ordering when deleting `_BlockingSafeFile`.** Delete it in the same change
  that makes the renderer stream inside the region (M6), never before — while
  `patch_stdout()` makes the fd non-blocking a large `Console.print()` outside a
  region can raise `BlockingIOError` again.
- **`patch_stdout()` stays** around the inline loop (`repl.py:154`,
  `devloop/console.py:816`); `LiveRegion` must cooperate with it as devloop does.
- **Markdown repaint cost.** Repainting the whole buffer per chunk is O(n²);
  update the region's renderable and let the 8/s tick repaint. In the TUI use
  `MarkdownStream` (Textual batches internally).
- **Partial Markdown.** An unclosed fence mid-stream must not raise; fall back
  to `Text` for the tail if `Markdown` fails.
- **Tool-event correlation depends on task context.** Tools that execute in a
  thread or a fresh loop (`asyncio.to_thread` copies context; `run_in_executor`
  does too; a new event loop does not) will not carry `TURN_SCOPE`; such events
  are simply not shown live — final `tool_calls` still render. Document, do not
  "fix" by dropping the filter.
- **Server-side scoping.** In `stream_sse`, subscribe *before* calling
  `ask_stream` and unsubscribe in `finally`; callbacks must only enqueue.
- **`user_id` semantics in server mode.** AgentTalk honours an explicit body
  `user_id` over the authenticated identity (`agent.py:879-902`). The CLI
  therefore omits `user_id` unless `--user` is passed (§8 Q8).
- **`/quit` raises `SystemExit`.** Kept for the `agentd` handlers and existing
  tests; inline propagates, TUI maps it to `App.exit(0)`.
- **`agent` function name** must stay `agent` for `LazyGroup`
  (`cli/__init__.py:119`).
- **Textual key availability.** `shift+enter` is not reported by every
  terminal; `ctrl+j` is the guaranteed newline key and is shown in the footer.
- **History file is single-writer per agent**; two concurrent sessions on the
  same agent interleave lines (prompt_toolkit's format tolerates it). No lock.
- **devloop is the one working console.** M14 is a refactor of code that is not
  broken; any behaviour change is a defect (`tests/cli/devloop/` must stay green).
- **Cross-package ordering.** M10 (server) and M15 (agentd) depend on core
  modules; land core first. The proxy parser tolerates a server without
  `tool_event` frames, so there is no broken intermediate state.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `textual` | `>=8.2,<9` (**new**, core) | TUI framework; requires `rich>=14.2`, Python `>=3.9`; resolver-verified 2026-09-18 (`textual==8.2.8`) |
| `rich` | `>=13.0` (existing, installed 15.0.0) | `Live`, `Markdown`, panels, tables |
| `prompt_toolkit` | `>=3.0` (existing, 3.0.47) | inline input, `FileHistory`, `patch_stdout` |
| `questionary` | `>=2.1.1` (existing) | picker (unchanged) |
| `aiohttp` | existing | server proxy; SSE parsed by hand (no `aiohttp-sse-client` usage added) |
| `navigator-eventbus` | existing (0.3.0) | `EventRegistry`, `TraceContext` |

---

## Worktree Strategy

- **Isolation**: one feature worktree for FEAT-573
  (`feat-FEAT-573-new-ui-cli-agents`); the `sdd-coder` engine gives each task
  its own sub-worktree inside it.
- **Module dependency graph** (edge = imports/edits the target's output):
  - M0 → (none); everything importing `textual` (M11, M12, M13) needs M0 merged.
  - M1 → M6, M8, M14, M15 (they import `parrot.cli.console`).
  - M2 → M5 (`save_session_pointer`), M8 (`history_path`), M13 (`resolve_ui_mode`).
  - M3 → M5, M10 (`turn_scope`, `in_turn_scope`).
  - M4 → M5, M6, M7, M9, M11 (`TurnEvent` family, `BackendCapabilities`).
  - M5 → M7 (`ctx.runner`), M8, M11, M13.
  - M6 → M8 (renderer API), M13.
  - M7 → M8, M12, M15 (`CommandContext`).
  - M9 → M13 (`ServerAgentProxy(token=)`); M10 → M9 only by frame grammar (parser tolerates absence), not by import.
  - M11 → M12 → M13 (TUI wired last).
  - M16 → all; M17 → M13.
  - Independent pairs expected to run concurrently: {M1, M2, M3, M4} · {M6, M14} after M1 · {M9, M10} · {M11, M15}.
- **Shared files** (their tasks serialise): `repl.py` (M8 only), `renderer.py`
  (M6 only), `commands.py` (M7 only), `agent_repl.py` (M13 only), `loaders.py`
  (M9 only), `core/events/lifecycle/__init__.py` (M3 only), `tests/cli/conftest.py`
  (M16 only), `agentd/cli.py` + `agentd/proxy.py` (M15 only).
- **Exclusive resources** (`parallel: false`): M0 (edits `pyproject.toml` and
  runs `uv lock`; also edits `sdd/specs/new-cli-infra.spec.md`).
- **Cross-feature dependencies**: none must merge first. FEAT-519 is
  superseded by M0, not merged.

---

## 8. Open Questions

> Resolved items carry the brainstorm answer verbatim; unresolved items are
> owned and do not block task decomposition unless marked.

- [x] Confirm feature/dev defaults and intended audience — *Resolved in brainstorm*: `type: feature`, `base_branch: dev` confirmed. Audience is developers and operators interacting with registered Parrot agents. → frontmatter, §1.
- [x] Is the target a persistent full-screen workspace or improved inline chat? — *Resolved in brainstorm*: Full-screen Textual workspace (Option B) with the inline Rich chat retained as the fallback mode for non-TTY and `--ui inline`. → §2 Overview, G1/G2, M11.
- [x] Approve Textual as the UI dependency, prefer existing dependencies, or choose external Toad/ACP? — *Resolved in brainstorm*: Textual approved as a new core dependency. Toad/ACP (Option C) and prompt_toolkit full-screen (Option D) rejected. → M0, §7 External Dependencies, §1 Non-Goals.
- [x] Does this supersede FEAT-519's Textual rejection, or layer on top of its shared inline infrastructure? — *Resolved in brainstorm*: This feature absorbs and supersedes FEAT-519. Its inline fixes (shared console, LiveRegion, Markdown streaming, post-turn hook) become this feature's inline mode; the TUI is added on top. FEAT-519 is marked superseded. One worktree, one owner of the CLI files. → M0, M1, M6, M8, M14, M15, AC11–AC15, AC24.
- [x] Confirm v1 scope — *Resolved in brainstorm*: v1 includes (1) the core workspace — one agent, one session, multiline composer, transcript navigation with auto-follow, slash commands with completion, cancellation, tool-call details, usage footer, `--ui auto|inline|tui`; (2) persistent input history across launches; (3) conversation resume of a prior `session_id` from bot-owned memory; (4) live tool progress from the backend (new event contract in the streaming path and the server). Embedded shell, file attachments, session switching and concurrent sessions remain out of scope. → G1, G4, G5, G6, M5, M9–M11.
- [x] Choose mode defaults, non-TTY behavior, keybindings and supported terminal/platform baseline — *Resolved in brainstorm*: `--ui auto` is the default — TUI when stdin and stdout are TTYs and `TERM` is not `dumb`, inline Rich otherwise. Non-TTY never emits full-screen escapes, never opens the interactive picker (agent name required), and reads queries line by line from stdin. Keybindings and platform baseline are spec decisions. → M2, M13, AC1/AC2; keybindings fixed in M11 (Linux/macOS terminals with xterm-compatible `TERM`; Windows Terminal supported by Textual but not part of the acceptance run).
- [x] Identify supported tool-event and cancellation contracts for standalone/server backends; decide whether backend expansion is deferred — *Resolved in brainstorm*: Backend expansion is NOT deferred — live tool progress is in v1 scope, so the spec must define the tool-event contract for the standalone streaming path and the server. Cancellation remains local (task cancellation + stream close); no remote rollback is claimed. → M3, M4, M5, M10, AC6/AC7/AC17/AC18.
- [x] **FEAT-519 G7 (generalised wizard, Module 5)** — *Decided by spec author*: not required by the workspace; deferred to a follow-up spec rather than absorbed (§1 Non-Goals). Flagged for the user in the `/sdd-spec` report.
- [ ] **Q8 — Server-mode identity and PBAC** (codex S3, escalated). The CLI now sends a bearer token and omits `user_id` unless `--user` is given, but the device-code flow (`build_cli_permission_context`) is standalone-only and AgentTalk still lets an explicit body `user_id` override the authenticated identity. Should `--user` be refused in `--server` mode, and should the server ignore body `user_id` for authenticated requests? — *Owner: Jesus Lara*. Does not block decomposition; M9 implements the token + omission behaviour as specified.
- [ ] **Q9 — Server-side conversation history for resume** (codex S4, escalated). No endpoint exists; v1 resume is standalone-only (`capabilities.resume=False` in server and daemon modes). Add `GET /api/v1/agents/chat/{agent_id}/history?session_id=` in a follow-up? — *Owner: Jesus Lara*. Does not block.
- [ ] **Q10 — Daemon live tool events.** Add a `chat.tool_event` notification to the agentd protocol so `parrot attach` shows live tool rows? — *Owner: agentd maintainer*. Out of v1; does not block.
- [ ] **Q11 — `list_agents` payload shape of `GET /api/v1/bots`** (`bots.py:_get_all`, not read in detail). M9 accepts a list or `{"agents": [...]}`; the implementing task must read `_get_all` and pin the shape in its blueprint. — *Owner: implementer of M9*. Does not block.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: completed
> · Transcript: `sdd/state/FEAT-573/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Define a presentation-neutral turn event protocol first (architecture) | CONFIRM | Exactly the brainstorm's "presentation-neutral event model"; typed `TurnEvent` family + one `TurnRunner` consumed by both presenters | §2 Data Models, M4, M5, AC5 |
| S2 | Reconcile `ServerAgentProxy` with the canonical server API (api) | CONFIRM | Verified: `/api/agent/*` routes do not exist; canonical routes are `/api/v1/agents/chat/{agent_id}` (AgentTalk) and `/bots/{bot_id}/stream/sse`. Chose SSE over AgentTalk's `\n\x00` chunked transport for streaming because typed frames are needed for tool events | M9, M10, AC16, §6 Does NOT Exist |
| S3 | Specify the authenticated identity boundary for server mode (risk) | CONFIRM + ESCALATE | Bearer token (`--token`/`PARROT_SERVER_TOKEN`) added and `user_id` omitted by default (verified precedence at `agent.py:879-902`). Whether to refuse `--user` in server mode and harden the server is the user's call | M9, M13, AC16, §8 Q8 |
| S4 | Add a session repository and an explicit resume contract (architecture) | CONFIRM (partial) + ESCALATE | Explicit store: `cli_state_dir()` with `0o600` history file and per-agent `SessionPointer`; resume via `bot.get_conversation_history`; display history vs bot memory distinguished. No locking (single-writer, documented). Server-side history endpoint escalated | M2, M5, M7 (`/resume`), AC9/AC10, §8 Q9 |
| S5 | Decouple slash commands from `AgentREPL` and its renderer (api) | CONFIRM (partial) | `CommandContext`/`RendererProtocol` protocols, `ctx.runner` for session mutation, `suspend()` for `CLIHumanChannel`. **Rejected part**: changing `/quit` away from `SystemExit` — kept for agentd handlers and existing tests; hosts catch it | M7, M12, AC20 |
| S6 | Make cancellation an explicit turn lifecycle (risk) | CONFIRM | `TurnRunner` owns the active task; `CancelledError` → `aclose()` → `TurnCancelled(partial)`; cancelled turns never recorded; no remote rollback claimed | M5, M8, M11, AC18 |
| S7 | Define live tool-event semantics instead of inferring them from text (api) | CONFIRM | `call_id = span_id`, `seq` ordering, started/finished/failed states, `args_summary` only (already truncated by the emitter), `result_size_bytes` not results, `BackendCapabilities.live_tool_events` fallback | §2 Data Models, M4, M5, M10, AC6–AC8 |
| S8 | Make display ownership and output injection explicit (architecture) | CONFIRM | Single `get_console()`, `LiveRegion` discipline, injected console/region in the renderer, log drawer handler in the TUI, `App.suspend()` for foreign prompts, AC that only one owner emits control sequences | M1, M6, M12, AC11/AC12/AC14 |
| S9 | Implement mode selection before choosing the input mechanism (architecture) | CONFIRM | `resolve_ui_mode()` on stdin/stdout TTY + `TERM`; name required on non-TTY; `run_batch` line mode with no alternate screen | M2, M8, M13, AC1/AC2 |
| S10 | Build a backend-by-mode test matrix, not only mock no-raise tests (testing) | CONFIRM (partial) | Deterministic event-stream tests per backend, Textual `run_test()` interaction tests, resize via `run_test(size=)`, pipe checks via `CliRunner`. **Rejected part**: PTY-level SIGINT/resize harness — no PTY test dependency (`pexpect`) is in the workspace; covered by unit-level cancellation and Textual headless resize instead | §4, M16 |
| S11 | Pin and lazily load a resolver-verified Textual version (architecture) | CONFIRM | `textual>=8.2,<9`, `uv lock` verified across 3.11/3.12/3.13 in M0, lazy import in `agent_repl.py` with an AC | M0, M13, AC22/AC23 |

Summary: **11** confirmed (3 partial) · **0** rejected outright · **2** escalated (S3, S4 → §8 Q8, Q9).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-18 | Jesus Lara | Initial draft from accepted brainstorm; absorbs FEAT-519 Modules 1–4, 6–8; design research (codex, 11 suggestions) folded in |

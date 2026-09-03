---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# Intentional bypass of scripts/sdd/reserve_ids.py (FEAT-387).
# FEAT-519 was allocated by /sdd-proposal's max-scan and is already committed
# in sdd/proposals/new-cli-infra.proposal.md and sdd/state/FEAT-519/.
# existing_feature_id() reads only sdd/specs/ and sdd/tasks/index/ — it is
# blind to proposals — and reserve_ids() allocates straight from
# ledger.next_feature_id (then 501), so reserving here would have returned
# FEAT-501 and forked this feature's identity: exactly the FEAT-488→489
# failure the command warns about. The ledger was instead repaired
# (next_feature_id 501 → 520) in a separate commit.
reuse_feature_id: FEAT-519
---

# Feature Specification: Shared Rich Console Layer for the Parrot CLI

**Feature ID**: FEAT-519
**Date**: 2026-09-02
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.next

> **Source**: `sdd/proposals/new-cli-infra.proposal.md` (research-grounded
> proposal, overall confidence **high**, 11 findings, audit at
> `sdd/state/FEAT-519/`). All six of its questions (U1-U4, D1-D2) are resolved;
> §8 below carries every resolution forward.

---

## 1. Motivation & Business Requirements

### Problem Statement

The interactive console `parrot agent <agent_id>` looks and feels poor. The
originally reported cause — "using direct print to stdout" — is **half true, and
the false half matters**: `parrot agent` already renders through Rich end to end
(banner, errors, `--list` table, Markdown output, tool-call panels, token usage),
and `packages/ai-parrot/src/parrot/cli` contains **zero** `print()` calls.

The actual defect is one function. `ResponseRenderer.render_stream_chunk`
(`renderer.py:248-260`) writes raw `sys.stdout.write(text)`, and
`REPLConfig.streaming` defaults to `True` (`repl.py:82-85`) — so the raw path is
what every user sees by default, while the good Markdown renderer is reachable
only via `--no-stream`. Streamed responses therefore lose Markdown, syntax
highlighting and soft-wrapping, which is precisely the "cheap" impression.

The in-code justification is a real conflict: `rich.live.Live` emits
cursor-control ANSI that `prompt_toolkit.patch_stdout()`'s `StdoutProxy` mangles
into literal `?[2K` (`renderer.py:233-246`). But the sibling command
`parrot devloop` **already solved that exact conflict in the same package** with a
modal pause/resume discipline — "one writer at a time"
(`devloop/console.py:1-5`, `devloop/renderer.py:82-107`). This is therefore a
homologation feature, not a greenfield TUI adoption.

Worse, the surface is accreting point workarounds instead of a fix. Three now
stack on the same unaddressed seam, two of which landed on 2026-09-02 while the
proposal research was running, and neither touched the raw write:

| # | Workaround | Location | Compensates for |
|---|---|---|---|
| 1 | `Console(file=sys.__stdout__, force_terminal=True)` | `agent_repl.py:25`, `repl.py:128`, `renderer.py:80` | `patch_stdout()` mangling ANSI |
| 2 | `_BlockingSafeFile` write-retry | `renderer.py:22-56` | `BlockingIOError` — `patch_stdout()` makes the fd non-blocking |
| 3 | `_mute_stream_loggers()` | `repl.py:27-58`, called at `247`/`279` | log records interleaving with streamed tokens |

### Goals

- **G1** — Streamed responses render with the same fidelity as batch responses
  (Markdown, code highlighting, wrapping), so `--no-stream` is no longer the
  only way to get good output.
- **G2** — Adopt devloop's modal "one writer at a time" `Live` discipline in the
  agent console, keeping `prompt_toolkit` as the input layer.
- **G3** — Extract a single shared console/presentation layer used by
  `parrot agent`, `parrot devloop` and `parrot attach`, replacing the three
  unshared `Console` instances with one configuration point.
- **G4** — Give `AgentREPL` a real post-turn hook so `agentd` can retire its
  instance-level `send`/`send_stream` monkeypatch.
- **G5** — Retire all three stacked workarounds; the seam makes them unnecessary.
- **G6** — Log records must not interleave with streamed tokens *by construction*
  (rendering inside a managed region), not by muting handlers.
- **G7** — Generalize `cli/wizard.py` into the shared engine its own spec already
  declared it to be (devloop spec goal G2) and have the agent console consume it.
- **G8** — Add no new runtime dependency. `rich`, `prompt_toolkit` and
  `questionary` are already core.

### Non-Goals (explicitly out of scope)

- **Textual.** A full-screen TUI was evaluated and rejected (proposal U1). It
  would dissolve the `Live`/`patch_stdout` conflict by owning the screen, but it
  is a new dependency (absent from every `pyproject.toml`, not importable in the
  venv), a rewrite of the input layer, incompatible with piping/non-TTY use, and
  would fork the agent console away from devloop's Rich conventions rather than
  homologating with them.
- **InquirerPy.** Rejected (proposal U2): `questionary>=2.1.1` is already a core
  dependency and already powers `parrot agent`'s own picker
  (`loaders.py:103-120`), `InteractiveDecisionNode` and the wiki CLI. Both wrap
  `prompt_toolkit`; adopting InquirerPy would add a redundant library to core.
- **Migrating the `parrot/human/` HITL surface.** `human/channels/cli.py` and
  `human/cli_companion.py` are an existing Rich-based HITL surface not named in
  the request. Deferred to a follow-up (proposal D2) — but see **C13** in §5:
  the shared layer must be designed so they can adopt it later *without a second
  redesign*.
- **`cli/tool_worker.py`.** Its `sys.stdout.write` calls (lines 39-41) are an IPC
  result-marker protocol, not display output. Do not touch.
- **`parrot/clients/*`.** Changes there from commit `7c2790044` and later are
  unrelated to this feature.

---

## 2. Architectural Design

### Overview

Introduce **`parrot/cli/console.py`** — a new module (verified absent, see §6)
holding the shared presentation layer:

1. **One console.** `get_console()` returns a process-wide singleton `Console`,
   replacing the three independent instances. Because rendering now happens
   inside a managed `Live` region rather than racing `patch_stdout()`, the
   console is constructed normally — the `file=sys.__stdout__` bypass and the
   `_BlockingSafeFile` retry wrapper both go away (G5).
2. **One discipline.** `LiveRegion` generalizes the pause/resume behaviour
   currently embedded in `devloop`'s `RunView` (`devloop/renderer.py:82-96`):
   `start/stop/pause/resume/update`, plus a `modal()` context manager that
   brackets any `prompt_async()` call. This is the extraction of an already-proven
   pattern, not a new invention.

`ResponseRenderer` then streams *into* a `LiveRegion`: `render_stream_chunk`
appends to `_stream_buffer` and repaints the buffer as `rich.markdown.Markdown`
in the live region, instead of writing raw bytes. Because a `Live` region owns
its screen area, log records emitted during a stream land above it rather than
inside it — satisfying G6 by construction and making `_mute_stream_loggers`
unnecessary.

`AgentREPL` gains two seams: the renderer is already injected (constructor
param), and a new post-turn hook list lets consumers observe turn completion
without shadowing methods (G4).

**Non-TTY safety**: `LiveRegion` must degrade to plain sequential printing when
`console.is_terminal` is false, so piping `parrot agent` keeps working — this is
the property that made the inline approach preferable to Textual.

### Component Diagram

```
                       parrot/cli/console.py   (NEW — shared layer)
                       ┌──────────────────────────────────────┐
                       │  get_console() -> Console  (singleton)│
                       │  LiveRegion                           │
                       │    start/stop/pause/resume/update      │
                       │    modal()  ← contextmanager           │
                       └──────────────────────────────────────┘
                            ▲             ▲              ▲
              ┌─────────────┘             │              └─────────────┐
              │                           │                            │
   ResponseRenderer              devloop/RunView            devloop/DevLoopConsole
   (renderer.py)                 (devloop/renderer.py)      (devloop/console.py)
   streams Markdown              drops its own              keeps gate prompts,
   into LiveRegion               pause/resume/_live         now via region.modal()
              ▲
              │ injected
        AgentREPL  (repl.py)
          run()  ── prompt_async() inside region.modal()
          send() / send_stream()
          add_post_turn_hook(cb) ──────────► agentd `parrot attach`
                                              (drops _wrap_with_event_drain)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ResponseRenderer` (`renderer.py:59`) | modifies | streams into a `LiveRegion`; `_BlockingSafeFile` deleted |
| `AgentREPL` (`repl.py:92`) | modifies | brackets `prompt_async()` in `region.modal()`; gains post-turn hooks; `_mute_stream_loggers` deleted |
| `agent_repl.py` (`:25`) | modifies | module-level `Console` → `get_console()` |
| `RunView` (`devloop/renderer.py:26`) | modifies | delegates `pause`/`resume`/`_live` to `LiveRegion`; envelope handlers unchanged |
| `DevLoopConsole` (`devloop/console.py:48`) | modifies | gate prompts use `region.modal()` instead of manual `pause()`/`resume()` pairs |
| `agentd` `attach` (`agentd/cli.py:158-181`) | modifies | uses `add_post_turn_hook`; `_wrap_with_event_drain` deleted |
| `cli/wizard.py` | modifies | generalized per G7/D1; agent console consumes it |
| `SlashCommandDispatcher` (`commands.py:70`) | unchanged | dispatch contract untouched |
| `questionary` pickers (`loaders.py:103-120`, `:413`) | unchanged | U2 — kept as-is |

### Data Models

```python
# parrot/cli/console.py  (NEW)
from collections.abc import Awaitable, Callable
from parrot.cli.commands import ConversationTurn

#: Called after a turn completes, before the next prompt is shown.
PostTurnHook = Callable[["AgentREPL", ConversationTurn], Awaitable[None]]
```

No new Pydantic models are required; `REPLConfig` (`repl.py:61`) is unchanged.

### New Public Interfaces

```python
# parrot/cli/console.py  (NEW MODULE — verified absent, see §6)

def get_console() -> Console:
    """Return the process-wide shared Rich Console."""

class LiveRegion:
    """A managed Rich Live area with modal pause/resume discipline.

    Generalizes the behaviour proven in devloop's RunView
    (devloop/renderer.py:82-107): exactly one writer owns the terminal at a
    time. Degrades to plain sequential printing when the console is not a
    terminal, so piped output keeps working.
    """

    def __init__(
        self,
        console: Optional[Console] = None,
        *,
        refresh_per_second: int = 8,
        transient: bool = False,
    ) -> None: ...

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def update(self, renderable: Any) -> None: ...

    @contextlib.contextmanager
    def modal(self) -> Iterator[None]:
        """Pause the region for the duration of a prompt, then resume."""


# parrot/cli/repl.py  (ADDED to the existing AgentREPL)
class AgentREPL:
    def add_post_turn_hook(self, hook: PostTurnHook) -> None:
        """Register a coroutine called after each completed turn."""
```

---

## 3. Module Breakdown

### Module 1: Shared console layer
- **Path**: `packages/ai-parrot/src/parrot/cli/console.py` *(new file)*
- **Responsibility**: `get_console()` singleton + `LiveRegion` with
  `start/stop/pause/resume/update/modal()`; non-TTY degradation.
- **Depends on**: nothing in this spec (foundation module).

### Module 2: Streaming renderer on the shared layer
- **Path**: `packages/ai-parrot/src/parrot/cli/renderer.py`
- **Responsibility**: `render_stream_start/chunk/end` repaint `_stream_buffer` as
  `Markdown` inside a `LiveRegion` instead of `sys.stdout.write`. Delete
  `_BlockingSafeFile`; construct the console via `get_console()`. Batch
  `render()` path and all panel/table/usage helpers keep their current output.
- **Depends on**: Module 1.

### Module 3: `AgentREPL` seams
- **Path**: `packages/ai-parrot/src/parrot/cli/repl.py`
- **Responsibility**: bracket `prompt_async()` in `region.modal()`; add
  `add_post_turn_hook()` and invoke hooks at the end of `send()` and
  `send_stream()`; delete `_mute_stream_loggers`/`_restore_stream_loggers` and
  their call sites (`:247`, `:279`); console via `get_console()`.
- **Depends on**: Modules 1, 2.

### Module 4: `agent_repl.py` wiring
- **Path**: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
- **Responsibility**: replace the module-level `Console` (`:25`) with
  `get_console()`. Preserve the FEAT-266 permission-context bootstrap and the
  bot-cleanup `finally` block added by `7c2790044` (`:154-163`).
- **Depends on**: Modules 1, 3.

### Module 5: Generalized wizard  *(D1)*
- **Path**: `packages/ai-parrot/src/parrot/cli/wizard.py`
- **Responsibility**: widen the engine from its devloop-shaped usage into the
  genuinely shared engine the devloop spec already declared (goal G2), and have
  the agent console consume it. Console access via `get_console()`.
- **Depends on**: Module 1.

### Module 6: devloop convergence
- **Path**: `packages/ai-parrot/src/parrot/cli/devloop/renderer.py`,
  `packages/ai-parrot/src/parrot/cli/devloop/console.py`
- **Responsibility**: `RunView` delegates `pause`/`resume`/`_live` to
  `LiveRegion`; `DevLoopConsole` gate prompts use `region.modal()` in place of
  manual `pause()`/`resume()` pairs (`console.py:907/940/969/1102/1114/1133/1146`).
  Envelope handlers (`_handle_*`) and `SessionHost` polling are untouched.
- **Depends on**: Module 1.
- **Constraint**: this is the one currently-working console — **no behaviour
  regression**; its existing suite must stay green.

### Module 7: agentd migration
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/cli.py`
- **Responsibility**: replace `_wrap_with_event_drain` (`:205-230`) with
  `repl.add_post_turn_hook(...)`; delete the monkeypatch; module-level `Console`
  (`:30`) via `get_console()`.
- **Depends on**: Module 3.
- **Cross-package**: ships in `ai-parrot-integrations`; land after Module 3.

### Module 8: Tests
- **Path**: `packages/ai-parrot/tests/cli/`
- **Responsibility**: keep `test_integration.py` green; add coverage per §4.
- **Depends on**: Modules 1-7.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_get_console_is_singleton` | 1 | repeated `get_console()` returns the same object |
| `test_live_region_modal_pauses_and_resumes` | 1 | `modal()` pauses on enter, resumes on exit, resumes on exception |
| `test_live_region_non_tty_degrades` | 1 | with `is_terminal=False`, `update()` prints sequentially and starts no `Live` |
| `test_stream_chunk_renders_markdown` | 2 | streamed `**bold**` reaches the region as `Markdown`, not raw text |
| `test_stream_end_preserves_tool_calls_and_usage` | 2 | existing `render_stream_end` metadata behaviour unchanged |
| `test_blocking_safe_file_removed` | 2 | `renderer.py` no longer defines `_BlockingSafeFile` |
| `test_post_turn_hook_invoked_after_send` | 3 | hook fires once per `send()`, after history append |
| `test_post_turn_hook_invoked_after_send_stream` | 3 | hook fires once per `send_stream()`, never mid-stream |
| `test_mute_stream_loggers_removed` | 3 | `repl.py` no longer defines `_mute_stream_loggers` |

### Integration Tests

| Test | Description |
|---|---|
| `test_streaming_output_is_rendered_markdown` | end-to-end `parrot agent` streaming turn yields rendered Markdown (G1) |
| `test_logs_do_not_interleave_with_stream` | log records emitted mid-stream land outside the region, tokens stay contiguous (G6) |
| `test_piped_output_still_works` | non-TTY invocation produces clean plain text, no ANSI cursor codes |
| `test_devloop_console_unregressed` | existing `tests/cli/devloop/` suite passes against `LiveRegion` |
| `test_agentd_events_drain_after_turn` | `parrot attach` job events appear after a turn via the hook, with no monkeypatch |

### Test Data / Fixtures

```python
# Existing, reuse: packages/ai-parrot/tests/cli/conftest.py
#   provides a quiet ResponseRenderer fixture (`renderer`) and `mock_agent`,
#   `repl_config` used by TestAgentREPLSend / TestAgentREPLStream.

@pytest.fixture
def non_tty_console() -> Console:
    """Console forced to non-terminal, for degradation tests."""
    return Console(force_terminal=False, force_interactive=False)
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC1 (G1)** — A streamed response in `parrot agent` renders Markdown,
      code highlighting and wrapping, matching `--no-stream` fidelity.
- [ ] **AC2 (G1)** — `ResponseRenderer.render_stream_chunk` contains no
      `sys.stdout.write`; `grep -n 'sys.stdout.write' cli/renderer.py` is empty.
- [ ] **AC3 (G2)** — Every `prompt_async()` call in `repl.py` and
      `devloop/console.py` is bracketed by `LiveRegion.modal()`.
- [ ] **AC4 (G3)** — Exactly one `Console` construction remains in the CLI
      (`get_console()`); `agent_repl.py:25`, `repl.py:128` and `renderer.py:80`
      no longer build their own.
- [ ] **AC5 (G4)** — `AgentREPL.add_post_turn_hook()` exists and is exercised by
      `agentd`; `_wrap_with_event_drain` is deleted from `agentd/cli.py`.
- [ ] **AC6 (G5)** — `_BlockingSafeFile` (`renderer.py`) and
      `_mute_stream_loggers`/`_restore_stream_loggers` (`repl.py`) are deleted,
      along with the `file=sys.__stdout__` bypass.
- [ ] **AC7 (G6)** — Log records emitted during a stream do not interleave with
      streamed tokens, with no logging-handler mutation anywhere in the path.
- [ ] **AC8 (G7/D1)** — `cli/wizard.py` is consumed by the agent console, not
      only by devloop.
- [ ] **AC9 (G8)** — No new runtime dependency. `pyproject.toml` gains neither
      `textual` nor `InquirerPy`; `grep -ri 'textual\|inquirerpy' packages/*/pyproject.toml`
      is empty.
- [ ] **AC10** — Piping works: `parrot agent <id> < input` produces clean plain
      text with no ANSI cursor-control sequences.
- [ ] **AC11** — No regression in `parrot devloop`: `pytest packages/ai-parrot/tests/cli/devloop/ -v` passes.
- [ ] **AC12** — `pytest packages/ai-parrot/tests/cli/ -v` passes, including the
      pre-existing FEAT-168 suite in `test_integration.py`.
- [ ] **AC13 (D2)** — The shared layer is importable and usable from
      `parrot/human/` without redesign — demonstrated by a design note or a thin
      smoke test, **not** by migrating that surface in this feature.
- [ ] **AC14** — No breaking change to the cross-package public API:
      `from parrot.cli.repl import AgentREPL, REPLConfig` and
      `from parrot.cli.renderer import ResponseRenderer` keep working with their
      current constructor signatures.
- [ ] **AC15** — `ruff check` and `mypy` clean on all changed files.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against commit `7c2790044` (2026-09-02). `packages/ai-parrot/src/parrot/cli/`
> was confirmed untouched by the uncommitted `clients/` work in the tree at spec
> time. Re-verify line numbers if `cli/` moves before implementation starts.

### Verified Imports

```python
# All confirmed present and importable:
from rich.console import Console            # renderer.py:13
from rich.markdown import Markdown          # renderer.py:14
from rich.panel import Panel                # renderer.py:15
from rich.table import Table                # renderer.py:16
from rich.text import Text                  # renderer.py:17
from rich.live import Live                  # devloop/renderer.py:15
from rich.console import Console, Group     # devloop/renderer.py:14

from prompt_toolkit import PromptSession               # repl.py:14
from prompt_toolkit.completion import WordCompleter    # repl.py:15
from prompt_toolkit.history import InMemoryHistory     # repl.py:16
from prompt_toolkit.patch_stdout import patch_stdout   # repl.py:17

from parrot.cli.repl import AgentREPL, REPLConfig      # agentd/cli.py:20
from parrot.cli.renderer import ResponseRenderer       # agentd/cli.py:19
from parrot.cli.commands import ConversationTurn, SlashCommand, SlashCommandDispatcher  # repl.py:22
from parrot.models.responses import AIMessage          # repl.py:25
from parrot.models.outputs import OutputMode           # repl.py:24
import questionary                                     # loaders.py:17
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/cli/renderer.py
class _BlockingSafeFile:                                            # line 22  (TO BE DELETED)
    _MAX_RETRIES: int = 200                                         # line 33
    def __init__(self, wrapped) -> None: ...                        # line 35
    def write(self, s: str) -> int: ...                             # line 38
    def flush(self) -> None: ...                                    # line 47
    def __getattr__(self, name: str) -> Any: ...                    # line 55

class ResponseRenderer:                                             # line 59
    console: Console                                                # line 80 (Console(file=_BlockingSafeFile(sys.__stdout__), force_terminal=True))
    _stream_buffer: str                                             # line 83
    def __init__(self) -> None: ...                                 # line 69
    def render(self, response: AIMessage) -> None: ...              # line 89
    def _render_tool_calls(self, tool_calls: List[Any]) -> None: ...# line 124
    def _render_usage(self, usage: Any) -> None: ...                # line 153
    def render_error(self, error: Exception) -> None: ...           # line 175
    def render_table(self, headers: List[str], rows: List[List[str]],
                     title: Optional[str] = None) -> None: ...      # line 195
    def render_info(self, lines: List[tuple[str, str]]) -> None: ...# line 215
    def render_stream_start(self) -> None: ...                      # line 233
    def render_stream_chunk(self, text: str) -> None: ...           # line 248  ← ROOT CAUSE (sys.stdout.write at 257)
    def render_stream_end(self, response: Optional[AIMessage] = None) -> None: ...  # line 262
    def print(self, *args: Any, **kwargs: Any) -> None: ...         # line 282

# packages/ai-parrot/src/parrot/cli/repl.py
_STREAM_LOG_FLOOR = logging.WARNING                                 # line 30  (TO BE DELETED)
def _mute_stream_loggers() -> dict[int, int]: ...                   # line 33  (TO BE DELETED)
def _restore_stream_loggers(saved: dict[int, int]) -> None: ...     # line 52  (TO BE DELETED)

class REPLConfig(BaseModel):                                        # line 61
    agent_name: str                                                 # line 82
    streaming: bool = True                                          # line 83
    server_url: Optional[str] = None                                # line 84
    session_id: str = Field(default_factory=lambda: str(uuid4()))   # line 85
    user_id: str = "cli-user"                                       # line 86
    permission_context: Optional[Any] = None                        # line 87

class AgentREPL:                                                    # line 92
    def __init__(self, bot: AbstractBot, config: REPLConfig,
                 renderer: ResponseRenderer) -> None: ...           # line 109
    async def run(self) -> None: ...                                # line 131  (patch_stdout at 154; prompt_async at 157)
    async def send(self, query: str) -> AIMessage: ...              # line 200
    async def send_stream(self, query: str) -> None: ...            # line 228  (mute at 247, restore at 279)
    def register_command(self, cmd: SlashCommand) -> None: ...      # line 296

class _StreamedResponse:                                            # line 305
    def __init__(self, query: str, output: str) -> None: ...        # line 317

# packages/ai-parrot/src/parrot/cli/devloop/renderer.py  — REFERENCE PATTERN
class RunView:                                                      # line 26
    def __init__(self, host: Any, console: Optional[Console] = None,
                 *, run_id: str = "") -> None: ...                  # line 29
    def pause(self) -> None:   # self._paused = True;  self._live.stop()   # line 82
    def resume(self) -> None:  # self._paused = False; self._live.start()  # line 88
    def stop(self) -> None:    # self._stop = True                          # line 94
    async def run_live(self, stop_event: Optional[asyncio.Event] = None) -> None: ...  # line 98
        # with Live(self._build_display(), console=self.console,
        #           refresh_per_second=8, transient=False) as live:        # lines 103-107

# packages/ai-parrot/src/parrot/cli/commands.py
class SlashCommand: ...                                             # line 23
class ConversationTurn:                                             # line 38
    def to_dict(self) -> Dict[str, Any]: ...                        # line 51
class SlashCommandDispatcher:                                       # line 70
    def register(self, cmd: SlashCommand) -> None: ...              # line 86
    async def dispatch_async(self, input_text: str, repl: "AgentREPL") -> bool: ...  # line 95
    def get_completions(self) -> List[str]: ...                     # line 130

# packages/ai-parrot-integrations/src/parrot/integrations/agentd/cli.py
console = Console()                                                 # line 30
def _wrap_with_event_drain(repl: AgentREPL, proxy: DaemonAgentProxy) -> None: ...  # line 205  (TO BE DELETED)
    # repl.send = _send_with_drain; repl.send_stream = _send_stream_with_drain
def _print_drained_events(proxy: DaemonAgentProxy) -> None: ...     # line 232
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `LiveRegion` | `rich.live.Live` | wraps, `refresh_per_second=8, transient=False` | `devloop/renderer.py:103-107` |
| `LiveRegion.pause/resume` | `Live.stop()` / `Live.start()` | direct call — same as proven pattern | `devloop/renderer.py:82-92` |
| `ResponseRenderer.render_stream_chunk` | `LiveRegion.update()` | replaces `sys.stdout.write` | `renderer.py:257` |
| `AgentREPL.run` | `LiveRegion.modal()` | brackets `session.prompt_async(prompt)` | `repl.py:157` |
| `AgentREPL.add_post_turn_hook` | `agentd` `_print_drained_events` | hook registration | `agentd/cli.py:232` |
| `RunView` | `LiveRegion` | delegation; `_live`/`_paused` removed | `devloop/renderer.py:40-41` |
| `DevLoopConsole` gates | `LiveRegion.modal()` | replaces pause/resume pairs | `devloop/console.py:907, 940, 969` |

### Does NOT Exist (Anti-Hallucination)

Every item below was explicitly searched for and confirmed absent:

- ~~`parrot.cli.console`~~ — **the module this spec creates.** No such file today.
- ~~`parrot.cli.theme`~~, ~~`parrot.cli.live`~~, ~~`parrot.console`~~ — no such modules.
- ~~`class ConsoleLayer`~~, ~~`ParrotConsole`~~, ~~`SharedConsole`~~,
  ~~`ConsoleSession`~~, ~~`StreamRenderer`~~, ~~`MarkdownStream`~~ — no such
  classes anywhere in `packages/`.
- ~~`ResponseRenderer.render_markdown()`~~, ~~`.render_live()`~~,
  ~~`.set_console()`~~ — not real methods. Markdown rendering today goes through
  `self.console.print(Markdown(output))` inside `render()` (`renderer.py:104`).
- ~~`AgentREPL.on_turn_end`~~, ~~`.add_hook()`~~, ~~`.register_listener()`~~ —
  **no hook or callback mechanism exists in `repl.py` at all.** That absence is
  why `agentd` monkeypatches; this spec adds `add_post_turn_hook()`.
- ~~`import textual`~~ — **not installed** (`ModuleNotFoundError` in the venv) and
  absent from every `pyproject.toml`. Do not import it.
- ~~`import InquirerPy`~~ — not a dependency. Use `questionary` (already core).
- ~~`RunView` as a reusable agent-console class~~ — it exists, but is coupled to
  dev-loop `SessionHost` semantics (`replay_since`, `_handle_dispatch_*`,
  gate handlers). Homologate the **pattern**; do not instantiate it for
  `parrot agent`.

### Configuration References

No new configuration keys. `REPLConfig` (`repl.py:61`) is unchanged, including
`streaming: bool = True` — the default stays `True`; this feature makes that
default good rather than changing it.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Homologate, don't invent.** `LiveRegion` is an extraction of
  `devloop/renderer.py:82-107`, which is proven in production use. Match its
  parameters (`refresh_per_second=8`, `transient=False`) unless a test shows a
  reason to differ.
- **Modal discipline**: exactly one writer owns the terminal at a time
  (`devloop/console.py:1-5`). Every prompt must be inside `region.modal()`.
- Async-first; `self.logger` over `print`; Google-style docstrings and strict
  type hints on every new function (CLAUDE.md).
- Keep `ResponseRenderer.__init__()` zero-argument — `agentd/cli.py:158` and
  `:309` construct it with no arguments, and `tests/cli/conftest.py` provides it
  as a fixture (AC14).

### Known Risks / Gotchas

- **`patch_stdout()` remains in play.** `repl.py:154` and `devloop/console.py:816`
  both wrap their loops in it. `LiveRegion` must cooperate with it the way
  devloop already does, not assume it is gone. If `_BlockingSafeFile` is deleted
  before the region owns rendering, large `Console.print()` calls can raise
  `BlockingIOError` again — **delete it in the same change that introduces the
  region, never before** (ordering: Module 1 → Module 2).
- **Deleting `_mute_stream_loggers` regresses G6 if the region does not actually
  contain the render.** AC7 must be verified by test, not by inspection.
- **devloop is the one working console.** Module 6 is a refactor of code that is
  not broken; treat any behaviour change as a defect (AC11).
- **Cross-package ordering.** Module 7 lives in `ai-parrot-integrations` and
  depends on Module 3 in `ai-parrot`. Land Module 3 first; the monkeypatch keeps
  working until it is removed, so there is no broken intermediate state.
- **Markdown repaint cost.** Re-rendering the whole `_stream_buffer` as
  `Markdown` on every chunk is O(n²) over a long response. Throttle repaints to
  the region's refresh tick (8/s) rather than rendering per chunk.
- **Partial Markdown.** Mid-stream text can contain an unclosed code fence or
  table. `rich.markdown.Markdown` must not raise on it — render defensively and
  fall back to plain `Text` for the incomplete tail if needed.
- **Non-TTY.** `Live` in a pipe emits control codes. The degradation path
  (AC10) is a hard requirement, and it is the reason Textual was rejected.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `rich` | `>=13.0` | **already core** (`pyproject.toml:97`) — `Live`, `Markdown`, `Panel`, `Table` |
| `prompt_toolkit` | `>=3.0` | **already core** (`pyproject.toml:102`) — input layer, `patch_stdout` |
| `questionary` | `>=2.1.1` | **already core** (`pyproject.toml:131`) — pickers/confirmations (U2) |

**No new dependency is added by this feature** (G8/AC9).

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one
  worktree.
- **Rationale**: Modules 2, 3, 4, 6 and 7 all edit or delete code that Module 1
  introduces, and Modules 2/3 must land together (see the `_BlockingSafeFile`
  ordering gotcha). Parallelising them would produce conflicting edits to
  `renderer.py` and `repl.py`.
- **Partial parallelism**: Module 5 (generalized wizard) touches only
  `cli/wizard.py` and depends on Module 1 alone — it may run in parallel with
  Modules 2-4 once Module 1 has landed.
- **Cross-feature dependencies**: none. No other spec must merge first.
- **Cross-package note**: Module 7 edits `ai-parrot-integrations`; the same
  worktree covers it since this is a uv workspace.

```bash
git checkout dev
git worktree add -b feat-519-new-cli-infra \
  .claude/worktrees/feat-519-new-cli-infra HEAD
```

---

## 8. Open Questions

> All six questions from the proposal are resolved. None block implementation.

- [x] **U1 — Inline Rich + pause/resume, or a full-screen Textual app?** —
  *Resolved in proposal*: Inline Rich + pause/resume. Keep `prompt_toolkit` and
  adopt devloop's modal "one writer at a time" `Live` discipline so streamed
  tokens render as Markdown in a `Live` region that pauses around every prompt.
  No new dependencies; converges with devloop; piping/non-TTY preserved; the
  three stacked workarounds become removable. **Textual explicitly NOT adopted.**
  → §2 Overview, §1 Non-Goals, AC1-AC3, AC9, AC10.

- [x] **U2 — InquirerPy, or the `questionary` already in core?** —
  *Resolved in proposal*: Keep `questionary` (already core `>=2.1.1`, already
  powers `parrot agent`'s own picker at `loaders.py:103-120`). **InquirerPy
  explicitly NOT adopted.** → §1 Non-Goals, §7 External Dependencies, AC9.

- [x] **U3 — How wide should the refactor go?** — *Resolved in proposal*:
  Extract a shared console/presentation layer used by `parrot agent`,
  `parrot devloop` and `parrot attach` — single `Console`, one `Live` discipline,
  pluggable renderer. Cross-package refactor accepted. → §2, Modules 1/6/7, AC4.

- [x] **U4 — Give `AgentREPL` a real post-turn hook?** — *Resolved in proposal*:
  Yes — add the hook and retire agentd's `send`/`send_stream` instance-level
  monkeypatch. → Module 3, Module 7, AC5.

- [x] **D1 — Does `cli/wizard.py` generalise, or is it devloop-shaped?** —
  *Resolved*: **Generalize it.** It becomes a genuinely shared engine the agent
  console reuses, making real the "generic, reusable engine" the devloop spec
  already declared as goal G2. → Module 5, G7, AC8.

- [x] **D2 — Migrate `parrot/human/channels/cli.py` + `cli_companion.py` now or
  later?** — *Resolved*: **Migrate later** — explicitly a follow-up feature, not
  FEAT-519. Design constraint it imposes: the shared console layer must be built
  so that surface can adopt it later without a second redesign. → §1 Non-Goals,
  AC13.

### Deferred to implementation (non-blocking)

- [ ] Exact repaint throttling strategy for the Markdown region (tick-aligned vs
  debounced) — decide with a benchmark during Module 2. *Owner: implementer*
- [ ] Whether `LiveRegion` should expose a `record=True` mode for test capture,
  or tests should assert on the injected console. *Owner: implementer*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-02 | Jesus Lara | Initial draft from `new-cli-infra.proposal.md` (FEAT-519, confidence high, 11 findings) |

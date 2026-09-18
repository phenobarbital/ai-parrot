# TASK-3407: `AgentREPL` on `TurnRunner` — modal prompt, cancellation, file history, batch mode

**Feature**: FEAT-573 — Agent Terminal Workspace for `parrot agent`
**Spec**: `sdd/specs/new-ui-cli-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3400, TASK-3401, TASK-3404, TASK-3405, TASK-3406
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (absorbs FEAT-519 Module 3). `AgentREPL` (`repl.py:92`) is the
inline presenter. Today it calls the bot itself (`:212-218`, `:249-255`), mutes
logging handlers around streams (`:33-58`, `:247`, `:279`), builds a bypass
console (`:128`), uses `InMemoryHistory` (`:148`) and catches a
`KeyboardInterrupt` that, on Python ≥3.11 under `asyncio.run`, never reaches
`:190` (the runner cancels the main task instead).

After this task the REPL: consumes `TurnRunner` events (TASK-3404) and renders
them through `ResponseRenderer.render_turn_event` (TASK-3405); brackets every
prompt in `LiveRegion.modal()` (TASK-3400); persists composer history via
`FileHistory` at `history_path()` (TASK-3401); implements `CommandContext`
(TASK-3406); cancels the active turn on Ctrl+C (spec AC18); runs a plain
line-oriented batch mode on non-TTY (spec AC2); exposes `add_post_turn_hook`
for agentd (spec AC15).

---

## Scope

- `REPLConfig` gains `ui_mode: UIMode = UIMode.AUTO`, `resume_session_id`,
  `server_token`, `history_enabled: bool = True`; `user_id` becomes
  `Optional[str] = "cli-user"`.
- Delete `_STREAM_LOG_FLOOR`, `_mute_stream_loggers`, `_restore_stream_loggers`
  and both call sites.
- `AgentREPL.__init__(bot, config, renderer, *, runner: Optional[TurnRunner] = None)`;
  `self.runner`; `history` becomes a read-only property aliasing `runner.history`;
  console via `get_console()`.
- `run()`: optional resume at start, `PromptSession(history=FileHistory|InMemoryHistory)`,
  `prompt_async` inside `self.renderer.region.modal()`, each agent turn as an
  `asyncio.Task` with a SIGINT handler that calls `runner.cancel()`.
- `send()` / `send_stream()` keep their signatures and delegate to the runner.
- `run_batch(lines) -> int`, `add_post_turn_hook()`, `suspend()`.
- New tests in `test_repl_runner.py`; `test_integration.py` edited only if a
  FEAT-168 test is genuinely incompatible (expected: none — see contract).

**NOT in scope**: `agent_repl.py` option parsing and mode resolution
(TASK-3413), the TUI (TASK-3410-3412), `commands.py` (TASK-3406),
`conftest.py` (TASK-3416), agentd `attach` (TASK-3415).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/repl.py` | MODIFY | config fields, runner delegation, modal prompt, cancellation, FileHistory, batch mode, hooks |
| `packages/ai-parrot/tests/cli/test_repl_runner.py` | CREATE | Ctrl+C cancel, FileHistory, batch mode, no logger mutation, hooks |
| `packages/ai-parrot/tests/cli/test_integration.py` | MODIFY | only if required; the FEAT-168 suite must stay green (AC25) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import logging, sys                                                   # verified: repl.py:8-9
from datetime import datetime                                         # verified: repl.py:10
from typing import Any, AsyncIterator, List, Optional                 # verified: repl.py:11 (extend with ContextManager, Iterable)
from uuid import uuid4                                                # verified: repl.py:12
from prompt_toolkit import PromptSession                              # verified: repl.py:14
from prompt_toolkit.completion import WordCompleter                   # verified: repl.py:15
from prompt_toolkit.history import InMemoryHistory                    # verified: repl.py:16
from prompt_toolkit.history import FileHistory                        # verified: importable, prompt_toolkit 3.0.47 (FileHistory(filename))
from prompt_toolkit.patch_stdout import patch_stdout                  # verified: repl.py:17
from pydantic import BaseModel, Field                                 # verified: repl.py:18
from parrot.bots.abstract import AbstractBot                          # verified: repl.py:21
from parrot.cli.commands import ConversationTurn, SlashCommand, SlashCommandDispatcher   # verified: repl.py:22
from parrot.cli.renderer import ResponseRenderer                      # verified: repl.py:23
from parrot.models.outputs import OutputMode                          # verified: repl.py:24 (kept for _StreamedResponse users; runner passes it)
from parrot.models.responses import AIMessage                         # verified: repl.py:25
from parrot.cli.console import get_console                            # provided by TASK-3400
from parrot.cli.modes import UIMode, history_path                     # provided by TASK-3401
from parrot.cli.events import (TurnStarted, TextDelta, TurnCompleted, TurnFailed, TurnCancelled, PostTurnHook)   # provided by TASK-3403
from parrot.cli.session import TurnRunner                             # provided by TASK-3404
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/repl.py  (328 lines)
_STREAM_LOG_FLOOR = logging.WARNING                                   # line 30   (DELETE; occurrences 1)
def _mute_stream_loggers() -> dict[int, int]                          # lines 33-49 (DELETE)
def _restore_stream_loggers(saved: dict[int, int]) -> None            # lines 52-58 (DELETE)
class REPLConfig(BaseModel):                                          # line 61
    agent_name: str; streaming: bool = True; server_url: Optional[str] = None   # lines 82-84
    session_id: str = Field(default_factory=lambda: str(uuid4()))     # line 85
    user_id: str = "cli-user"                                         # line 86  (→ Optional[str]; occurrences 1)
    permission_context: Optional[Any] = None                          # line 87  (anchor; occurrences 1)
    model_config = {"arbitrary_types_allowed": True}                  # line 89
class AgentREPL:                                                      # line 92
    def __init__(self, bot: AbstractBot, config: REPLConfig, renderer: ResponseRenderer) -> None   # line 109
        self.dispatcher = SlashCommandDispatcher(); self.history: List[ConversationTurn] = []      # lines 125-126
        self.console = Console(file=sys.__stdout__, force_terminal=True)                           # line 128 (REPLACE; occurrences 1)
    async def run(self) -> None                                       # line 131 (PromptSession 147-150 with `history=InMemoryHistory(),` :148;
                                                                      #   `with patch_stdout():` :154; `text = await session.prompt_async(prompt)` :157;
                                                                      #   quit/exit intercept 174-176; dispatch 179; turn 184-198)
    async def send(self, query: str) -> AIMessage                     # line 200 (KEEP signature)
    async def send_stream(self, query: str) -> None                   # line 228 (KEEP signature; mute :247 / restore :279 DELETE)
    def register_command(self, cmd: SlashCommand) -> None             # line 296 (KEEP)
class _StreamedResponse: def __init__(self, query: str, output: str)  # lines 305-328 (KEEP as batch fallback proxy)

# TASK-3404 TurnRunner(bot, config, *, capabilities=None): history, is_active, capabilities, run_turn(query) -> AsyncIterator[TurnEvent],
#   cancel() -> bool, load_history(session_id) -> list[ConversationTurn], reset_session() -> str, add_post_turn_hook(hook)
# TASK-3405 ResponseRenderer: region (property, LiveRegion), render_turn_event(event), render_history(turns, *, session_id),
#   render_stream_start/chunk/end unchanged signatures
# TASK-3400 LiveRegion.modal() -> context manager
# TASK-3401 history_path(agent_name) -> Path ; UIMode enum (AUTO/INLINE/TUI)
# TASK-3406 CommandContext protocol: bot, config, renderer, dispatcher, runner, history (property), suspend() -> ContextManager[None]

# tests/cli/test_integration.py — constraints this task must keep true:
#   AgentREPL(mock_agent, repl_config, renderer) positional construction (lines 116, 131, 146, 259, 275, 289, 320, 372, …)
#   REPLConfig(agent_name="test").user_id == "cli-user" (lines 160-163)
#   repl.send("hello") → mock_agent.ask called with output_mode=TERMINAL and session_id kwargs (lines 253-292)
#   repl.history is readable, len 1 after a turn, 0 after "/clear" (lines 275-278, 351-352, 386-394)
#   test_send_stream_renders_chunks (304-352) replaces renderer.render_stream_start/chunk/end on the INSTANCE and expects
#   start once, end once, chunk ≥1 — so send_stream must call those three renderer methods by attribute lookup.
# tests/cli/conftest.py — mock_agent is an AsyncMock (ask_stream yields str chunks only; no final AIMessage)
```

### Does NOT Exist
- ~~`AgentREPL.add_post_turn_hook`, `.on_turn_end`, `.hooks`~~ — no hook mechanism exists; THIS task adds `add_post_turn_hook` (agentd currently monkeypatches `send`/`send_stream`, `agentd/cli.py:205-230` — untouched here, TASK-3415).
- ~~`KeyboardInterrupt` reaching `repl.py:190` during a turn on Python ≥3.11~~ — `asyncio.run`'s runner turns SIGINT into cancellation of the main task; Ctrl+C **at the prompt** does raise `KeyboardInterrupt` from `prompt_async` (prompt_toolkit owns the terminal then). Install a loop SIGINT handler for the duration of a turn (blueprint).
- ~~`REPLConfig.ui_mode` / `.resume_session_id` / `.server_token` / `.history_enabled`~~ — added by THIS task.
- ~~`AgentREPL.history` as a plain list attribute after this task~~ — it becomes a property over `runner.history`; assigning to it is not supported.
- ~~`_mute_stream_loggers`~~ — deleted; nothing may set handler levels (AC14).
- ~~`ResponseRenderer.console` with `force_terminal=True` bypass~~ — gone after TASK-3405.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/cli/repl.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/cli/test_repl_runner.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/cli/test_integration.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/repl.py#REPLConfig",
    "sym:packages/ai-parrot/src/parrot/cli/repl.py#AgentREPL",
    "sym:packages/ai-parrot/src/parrot/cli/repl.py#AgentREPL.run",
    "sym:packages/ai-parrot/src/parrot/cli/repl.py#AgentREPL.send",
    "sym:packages/ai-parrot/src/parrot/cli/repl.py#AgentREPL.send_stream",
    "sym:packages/ai-parrot/src/parrot/cli/repl.py#_mute_stream_loggers",
    "sym:packages/ai-parrot/src/parrot/cli/repl.py#_restore_stream_loggers",
    "sym:packages/ai-parrot/src/parrot/cli/repl.py#_StreamedResponse",
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#SlashCommandDispatcher",
    "sym:packages/ai-parrot/src/parrot/cli/renderer.py#ResponseRenderer"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `AgentREPL` never calls `bot.ask`/`bot.ask_stream` after this task (AC5): `grep -n "ask_stream\|bot.ask(" repl.py` must be empty.
- `patch_stdout()` **stays** around the loop (`repl.py:154`); the region cooperates with it as devloop does (spec §7).
- One turn at a time is enforced by the runner; the REPL only awaits.
- `send()` is batch and `send_stream()` is streaming regardless of `config.streaming`; implement by saving/restoring `config.streaming` around the runner call (the runner reads it) — keep the shim small and documented.
- Ctrl+C **at the prompt** → hint and continue (unchanged); Ctrl+C **during a turn** → `runner.cancel()`; the loop continues (AC18). Ctrl+D → exit (unchanged).
- Non-TTY batch: no picker, no alternate screen, plain sequential output (the region degrades because the console is not a terminal).
- Inside a worktree run tests with `PYTHONPATH=packages/ai-parrot/src pytest …`; never `uv sync` there.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/devloop/console.py:816-890` — the sibling loop that already wraps `prompt_async` with `patch_stdout()` and a `RunView` live region.
- `packages/ai-parrot-integrations/src/parrot/integrations/agentd/cli.py:156-199` — the consumer that will use `add_post_turn_hook` (TASK-3415).

---

## Implementation Blueprint

### Steps (in order)
1. Delete lines 27-58 (`_STREAM_LOG_FLOOR`, both logger helpers) and the two call sites — *why*: AC6/AC14 — the region contains the render, so muting is unnecessary and forbidden.
2. Extend `REPLConfig` (after line 87) and change `user_id` to `Optional[str]` — *why*: server mode omits `user_id` (spec Q8) and TASK-3413 needs `ui_mode`/`resume_session_id`/`server_token`/`history_enabled`.
3. Rewrite `__init__` to build/accept the runner and use `get_console()`; add the `history` property, `add_post_turn_hook`, `suspend` — *why*: `CommandContext` (TASK-3406) is satisfied structurally.
4. Rewrite `run()` per block below — *why*: modal prompt, FileHistory, resume, task-based turn with SIGINT handler.
5. Rewrite `send`/`send_stream` as runner consumers; add `_render_turn` and `run_batch` — *why*: one lifecycle (AC5), batch mode (AC2).
6. Run `pytest packages/ai-parrot/tests/cli/test_integration.py -q`; edit it only if a contract listed above was impossible to keep — *why*: AC25.
7. Write `test_repl_runner.py`.

### `packages/ai-parrot/src/parrot/cli/repl.py` (MODIFY — deletions, config, constructor)
```python
# occurrences: 1 (verified: grep -c '_STREAM_LOG_FLOOR = logging.WARNING' packages/ai-parrot/src/parrot/cli/repl.py)
# DELETE — lines 27-58: the comment block, `_STREAM_LOG_FLOOR`, `_mute_stream_loggers`, `_restore_stream_loggers`
# DELETE — line 247 `saved_levels = _mute_stream_loggers()` and line 279 `_restore_stream_loggers(saved_levels)` (occurrences 1 each)

# occurrences: 1 (verified: grep -c 'from prompt_toolkit.history import InMemoryHistory' packages/ai-parrot/src/parrot/cli/repl.py)
# REPLACE — line 16
from prompt_toolkit.history import FileHistory, InMemoryHistory
# AFTER — insert below `from parrot.models.responses import AIMessage` (verified: repl.py:25)
from parrot.cli.console import get_console                                                    # provided by TASK-3400
from parrot.cli.events import PostTurnHook, TextDelta, TurnCancelled, TurnCompleted, TurnFailed, TurnStarted   # provided by TASK-3403
from parrot.cli.modes import UIMode, history_path                                               # provided by TASK-3401
from parrot.cli.session import TurnRunner                                                       # provided by TASK-3404

# occurrences: 1 (verified: grep -c 'user_id: str = "cli-user"' packages/ai-parrot/src/parrot/cli/repl.py)
# REPLACE — line 86
    user_id: Optional[str] = "cli-user"
# occurrences: 1 (verified: grep -c 'permission_context: Optional\[Any\] = None' packages/ai-parrot/src/parrot/cli/repl.py)
# AFTER — insert below line 87
    ui_mode: UIMode = UIMode.AUTO
    resume_session_id: Optional[str] = None
    server_token: Optional[str] = None
    history_enabled: bool = True

# occurrences: 1 (verified: grep -c 'self.console = Console(file=sys.__stdout__, force_terminal=True)' packages/ai-parrot/src/parrot/cli/repl.py)
# REPLACE — __init__ signature (line 109-114) and body lines 122-129
    def __init__(self, bot: AbstractBot, config: REPLConfig, renderer: ResponseRenderer,
                 *, runner: Optional[TurnRunner] = None) -> None:
        """Initialise the REPL. ``runner`` defaults to ``TurnRunner(bot, config)``."""
        self.bot = bot
        self.config = config
        self.renderer = renderer
        self.dispatcher = SlashCommandDispatcher()
        self.runner: TurnRunner = runner or TurnRunner(bot, config)
        self.console = get_console()
        self.logger = logging.getLogger(__name__)

    @property
    def history(self) -> List[ConversationTurn]:
        """Display/export history — owned by the runner (read-only alias)."""
        return self.runner.history

    def add_post_turn_hook(self, hook: PostTurnHook) -> None:
        """Register a coroutine awaited after each completed turn (agentd uses this; AC15)."""
        self.runner.add_post_turn_hook(hook)

    def suspend(self):
        """Release the terminal to a foreign prompt (HITL/device code) — ``LiveRegion.modal()``."""
        return self.renderer.region.modal()
```
**Why**: `history` as a property keeps every `repl.history` read in `test_integration.py` valid while making the runner the single owner. `Console` and `sys` imports become unused after this change — remove `from rich.console import Console` (line 19) and `import sys` (line 9) once `ruff` confirms.

### `packages/ai-parrot/src/parrot/cli/repl.py` (MODIFY — `run`, turn execution, batch)
```python
# occurrences: 1 (verified: grep -c 'text = await session.prompt_async(prompt)' packages/ai-parrot/src/parrot/cli/repl.py)
# REPLACE — run() body lines 145-198
        completer = WordCompleter(self.dispatcher.get_completions(), sentence=True)
        history = InMemoryHistory()
        if self.config.history_enabled:
            path = history_path(self.config.agent_name)
            path.parent.mkdir(parents=True, exist_ok=True)
            history = FileHistory(str(path))   # FILL IN: chmod 0o600 after first write — bounded by AC10
        session: PromptSession = PromptSession(history=history, completer=completer)
        prompt = f"{self.bot.name}> "
        self.logger.info("Starting REPL for agent '%s'", self.bot.name)
        if self.config.resume_session_id:
            turns = await self.runner.load_history(self.config.resume_session_id)
            self.renderer.render_history(turns, session_id=self.config.session_id)
        with patch_stdout():
            while True:
                try:
                    with self.renderer.region.modal():
                        text = await session.prompt_async(prompt)
                except EOFError:
                    self.console.print("\n[dim]Goodbye.[/dim]"); break
                except KeyboardInterrupt:
                    self.console.print("[dim]Use Ctrl+D or /quit to exit.[/dim]"); continue
                text = text.strip()
                if not text:
                    continue
                if text.lower() in ("quit", "exit"):
                    self.console.print("[dim]Goodbye.[/dim]"); break
                if await self.dispatcher.dispatch_async(text, self):
                    continue
                await self._turn_with_cancel(text)

    async def _turn_with_cancel(self, text: str) -> None:
        """Run one agent turn as a task; SIGINT while it runs cancels it instead of killing the REPL (AC18)."""
        loop = asyncio.get_running_loop()
        task = loop.create_task(self.send_stream(text) if self.config.streaming else self._send_and_render(text))
        # FILL IN: previous = signal.getsignal(SIGINT); loop.add_signal_handler(SIGINT, self.runner.cancel);
        #   try: await task  except KeyboardInterrupt: self.runner.cancel(); await asyncio.gather(task, return_exceptions=True)
        #   finally: loop.remove_signal_handler(SIGINT); signal.signal(SIGINT, previous)  (NotImplementedError → skip on Windows)
        #   — bounded by AC18; needs `import asyncio, signal` at the top of the module
        await task

    async def _send_and_render(self, text: str) -> None:
        self.renderer.render(await self.send(text))

    async def _consume(self, query: str, *, streaming: bool) -> Any:
        """Drive the runner and render each event; returns the final message (or None). Shim: runner reads config.streaming."""
        previous, self.config.streaming = self.config.streaming, streaming
        final: Any = None
        try:
            async for event in self.runner.run_turn(query):
                if isinstance(event, TurnStarted) and streaming:
                    self.renderer.render_stream_start()
                elif isinstance(event, TextDelta):
                    self.renderer.render_stream_chunk(event.text)
                elif isinstance(event, TurnCompleted):
                    final = event.message
                    if streaming:
                        self.renderer.render_stream_end(final)
                else:
                    self.renderer.render_turn_event(event)   # Tool*, TurnFailed, TurnCancelled
        finally:
            self.config.streaming = previous
        return final

    async def send(self, query: str) -> AIMessage:
        """Send a query (batch) and return the full response; history is recorded by the runner."""   # signature: repl.py:200
        return await self._consume(query, streaming=False)

    async def send_stream(self, query: str) -> None:
        """Send a query and render the streamed response (start/chunk/end on the renderer)."""       # signature: repl.py:228
        await self._consume(query, streaming=True)

    async def run_batch(self, lines: Iterable[str]) -> int:
        """Non-TTY mode: one turn per non-empty line, slash commands allowed, plain output; 1 if any turn FAILED."""
        # FILL IN: loop lines; dispatch slash; else events = run_turn; track TurnFailed → exit 1 — bounded by AC2
        return 0
```
**Why**: `_consume` calls `render_stream_start/chunk/end` via attribute lookup so `test_send_stream_renders_chunks` (test_integration.py:304-352) keeps observing them; all other events go to `render_turn_event`. The shim around `config.streaming` exists only because the runner's `run_turn(query)` signature (spec M5) reads the config. The SIGINT handler is what actually makes "Ctrl+C during a turn" cancel on Python ≥3.11 — the old `except KeyboardInterrupt` at `:190` was unreachable under `asyncio.run`.

### `packages/ai-parrot/tests/cli/test_repl_runner.py` (CREATE)
```python
"""AgentREPL-on-TurnRunner tests (FEAT-573 TASK-3407, spec §4)."""
from __future__ import annotations

import io
import logging
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console                          # verified: renderer.py:13

from parrot.cli.repl import AgentREPL, REPLConfig         # verified: repl.py:61, :92
from parrot.cli.renderer import ResponseRenderer          # verified: repl.py:23
from parrot.cli.console import set_console                # provided by TASK-3400


@pytest.fixture
def quiet_renderer():
    console = Console(file=io.StringIO(), force_terminal=False, width=100)
    set_console(console)
    yield ResponseRenderer(console=console), console
    set_console(None)


@pytest.mark.asyncio
async def test_repl_no_logger_level_mutation(mock_agent, quiet_renderer):
    renderer, _ = quiet_renderer
    before = [(id(h), h.level) for h in logging.getLogger().handlers]
    repl = AgentREPL(mock_agent, REPLConfig(agent_name="t", streaming=True), renderer)
    await repl.send_stream("hi")
    assert [(id(h), h.level) for h in logging.getLogger().handlers] == before   # AC14


@pytest.mark.asyncio
async def test_repl_run_batch_plain_output(mock_agent, quiet_renderer):
    renderer, console = quiet_renderer
    repl = AgentREPL(mock_agent, REPLConfig(agent_name="t", streaming=True, history_enabled=False), renderer)
    code = await repl.run_batch(["hello", "", "/info", "again"])
    out = console.file.getvalue()
    assert code == 0 and "\x1b[2K" not in out and "\x1b[?1049h" not in out   # AC2
    assert len(repl.history) == 2


@pytest.mark.asyncio
async def test_repl_file_history_used_when_enabled(mock_agent, quiet_renderer, tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    renderer, _ = quiet_renderer
    with patch("parrot.cli.repl.PromptSession") as ps:
        ps.return_value.prompt_async.side_effect = EOFError
        await AgentREPL(mock_agent, REPLConfig(agent_name="my agent"), renderer).run()
    history = ps.call_args.kwargs["history"]
    # FILL IN: assert type(history).__name__ == "FileHistory" and its filename lives under tmp_path/"cli"/"history";
    #          second run with history_enabled=False → InMemoryHistory — AC10


@pytest.mark.asyncio
async def test_repl_ctrl_c_cancels_active_turn(quiet_renderer):
    renderer, console = quiet_renderer
    # FILL IN: slow fake bot (async gen with asyncio.sleep(10) after first delta); start repl._turn_with_cancel in a task,
    #   let it yield, then os.kill(os.getpid(), SIGINT) or call repl.runner.cancel(); await; assert "Interrupted" in output,
    #   history unchanged, and a following send_stream still works — AC18


@pytest.mark.asyncio
async def test_repl_post_turn_hook_called(mock_agent, quiet_renderer):
    renderer, _ = quiet_renderer
    repl = AgentREPL(mock_agent, REPLConfig(agent_name="t", streaming=False), renderer)
    calls = []

    async def hook(ctx, turn):
        calls.append(turn.query)

    repl.add_post_turn_hook(hook)
    await repl.send("hello")
    assert calls == ["hello"]   # AC15
```
**Why**: the `mock_agent`/`renderer`-style fixtures from `tests/cli/conftest.py` are reused where possible; `set_console` (TASK-3400) redirects the shared console so `get_console()` inside `AgentREPL.__init__` never touches the real terminal. The SIGINT test is the only one that exercises `_turn_with_cancel` directly.

### `packages/ai-parrot/tests/cli/test_integration.py` (MODIFY — conditional)
```python
# occurrences: n/a — expected diff: EMPTY. Run the suite first. Only if `TestREPLConfig`/`TestAgentREPLSend`/`TestAgentREPLStream`/
# `TestSlashCommandsAsync` break for a reason that contradicts a contract above, adjust the SMALLEST assertion and record it in the
# Completion Note. Never delete a test.
```
**Why**: AC25 requires the FEAT-168 suite green; the contracts above were chosen so no edit is needed.

### FILL IN checklist
- [ ] `repl.py::run` — `0o600` on the history file; bounded by AC10.
- [ ] `repl.py::_turn_with_cancel` — SIGINT handler install/restore (Windows fallback); bounded by AC18.
- [ ] `repl.py::run_batch` — loop, slash dispatch, exit code; bounded by AC2.
- [ ] `test_repl_runner.py` — FileHistory assertions and the Ctrl+C test body.
- [ ] Remove now-unused imports (`sys`, `Console`, `AsyncIterator`, `datetime` if unused) — ruff.

---

## Acceptance Criteria

- [ ] `grep -n "ask_stream\|bot.ask(" packages/ai-parrot/src/parrot/cli/repl.py` empty (spec AC5).
- [ ] `_mute_stream_loggers`, `_restore_stream_loggers`, `_STREAM_LOG_FLOOR`, `Console(file=sys.__stdout__` absent from `repl.py` (spec AC11/AC12/AC14).
- [ ] `prompt_async` is called inside `region.modal()`; Ctrl+C during a turn cancels and the loop continues; Ctrl+D exits (spec AC18).
- [ ] Composer history persists via `FileHistory` under `$PARROT_HOME/cli/history/`; `history_enabled=False` uses `InMemoryHistory` (spec AC10).
- [ ] `run_batch` produces plain output and correct exit code (spec AC2).
- [ ] `add_post_turn_hook` exists and fires after completed turns only (spec AC15/AC18).
- [ ] `pytest packages/ai-parrot/tests/cli/test_integration.py -q` green with an empty (or minimal, documented) diff (spec AC25).
- [ ] `ruff check packages/ai-parrot/src/parrot/cli/repl.py` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/test_repl_runner.py -q`
- `pytest packages/ai-parrot/tests/cli/test_integration.py -q`

---

## Test Specification

See the CREATE block above; required names: `test_repl_no_logger_level_mutation`,
`test_repl_run_batch_plain_output`, `test_repl_file_history_used_when_enabled`,
`test_repl_ctrl_c_cancels_active_turn`, `test_repl_post_turn_hook_called`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3407-agent-repl-on-turn-runner.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-coder native `sonnet` seat (attempt e58e24b1e28940dcbd003e2dbb111a23), fixed by orchestrator
**Date**: 2026-09-18
**Notes**: Rewrote `AgentREPL` to consume `TurnRunner` instead of calling
`bot.ask`/`bot.ask_stream` directly, implementing the `CommandContext`
protocol added by TASK-3406. Made zero changes to `test_integration.py`
(verified its full FEAT-168 suite stays green, so no edit was needed).
Correctly implemented `add_post_turn_hook` as a wrapping closure
(`await hook(self, turn)`, not TASK-3406's/TurnRunner's raw
`(TurnRunner, turn)` signature), verified against TASK-3404's actual
delivered `session.py` — deviated from the blueprint's literal one-liner
per the flagged design note, and locked it in with an explicit
`assert ctx is repl` in the new test. Fixed AC5's own literal grep
contract (blueprint prose accidentally contained the banned substrings).

**Confirmed and fixed by orchestrator review**: 2 of 5 new tests in
`test_repl_runner.py` did not isolate `PARROT_HOME`, so every real turn's
unconditional `save_session_pointer()` (session.py:227) wrote to the
developer's real `~/.parrot` — failing on a read-only `$HOME` (this
environment) and, more importantly, silently polluting real user state on
any normal machine. Fixed with an autouse `_isolated_parrot_home` fixture,
matching `test_modes.py`'s established convention. Fix commit:
`e0b317a4a332c2ed1dd34d6718b68e9b6a440f01`. Recorded as model feedback
(`unisolated-real-home-in-tests`).

**Result confirmed by orchestrator**: `test_repl_runner.py`: 5 passed.
`test_integration.py::TestSlashCommandsAsync::test_clear_new_session` —
the test flagged as an expected transitional failure by TASK-3406 — now
**passes**. `test_integration.py` full suite: 25 passed, 4 pre-existing
`TestStandaloneAgentLoader` failures confirmed unrelated (present on `dev`
itself, out of scope here).

**Deviations from spec**: `add_post_turn_hook` wraps the hook rather than
the blueprint's bare one-liner (documented above, verified correct against
the actual delivered contract); two docstring lines reworded to satisfy
AC5's literal grep check.

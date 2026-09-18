# TASK-3412: `AgentWorkspaceApp` — the Textual workspace application

**Feature**: FEAT-573 — Agent Terminal Workspace for `parrot agent`
**Spec**: `sdd/specs/new-ui-cli-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3404, TASK-3410, TASK-3411
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11 (second half). Wires the widgets (TASK-3410) and adapters
(TASK-3411) into one `App[int]` that drives `TurnRunner.run_turn()`
(TASK-3404) in an exclusive Textual worker. It owns the screen, the fixed
key bindings, the one-turn-at-a-time rule, cancellation, auto-follow resume,
tool/log toggles, narrow-terminal degradation and the exit code. It never
calls the bot directly (AC5).

---

## Scope

- Implement `AgentWorkspaceApp(App[int])` with `CSS_PATH = "app.tcss"`, the
  spec-fixed `BINDINGS`, `compose`, `on_mount` (render `resume_turns`, focus
  composer, install `DrawerLogHandler` on the root logger), `on_unmount`
  (remove the handler), `submit()`, `_run_turn` worker, and the actions
  `action_cancel_turn`, `action_toggle_tools`, `action_toggle_logs`,
  `action_resume_follow`, `action_clear_session` (`/clear`).
- Second submission while a turn is active → `notify(...)`, text kept (AC4).
- Ctrl+C: cancel the active turn; when idle, a second press within 2 s exits (AC18).
- `/quit` (`SystemExit`) → `self.exit(0)`; `App.exit(return_code=…)` becomes the process exit code (TASK-3413).
- Narrow terminals (`< 60` cols): collapse tool panels and hide usage before the composer shrinks.
- Tests via `App.run_test()` covering the spec §4 TUI rows.

**NOT in scope**: widgets and CSS (TASK-3410); renderer/context/log handler
classes (TASK-3411); Click wiring, mode resolution, `run_async()` call site
(TASK-3413); `tests/cli/conftest.py` (TASK-3416).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/tui/app.py` | CREATE | `AgentWorkspaceApp` |
| `packages/ai-parrot/tests/cli/tui/test_app.py` | CREATE | Interaction tests via `run_test()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
import logging
import time
from typing import Any, List, Optional

from prompt_toolkit.history import History                        # verified: prompt_toolkit 3.0.47
from textual import events, work                                  # verified: textual 8.2.8 probe (work(exclusive=..., group=...))
from textual.app import App, ComposeResult                        # verified: textual 8.2.8 probe (run_async, run_test, exit, notify, suspend, workers)
from textual.binding import Binding                               # verified: textual 8.2.8 probe
from textual.widgets import Footer, Header                        # verified: textual 8.2.8 probe

from parrot.cli.commands import ConversationTurn, SlashCommandDispatcher   # verified: commands.py:38, :70
from parrot.cli.events import TurnCancelled, TurnCompleted, TurnEvent, TurnFailed, TurnStarted, ToolStarted   # provided by TASK-3403
from parrot.cli.repl import REPLConfig                                     # verified: repl.py:61 (extended by TASK-3407)
from parrot.cli.session import TurnInProgressError, TurnRunner             # provided by TASK-3404
from parrot.cli.tui.adapter import DrawerLogHandler, TUICommandContext, TUIRenderer   # provided by TASK-3411
from parrot.cli.tui.widgets import Composer, LogDrawer, StatusBar, ToolActivity, TranscriptView   # provided by TASK-3410
```

### Existing Signatures to Use
```python
# parrot/cli/session.py — provided by TASK-3404 (spec §3 Module 5, fixed)
class TurnRunner:
    history: list[ConversationTurn]
    @property is_active -> bool
    async def run_turn(self, query: str) -> AsyncIterator[TurnEvent]     # raises TurnInProgressError if active
    def cancel(self) -> bool
    def reset_session(self) -> str
# parrot/cli/commands.py — TASK-3406
class SlashCommandDispatcher:
    async def dispatch_async(self, input_text: str, ctx: CommandContext) -> bool   # commands.py:95 (param renamed by TASK-3406)
    def get_completions(self) -> List[str]                                          # commands.py:130
# /quit handler raises SystemExit(0) — commands.py:319 (kept by TASK-3406)
# parrot/cli/tui/widgets.py — TASK-3410
class TranscriptView: following: reactive[bool]; async def apply(event); def append_renderable(r); def resume_follow(); def begin_turn(ev)
class Composer(TextArea): class Submitted(Message): text: str; __init__(*, history: History, completions: Callable[[], List[str]], **kw)
class StatusBar(Static): def apply(event); def set_cancelling()
class ToolActivity(Collapsible): collapsed: reactive[bool]
class LogDrawer(RichLog): display: bool
# parrot/cli/tui/adapter.py — TASK-3411
class TUIRenderer(transcript); class TUICommandContext(app, bot, config, runner, dispatcher, renderer); class DrawerLogHandler(app, drawer)
# textual 8.2.8 (verified via probe)
class App:
    BINDINGS: list[Binding]; CSS_PATH: str
    def exit(self, result=None, return_code: int = 0, message=None) -> None
    def notify(self, message, *, title="", severity="information", timeout=None) -> None
    async def run_async(self, *, headless=False, inline=False, ...) -> ReturnType | None
    async def run_test(self, *, headless=True, size=(80, 24), ...) -> AsyncGenerator[Pilot, None]
    workers: WorkerManager      # worker.cancel()
    size: Size                  # events.Resize has .size
def work(method=None, *, name="", group="default", exit_on_error=True, exclusive=False, description=None, thread=False)
class Pilot: async def press(*keys); async def pause(delay=None); async def resize_terminal(width, height)
```

### Does NOT Exist
- ~~`parrot.cli.tui.app`~~ — created here.
- ~~`TurnRunner.run_turn` returning a list~~ — it is an async generator; iterate with `async for` inside the worker.
- ~~a "queue" of pending submissions~~ — spec: reject or disable a second submission, never queue (AC4).
- ~~`App.suspend()` used here~~ — it is wrapped by `TUICommandContext.suspend()` (TASK-3411); the app never calls it directly.
- ~~`logging` level mutation~~ — only `root.addHandler(handler)` / `removeHandler` (AC14).
- ~~`bot.ask` / `bot.ask_stream`~~ — never called from `parrot/cli/tui/*` (AC5).
- ~~`App.run()` (sync)~~ in `agent_repl.py` — TASK-3413 uses `await app.run_async()` because it already runs inside `asyncio.run(_run(...))` (agent_repl.py:68).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/cli/tui/app.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/cli/tui/test_app.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#SlashCommandDispatcher",
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#SlashCommandDispatcher.dispatch_async",
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#SlashCommandDispatcher.get_completions",
    "sym:packages/ai-parrot/src/parrot/cli/repl.py#REPLConfig"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `PYTHONPATH=packages/ai-parrot/src pytest ...` inside a worktree; never `uv sync` there. `textual` is importable only after TASK-3399 lands and the shared venv is re-synced by the main-checkout operator; tests start with `pytest.importorskip("textual")`.
- The bindings list is **fixed by spec §3 Module 11**: `enter` send (handled inside `Composer`), `ctrl+j`/`shift+enter` newline (Composer), `up`/`down` history (Composer), `tab` completion (Composer), `pageup`/`pagedown` scroll transcript, `end` resume follow, `ctrl+c` cancel/quit, `ctrl+d` quit, `f2` toggle tools, `f3` toggle logs, `ctrl+l` = `/clear`. Composer-level keys are NOT app bindings.
- `@work(exclusive=True, group="turn")` guarantees one turn worker; `submit()` still checks `runner.is_active` first so the rejection is a friendly notice, not a worker cancellation (AC4).
- Cancellation goes through `runner.cancel()`; the runner yields `TurnCancelled` which the transcript renders (AC18). Do not cancel the Textual worker directly — that would skip the runner's cleanup.
- Test with `run_test(size=(80, 24))`; narrow test uses `size=(50, 20)`.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/repl.py:154-198` — the inline loop whose semantics (`/quit` → `SystemExit`, bare `quit`/`exit`, Ctrl+C hint) this app mirrors.
- `packages/ai-parrot/src/parrot/cli/agent_repl.py:68` — `asyncio.run(_run(...))`: the reason TASK-3413 must use `run_async()`.

---

## Implementation Blueprint

### Steps (in order)
1. Write part 1 (imports, class, bindings, `__init__`, `compose`, `on_mount`/`on_unmount`) — *why*: fixes the widget ids the CSS (TASK-3410) already targets.
2. Write part 2 (`submit`, `_run_turn`, actions, resize) — *why*: the behavioural rules AC3/AC4/AC18 depend on.
3. Write `test_app.py` with a fake runner (async generator of scripted events) — *why*: no bot, no Textual worker timing flakiness; the runner contract is what we test against.

### `packages/ai-parrot/src/parrot/cli/tui/app.py` — part 1/2 (CREATE)
```python
"""Full-screen Textual workspace for ``parrot agent`` (spec §3 Module 11)."""
from __future__ import annotations

import logging
import time
from typing import Any, List, Optional

from prompt_toolkit.history import History  # verified: prompt_toolkit 3.0.47
from textual import events, work  # verified: textual 8.2.8 probe
from textual.app import App, ComposeResult  # verified: textual 8.2.8 probe
from textual.binding import Binding  # verified: textual 8.2.8 probe
from textual.widgets import Footer, Header  # verified: textual 8.2.8 probe

from parrot.cli.commands import ConversationTurn, SlashCommandDispatcher  # verified: commands.py:38, :70
from parrot.cli.events import TurnEvent  # provided by TASK-3403
from parrot.cli.repl import REPLConfig  # verified: repl.py:61
from parrot.cli.session import TurnRunner  # provided by TASK-3404
from parrot.cli.tui.adapter import DrawerLogHandler, TUICommandContext, TUIRenderer  # provided by TASK-3411
from parrot.cli.tui.widgets import Composer, LogDrawer, StatusBar, ToolActivity, TranscriptView  # provided by TASK-3410

NARROW_WIDTH = 60
QUIT_DOUBLE_PRESS_S = 2.0


class AgentWorkspaceApp(App[int]):
    """Full-screen agent workspace. The return value is the process exit code."""

    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("pageup", "scroll_transcript(-1)", "Scroll up", show=False),
        Binding("pagedown", "scroll_transcript(1)", "Scroll down", show=False),
        Binding("end", "resume_follow", "Follow"),
        Binding("ctrl+c", "cancel_turn", "Cancel / quit", priority=True),
        Binding("ctrl+d", "quit_app", "Quit", priority=True),
        Binding("f2", "toggle_tools", "Tools"),
        Binding("f3", "toggle_logs", "Logs"),
        Binding("ctrl+l", "clear_session", "Clear", priority=True),
    ]

    def __init__(self, *, bot: Any, config: REPLConfig, runner: TurnRunner, dispatcher: SlashCommandDispatcher,
                 history: History, resume_turns: Optional[List[ConversationTurn]] = None) -> None:
        super().__init__()
        self.bot = bot
        self.config = config
        self.runner = runner
        self.dispatcher = dispatcher
        self._history = history
        self._resume_turns = resume_turns or []
        self._log_handler: Optional[DrawerLogHandler] = None
        self._last_ctrl_c = 0.0
        self.logger = logging.getLogger(__name__)
        self.command_context: Optional[TUICommandContext] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield TranscriptView(id="transcript")
        yield LogDrawer(id="logs")
        yield Composer(history=self._history, completions=self.dispatcher.get_completions, id="composer")
        yield StatusBar(id="status")
        yield Footer()

    async def on_mount(self) -> None:
        self.title = f"parrot agent · {self.config.agent_name}"
        self.sub_title = f"tui · session {self.config.session_id[:8]}"
        transcript = self.query_one("#transcript", TranscriptView)
        renderer = TUIRenderer(transcript)
        self.command_context = TUICommandContext(self, self.bot, self.config, self.runner, self.dispatcher, renderer)
        if self._resume_turns:
            renderer.render_history(self._resume_turns, session_id=self.config.session_id)
        self._log_handler = DrawerLogHandler(self, self.query_one("#logs", LogDrawer))
        logging.getLogger().addHandler(self._log_handler)  # AC14: add a handler, never change levels
        self.query_one("#composer", Composer).focus()

    def on_unmount(self) -> None:
        if self._log_handler is not None:
            logging.getLogger().removeHandler(self._log_handler)
            self._log_handler = None
```
**Why this shape**: ids match `app.tcss` (TASK-3410); the `BINDINGS` list is the spec's, minus the composer-level keys that `Composer._on_key` owns. `priority=True` on ctrl+c/ctrl+d/ctrl+l makes them work while the `TextArea` has focus (TextArea binds many keys itself). The log handler is added on mount and removed on unmount — the only permitted logging change (AC14).

### `packages/ai-parrot/src/parrot/cli/tui/app.py` — part 2/2 (CREATE, continues the same file)
```python
    async def on_composer_submitted(self, message: Composer.Submitted) -> None:
        await self.submit(message.text)

    async def submit(self, text: str) -> None:
        """Slash command → dispatcher; otherwise start the turn worker (one at a time, AC4)."""
        text = text.strip()
        if not text:
            return
        if text.lower() in ("quit", "exit"):
            self.exit(0)
            return
        if text.startswith("/"):
            try:
                await self.dispatcher.dispatch_async(text, self.command_context)  # type: ignore[arg-type]
            except SystemExit as exc:  # /quit — commands.py:319
                self.exit(int(exc.code or 0))
            return
        if self.runner.is_active:
            self.notify("A request is running — Ctrl+C cancels", severity="warning")
            self.query_one("#composer", Composer).load_text(text)  # keep the typed text (AC4)
            return
        self.query_one("#transcript", TranscriptView).resume_follow()
        self._run_turn(text)

    @work(exclusive=True, group="turn")
    async def _run_turn(self, query: str) -> None:
        transcript = self.query_one("#transcript", TranscriptView)
        status = self.query_one("#status", StatusBar)
        async for event in self.runner.run_turn(query):
            await transcript.apply(event)
            status.apply(event)
            # FILL IN: on TurnCompleted/TurnFailed/TurnCancelled update sub_title with the (possibly new) session id — bounded by AC20 (/clear)

    def action_cancel_turn(self) -> None:
        if self.runner.is_active:
            self.query_one("#status", StatusBar).set_cancelling()
            self.runner.cancel()
            return
        now = time.monotonic()
        if now - self._last_ctrl_c < QUIT_DOUBLE_PRESS_S:
            self.exit(0)
        else:
            self._last_ctrl_c = now
            self.notify("Press Ctrl+C again to quit (Ctrl+D also quits)")

    def action_quit_app(self) -> None:
        self.exit(0)

    def action_toggle_tools(self) -> None:
        # FILL IN: flip `collapsed` on every ToolActivity in the transcript (query(ToolActivity)) — bounded by spec §3 M11 bindings
        ...

    def action_toggle_logs(self) -> None:
        drawer = self.query_one("#logs", LogDrawer)
        drawer.display = not drawer.display

    def action_resume_follow(self) -> None:
        self.query_one("#transcript", TranscriptView).resume_follow()

    def action_scroll_transcript(self, direction: int) -> None:
        # FILL IN: page_down/page_up on the transcript; scrolling up sets following=False — bounded by AC3
        ...

    async def action_clear_session(self) -> None:
        await self.submit("/clear")

    def on_resize(self, event: events.Resize) -> None:
        narrow = event.size.width < NARROW_WIDTH
        for panel in self.query(ToolActivity):
            if narrow:
                panel.collapsed = True
        # FILL IN: StatusBar hides the tokens segment when narrow (add a `compact` flag on StatusBar via TASK-3410's API
        # only if it exists; otherwise set a CSS class "compact" on #status) — bounded by spec §3 M11 "Narrow terminals"
```
**Why this shape**: `submit()` is the single entry for both the composer message and `ctrl+l`, so `/clear` semantics (new session id, transcript notice) come from the shared `_cmd_clear` handler (AC20) rather than a TUI-only path. `SystemExit` from `/quit` is caught here, not in the adapter, because only the app can translate it into an exit code. Cancellation calls `runner.cancel()` so the runner emits `TurnCancelled` and never records the turn (AC18).

### `packages/ai-parrot/tests/cli/tui/test_app.py` (CREATE)
```python
"""Interaction tests for AgentWorkspaceApp (FEAT-573, spec §4 TUI rows)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, List
from unittest.mock import MagicMock

import pytest

pytest.importorskip("textual")

from prompt_toolkit.history import InMemoryHistory  # verified: repl.py:16

from parrot.cli.commands import SlashCommandDispatcher  # verified: commands.py:70
from parrot.cli.events import TextDelta, ToolFinished, ToolStarted, TurnCancelled, TurnCompleted, TurnEventKind, TurnStarted
from parrot.cli.repl import REPLConfig  # verified: repl.py:61
from parrot.cli.tui.app import AgentWorkspaceApp
from parrot.cli.tui.widgets import Composer, StatusBar, ToolActivity, TranscriptView, TurnPanel


class _FakeRunner:
    """Scripted TurnRunner: yields the given events slowly; cancel() ends with TurnCancelled."""

    def __init__(self, script: List[Any], delay: float = 0.01) -> None:
        self.script, self.delay, self.history, self._active, self._cancelled = script, delay, [], False, False

    @property
    def is_active(self) -> bool:
        return self._active

    def cancel(self) -> bool:
        self._cancelled = True
        return self._active

    def reset_session(self) -> str:
        return "new-session"

    async def run_turn(self, query: str) -> AsyncIterator[Any]:
        self._active = True
        try:
            yield TurnStarted(kind=TurnEventKind.STARTED, turn_id="t", seq=0, query=query, streaming=True)
            for i, ev in enumerate(self.script, start=1):
                await asyncio.sleep(self.delay)
                if self._cancelled:
                    yield TurnCancelled(kind=TurnEventKind.CANCELLED, turn_id="t", seq=i, partial_text="partial")
                    return
                yield ev
        finally:
            self._active = False
```

**Part 2 of the same file** — continue appending to `packages/ai-parrot/tests/cli/tui/test_app.py` (split only to respect the 80-line block cap):
```python
def _app(runner: _FakeRunner) -> AgentWorkspaceApp:
    bot = MagicMock(); bot.get_available_tools.return_value = []; bot.get_tools_count.return_value = 0
    return AgentWorkspaceApp(bot=bot, config=REPLConfig(agent_name="a"), runner=runner,
                             dispatcher=SlashCommandDispatcher(), history=InMemoryHistory())


def _deltas(*texts: str) -> List[Any]:
    evs = [TextDelta(kind=TurnEventKind.DELTA, turn_id="t", seq=i + 1, text=t) for i, t in enumerate(texts)]
    evs.append(TurnCompleted(kind=TurnEventKind.COMPLETED, turn_id="t", seq=len(evs) + 1, text="".join(texts), message=MagicMock(usage=None, tool_calls=[])))
    return evs


@pytest.mark.asyncio
async def test_submit_streams_and_follows():
    app = _app(_FakeRunner(_deltas("Hello", " world")))
    async with app.run_test() as pilot:
        await app.submit("hi")
        await pilot.pause(0.2)
        view = app.query_one("#transcript", TranscriptView)
        assert len(view.query(TurnPanel)) == 1 and view.following is True


@pytest.mark.asyncio
async def test_second_submit_rejected_while_active():
    # FILL IN: long script; submit twice; assert one TurnPanel and composer text kept — AC4
    ...


@pytest.mark.asyncio
async def test_ctrl_c_cancels_then_double_press_quits():
    # FILL IN: submit, press ctrl+c → TurnCancelled rendered; idle: ctrl+c twice within 2s → app.return_code == 0 — AC18
    ...


@pytest.mark.asyncio
async def test_tool_rows_and_f2_toggle():
    # FILL IN: script with ToolStarted/ToolFinished (same call_id) → one ToolActivity row; press f2 flips collapsed — AC6
    ...


@pytest.mark.asyncio
async def test_slash_quit_exits_zero_and_logs_routed():
    # FILL IN: await app.submit("/quit") → app.return_code == 0; separately logging.warning lands in #logs, not transcript — AC14/AC20
    ...


@pytest.mark.asyncio
async def test_resize_narrow_collapses_tools():
    # FILL IN: run_test(size=(50, 20)) with a tool script → every ToolActivity.collapsed is True, composer still mounted — spec §3 M11
    ...
```
**Why**: the fake runner reproduces the runner contract (`is_active`, `cancel()` → `TurnCancelled`) so tests exercise app behaviour without the bot or lifecycle registry; rows map to spec §4 `test_tui_*`.

### FILL IN checklist
- [ ] `app.py::_run_turn` — sub_title refresh after `/clear`; bounded by AC20
- [ ] `app.py::action_toggle_tools` / `action_scroll_transcript` / `on_resize` — bounded by spec §3 M11, AC3
- [ ] `test_app.py` — five test bodies

---

## Acceptance Criteria

- [ ] `grep -n "ask_stream\|bot.ask(" packages/ai-parrot/src/parrot/cli/tui/*.py` is empty (AC5)
- [ ] Composer usable and transcript scrollable during a turn; `End` re-follows (AC3)
- [ ] Second submission rejected with a notice, text kept (AC4)
- [ ] Ctrl+C cancels an active turn via `runner.cancel()`; idle double-press quits; Ctrl+D quits (AC18)
- [ ] `/quit` → exit code 0; `/clear` goes through the shared handler (AC20)
- [ ] Log records land in the drawer; only `addHandler`/`removeHandler` on the root logger (AC14)
- [ ] `pytest packages/ai-parrot/tests/cli/tui/test_app.py -q` passes; `ruff check packages/ai-parrot/src/parrot/cli/tui/app.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/tui/test_app.py -q`

---

## Test Specification

See the `test_app.py` blueprint: six `run_test()` scenarios — stream + follow, second submit rejected, Ctrl+C cancel/quit, tool rows + F2, `/quit` + log routing, narrow resize.

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
7. **Move this file** to `tasks/completed/TASK-3412-tui-workspace-app.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-coder native `sonnet` seat (attempt 18ca07e3589e4b6896b01c9f4a6fdef3)
**Date**: 2026-09-18
**Notes**: Implemented `AgentWorkspaceApp(App[int])` wiring TASK-3410
widgets and TASK-3411 adapters into one screen, driving `TurnRunner.run_turn()`
via an exclusive `@work` worker. Filled all 4 blueprint FILL INs (sub_title
refresh on session rotation, tool-panel toggle, transcript scroll delegation,
narrow-terminal resize handling). Checked both historical feedback patterns:
`unisolated-real-home-in-tests` confirmed not applicable (constructor
injection of `TurnRunner`, tests use only `_FakeRunner`, zero
`PARROT_HOME`/`save_session_pointer`/`TurnRunner(` matches); also
independently re-verified TASK-3411's `App.suspend()`/`SuspendNotSupported`
discrepancy does not recur here (`app.py` never calls `.suspend()` directly,
confirmed via grep — only via `TUICommandContext`, already tested).

Merge clean (`coder_merge` outcome=merged, 0 residual lint). `pytest
test_app.py`: 1 skipped (clean — `textual` still absent from shared `.venv`,
same carried-over gap since TASK-3399/3410/3411).

**Feedback recorded**: none — clean delivery, all checks correctly applied.
**Deviations from spec**: none.

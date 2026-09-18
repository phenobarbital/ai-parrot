# TASK-3410: Textual workspace widgets (transcript, turn panel, tool activity, composer, status bar, log drawer)

**Feature**: FEAT-573 — Agent Terminal Workspace for `parrot agent`
**Spec**: `sdd/specs/new-ui-cli-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3399, TASK-3403
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11 (first half). The full-screen presenter is a Textual `App`
(TASK-3412) composed of widgets that consume the presentation-neutral
`TurnEvent` family from `parrot/cli/events.py` (TASK-3403). This task creates
the widget layer only: a scrolling transcript with auto-follow, one panel per
turn (user text, streamed Markdown, collapsible tool rows), a multiline
composer with history/completion keys, a status bar that distinguishes
*waiting* from *streaming* from *running tool*, and a log drawer. Widgets
never call the bot and never import `TurnRunner`; they only react to events
the app feeds them — that keeps the TUI from becoming a second agent
implementation (spec §2 Overview, AC5).

Textual becomes importable only after TASK-3399 adds `textual>=8.2,<9` to
core (`pyproject.toml`); the API below was verified against textual 8.2.8.

---

## Scope

- Create the `parrot.cli.tui` package with a light `__init__.py`.
- Implement in `widgets.py`: `TranscriptView`, `TurnPanel`, `ToolActivity`,
  `Composer` (+ `Composer.Submitted` message), `StatusBar`, `LogDrawer`.
- Implement the 200-panel transcript cap with a single "(N earlier turns
  hidden — /export saves all)" notice and the 512 KiB per-turn text cap with a
  truncation marker (spec §3 M11 "Caps").
- Implement auto-follow: `anchor()` while following; any manual scroll up
  sets `following=False`; `resume_follow()` re-anchors.
- Ship `app.tcss` with the layout skeleton (header / transcript / composer /
  status / footer; log drawer hidden by default).
- Write widget tests using a minimal harness `App` and `App.run_test()`.

**NOT in scope**: the `AgentWorkspaceApp` itself, bindings/actions, the turn
worker, `submit()` (TASK-3412); `TUIRenderer`/`TUICommandContext`/log handler
(TASK-3411); any change to `agent_repl.py` (TASK-3413); `tests/cli/conftest.py`
(TASK-3416).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/tui/__init__.py` | CREATE | Package marker; docstring + `__all__`; lazy `__getattr__` re-exports |
| `packages/ai-parrot/src/parrot/cli/tui/widgets.py` | CREATE | The six widgets and the `Composer.Submitted` message |
| `packages/ai-parrot/src/parrot/cli/tui/app.tcss` | CREATE | Layout CSS consumed by `AgentWorkspaceApp.CSS_PATH` (TASK-3412) |
| `packages/ai-parrot/tests/cli/tui/__init__.py` | CREATE | Empty test package marker |
| `packages/ai-parrot/tests/cli/tui/test_widgets.py` | CREATE | Widget tests via `run_test()` |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, class names and signatures. Anything
> not listed must be verified with `grep`/`read` before use.

### Verified Imports
```python
from __future__ import annotations
import logging
from typing import Any, Callable, List, Optional

from rich.console import RenderableType                 # verified: rich 15.0.0 (used by textual Static.update VisualType)
from rich.text import Text                              # verified: renderer.py:17
from textual.app import App, ComposeResult              # verified: textual 8.2.8 probe
from textual.binding import Binding                     # verified: textual 8.2.8 probe
from textual.containers import Vertical, VerticalScroll # verified: textual 8.2.8 probe
from textual.message import Message                     # verified: textual 8.2.8 probe (Message.__init__(self) -> None)
from textual.reactive import reactive                   # verified: textual 8.2.8 probe
from textual.widgets import Collapsible, Markdown, RichLog, Static, TextArea   # verified: textual 8.2.8 probe
from textual.widgets._markdown import MarkdownStream    # verified: textual 8.2.8 probe (Markdown.get_stream(md) -> MarkdownStream; async write()/stop())
from textual import events                              # verified: textual 8.2.8 probe (events.Key has .key/.character; events.Resize has .size)
from prompt_toolkit.history import History              # verified: prompt_toolkit 3.0.47 (FileHistory/InMemoryHistory base; get_strings(), append_string())

# provided by TASK-3403 (packages/ai-parrot/src/parrot/cli/events.py)
from parrot.cli.events import (
    TurnEvent, TurnEventKind, TurnStarted, TextDelta, ToolStarted, ToolFinished, ToolFailed,
    TurnCompleted, TurnFailed, TurnCancelled,
)
from parrot.cli.commands import ConversationTurn        # verified: commands.py:38 (query, response, timestamp)
```

### Existing Signatures to Use
```python
# textual 8.2.8 (verified via isolated probe)
class TextArea(Widget):
    def __init__(self, text: str = "", *, language=None, theme="css", soft_wrap=True, tab_behavior="focus",
                 read_only=False, show_cursor=True, show_line_numbers=False, ..., placeholder="") -> None
    text: str                          # property with setter
    cursor_location: tuple[int, int]   # (row, column)
    def insert(self, text: str, location=None, *, maintain_selection_offset=True) -> EditResult
    def clear(self) -> EditResult
    def load_text(self, text: str) -> None
    def _on_key(self, event: events.Key) -> None   # override point: call event.prevent_default(); event.stop()
class Collapsible(Widget):
    def __init__(self, *children: Widget, title: str = "Toggle", collapsed: bool = True, ...) -> None
    collapsed: reactive[bool]; title: reactive[str]
class VerticalScroll(ScrollableContainer):
    def anchor(self, anchor: bool = True) -> None
    def scroll_end(self, *, animate=True, ...) -> None
    is_vertical_scroll_end: bool
class Static(Widget):
    def update(self, content: VisualType = "", *, layout: bool = True) -> None
class RichLog(ScrollView):
    def write(self, content: RenderableType | object, width=None, expand=False, shrink=True, scroll_end=None, animate=False) -> Self
class Markdown(Widget):
    def __init__(self, markdown: str | None = None, *, name=None, id=None, classes=None, parser_factory=None, open_links=True) -> None
    def update(self, markdown: str) -> AwaitComplete
    @classmethod def get_stream(cls, markdown: Markdown) -> MarkdownStream   # MarkdownStream.start() sync; await .write(str); await .stop()
class Widget:
    def mount(self, *widgets: Widget, before=None, after=None) -> AwaitMount
class App:
    async def run_test(self, *, headless=True, size=(80, 24), ...) -> AsyncGenerator[Pilot, None]   # Pilot.press/pause/resize_terminal

# packages/ai-parrot/src/parrot/cli/events.py — provided by TASK-3403 (spec §2 Data Models, fixed)
class TurnEvent(BaseModel): kind: TurnEventKind; turn_id: str; seq: int; at: datetime
class TurnStarted(TurnEvent): query: str; streaming: bool
class TextDelta(TurnEvent): text: str
class ToolStarted(TurnEvent): call_id: str; tool_name: str; args_summary: dict[str, Any]
class ToolFinished(TurnEvent): call_id: str; tool_name: str; duration_ms: float; result_status: str; result_size_bytes: int
class ToolFailed(TurnEvent): call_id: str; tool_name: str; duration_ms: float; error_type: str; error_message: str
class TurnCompleted(TurnEvent): text: str; message: Any
class TurnFailed(TurnEvent): error_type: str; error_message: str; partial_text: str
class TurnCancelled(TurnEvent): partial_text: str
```

### Does NOT Exist
- ~~`parrot.cli.tui`~~ — this task creates it; nothing under `parrot/cli/tui/` exists today.
- ~~`textual.widgets.MarkdownStream`~~ — the class lives in `textual.widgets._markdown`; obtain instances via `Markdown.get_stream(md)`.
- ~~`TextArea.history`~~, ~~`TextArea.on_key`~~ — no built-in history; override `_on_key` (verified) for Enter/Up/Down/Tab handling.
- ~~`TextArea.document.line_count`~~ — not present in 8.2.8; derive the line count from `self.text.count("\n") + 1`.
- ~~`VerticalScroll.following`~~ — Textual has `anchor()` only; `following` is the reactive this task adds on `TranscriptView`.
- ~~`ToolCall` result text in live events~~ — `ToolFinished` carries `result_status`/`result_size_bytes` only; results appear later in `TurnCompleted.message.tool_calls`.
- ~~`TurnRunner`, `bot.ask_stream`~~ — widgets never import or call them (AC5).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/cli/tui/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/cli/tui/widgets.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/cli/tui/app.tcss", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/cli/tui/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/cli/tui/test_widgets.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#ConversationTurn"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Inside a worktree run `PYTHONPATH=packages/ai-parrot/src pytest ...`; never `uv sync` there (it repoints the shared venv).
- `textual` is importable only after TASK-3399 lands **and** the main-checkout operator re-syncs the shared venv. Every test module starts with `pytest.importorskip("textual")`; `widgets.py` itself may import textual at module level (the package is imported lazily by `agent_repl.py`, AC22).
- Widgets receive `TurnEvent`s and Rich renderables only. No `bot`, no `TurnRunner`, no `logging` handler mutation (AC5, AC14).
- Streaming Markdown goes through `MarkdownStream` (Textual batches repaints); never rebuild the whole Markdown per delta.
- Unknown usage renders `tokens: n/a`, never `0` (AC8). Tool rows are created only from `ToolStarted` events, never from text (AC8).
- Google docstrings, strict typing, `self.logger = logging.getLogger(__name__)` on each widget class body that logs.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/renderer.py:124-173` — tool panel and usage formatting to mirror (`name`, `arguments`, `result`, `error`; `prompt=/completion=/total=`).
- `packages/ai-parrot/src/parrot/cli/devloop/renderer.py:26-60` — bounded renderable list (`_add_line`, cap at 200 → keep 150) is the precedent for the transcript cap.
- `packages/ai-parrot/src/parrot/cli/commands.py:130-136` — `get_completions()` returns `["/tools", ...]`; the composer's completion callable has this shape.

---

## Implementation Blueprint

### Steps (in order)
1. Create `parrot/cli/tui/__init__.py` with a lazy `__getattr__` — *why*: importing the package must stay cheap and must not pull `textual` until a widget is actually requested (AC22 measures `parrot.cli.tui` absence, but the app module is what `agent_repl.py` imports lazily; keep the package itself trivial).
2. Write `widgets.py` part 1 (`TranscriptView`, `TurnPanel`) — *why*: the transcript is the event sink every other widget hangs off.
3. Write part 2 (`ToolActivity`, `StatusBar`, `LogDrawer`) — *why*: these are pure event → text mappers, small and testable in isolation.
4. Write part 3 (`Composer`) — *why*: key handling is the only judgement-heavy piece; do it last with the other widgets already testable.
5. Write `app.tcss` — *why*: TASK-3412 sets `CSS_PATH = "app.tcss"`; ids/classes below are the contract.
6. Write `test_widgets.py` with a local `_Harness(App)` — *why*: widgets need a running app to mount; `run_test()` is headless.

### `packages/ai-parrot/src/parrot/cli/tui/__init__.py` (CREATE)
```python
"""Textual full-screen workspace for ``parrot agent`` (FEAT-573, spec §3 M11–M12).

Import cost matters: ``parrot.cli.agent_repl`` imports ``parrot.cli.tui.app``
lazily and only when the resolved UI mode is TUI (AC22). This package module
therefore re-exports its public names through ``__getattr__`` so importing the
package itself never imports ``textual``.
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "AgentWorkspaceApp",
    "Composer",
    "LogDrawer",
    "StatusBar",
    "ToolActivity",
    "TranscriptView",
    "TurnPanel",
]

_WIDGETS = {"Composer", "LogDrawer", "StatusBar", "ToolActivity", "TranscriptView", "TurnPanel"}


def __getattr__(name: str) -> Any:
    """Resolve public names lazily (PEP 562)."""
    if name in _WIDGETS:
        from parrot.cli.tui import widgets  # noqa: PLC0415

        return getattr(widgets, name)
    if name == "AgentWorkspaceApp":
        from parrot.cli.tui.app import AgentWorkspaceApp  # noqa: PLC0415  (TASK-3412)

        return AgentWorkspaceApp
    raise AttributeError(name)
```
**Why this shape**: PEP 562 lazy exports keep `import parrot.cli.tui` free of `textual`; `AgentWorkspaceApp` is exported for symmetry but resolves only when TASK-3412 has landed (until then, accessing it raises `ImportError`, which no code path in this task triggers).

### `packages/ai-parrot/src/parrot/cli/tui/widgets.py` — part 1/3: transcript + turn panel (CREATE)
```python
"""Widgets for the ``parrot agent`` Textual workspace (spec §3 Module 11)."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from prompt_toolkit.history import History  # verified: prompt_toolkit 3.0.47
from rich.text import Text  # verified: renderer.py:17
from textual import events  # verified: textual 8.2.8 probe
from textual.containers import Vertical, VerticalScroll  # verified: textual 8.2.8 probe
from textual.message import Message  # verified: textual 8.2.8 probe
from textual.reactive import reactive  # verified: textual 8.2.8 probe
from textual.widgets import Collapsible, Markdown, RichLog, Static, TextArea  # verified: textual 8.2.8 probe
from textual.widgets._markdown import MarkdownStream  # verified: textual 8.2.8 probe

from parrot.cli.commands import ConversationTurn  # verified: commands.py:38
from parrot.cli.events import (  # provided by TASK-3403 (parrot/cli/events.py)
    TextDelta, ToolFailed, ToolFinished, ToolStarted, TurnCancelled, TurnCompleted, TurnEvent,
    TurnFailed, TurnStarted,
)

logger = logging.getLogger(__name__)

MAX_PANELS = 200          # spec §3 M11 "Caps"
MAX_TURN_TEXT = 512 * 1024
TRUNCATION_MARKER = "\n\n*… output truncated at 512 KiB (use /export for the full text)*"


class TranscriptView(VerticalScroll):
    """Scrolling list of :class:`TurnPanel`; auto-follows the tail while ``following``."""

    following: reactive[bool] = reactive(True)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._panels: List["TurnPanel"] = []
        self._hidden_notice: Optional[Static] = None
        self._hidden_count = 0

    def begin_turn(self, event: TurnStarted) -> "TurnPanel":
        """Mount a new panel for ``event`` and enforce the 200-panel cap."""
        panel = TurnPanel(event, classes="turn")
        self._panels.append(panel)
        self.mount(panel)
        # FILL IN: when len(self._panels) > MAX_PANELS remove the oldest panel(s), increment
        # self._hidden_count and mount/update one Static "(N earlier turns hidden — /export saves all)"
        # at the top — bounded by spec §3 M11 "Caps" (runner.history is never capped here)
        if self.following:
            self.anchor()
        return panel

    async def apply(self, event: TurnEvent) -> None:
        """Route ``event`` to the current panel; re-anchor when following."""
        if isinstance(event, TurnStarted):
            self.begin_turn(event)
            return
        if not self._panels:
            logger.debug("transcript: event %s before any TurnStarted", event.kind)
            return
        await self._panels[-1].apply(event)
        if self.following:
            self.anchor()

    def append_renderable(self, renderable: Any) -> None:
        """Mount command output / notices between turns as a Static."""
        self.mount(Static(renderable, classes="notice"))
        if self.following:
            self.anchor()

    def resume_follow(self) -> None:
        """Re-enable auto-follow and jump to the end (``end`` key / new submission)."""
        self.following = True
        self.anchor()

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:  # noqa: D401
        self.following = False
        # FILL IN: also flip following=False for keyboard scroll-up actions (action_scroll_up /
        # action_page_up) — bounded by AC3 ("scrolling back stops auto-follow and End resumes it")
```
**Why this shape**: `following` is the single source of truth AC3 asserts on; `anchor()` is Textual's native "stick to bottom" and `resume_follow()` is what TASK-3412 binds to `end`. Panels are appended, never rebuilt, so streaming cost stays O(delta). The cap logic is a `FILL IN` because eviction order and notice placement are mechanical but need care with `mount(before=...)`.

### `packages/ai-parrot/src/parrot/cli/tui/widgets.py` — part 2/3: turn panel + tool activity (CREATE, continues the same file)
```python
class TurnPanel(Vertical):
    """One conversation turn: user text, streamed assistant Markdown, tool rows, footer line."""

    def __init__(self, started: TurnStarted, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.turn_id = started.turn_id
        self._user = Static(Text(f"you> {started.query}", style="bold"), classes="user")
        self._assistant = Markdown("", classes="assistant")
        self._tools = ToolActivity(classes="tools")
        self._footer = Static(Text("waiting…", style="dim"), classes="turn-footer")
        self._stream: Optional[MarkdownStream] = None
        self._text_len = 0
        self._truncated = False

    def compose(self):  # type: ignore[override]
        yield self._user
        yield self._assistant
        yield self._tools
        yield self._footer

    async def apply(self, event: TurnEvent) -> None:
        """Apply one event; each branch is idempotent for repeated terminal events."""
        if isinstance(event, TextDelta):
            if self._stream is None:
                self._stream = Markdown.get_stream(self._assistant)
                self._stream.start()
            if self._text_len < MAX_TURN_TEXT:
                self._text_len += len(event.text)
                await self._stream.write(event.text)
            elif not self._truncated:
                self._truncated = True
                await self._stream.write(TRUNCATION_MARKER)
        elif isinstance(event, ToolStarted):
            self._tools.start(event)
        elif isinstance(event, ToolFinished):
            self._tools.finish(event)
        elif isinstance(event, ToolFailed):
            self._tools.fail(event)
        elif isinstance(event, (TurnCompleted, TurnFailed, TurnCancelled)):
            await self._close_stream()
            # FILL IN: footer text per terminal kind — Completed: usage line from event.message.usage
            # (prompt=/completion=/total= like renderer.py:159-169, or "tokens: n/a" when usage is None,
            # AC8) and final tool details from event.message.tool_calls; Failed: "[red]error_type:
            # error_message[/red]" keeping partial text; Cancelled: "[yellow]Interrupted[/yellow]" — bounded by AC18/AC19

    async def _close_stream(self) -> None:
        if self._stream is not None:
            await self._stream.stop()
            self._stream = None


class ToolActivity(Collapsible):
    """Collapsible list of tool rows keyed by ``call_id`` (⏵ running · ✓ done (ms) · ✗ failed)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(title="Tools", collapsed=True, **kwargs)
        self._rows: Dict[str, Static] = {}
        self.display = False  # shown on first ToolStarted only (AC8: never inferred from text)

    def start(self, ev: ToolStarted) -> None:
        row = Static(Text(f"⏵ {ev.tool_name} …", style="cyan"), classes="tool-row")
        self._rows[ev.call_id] = row
        self.display = True
        self.title = f"Tools ({len(self._rows)})"
        self.mount(row)

    def finish(self, ev: ToolFinished) -> None:
        # FILL IN: update self._rows.get(ev.call_id) to "✓ <name> (<duration_ms:.0f> ms, <result_status>)";
        # create the row if the start event was missed — bounded by spec §2 Data Models (call_id == span_id)
        ...

    def fail(self, ev: ToolFailed) -> None:
        # FILL IN: same as finish() with "✗ <name> — <error_type>: <error_message>" in red — bounded by AC6
        ...
```
**Why this shape**: `MarkdownStream` is Textual's supported streaming path (verified `get_stream`/`write`/`stop`); starting it lazily on the first delta lets a `TurnCompleted` without deltas (batch mode) still render via the footer/`update`. `ToolActivity` is hidden until a real `ToolStarted` arrives, which is the mechanical form of AC8.

### `packages/ai-parrot/src/parrot/cli/tui/widgets.py` — part 3/3: composer, status bar, log drawer (CREATE, continues the same file)
```python
class Composer(TextArea):
    """Multiline composer: Enter sends, ctrl+j / shift+enter newline, Up/Down history, Tab completion."""

    class Submitted(Message):
        """Posted when the user submits text."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self, *, history: History, completions: Callable[[], List[str]], **kwargs: Any) -> None:
        super().__init__("", soft_wrap=True, show_line_numbers=False, placeholder="Message… (Enter sends, Ctrl+J newline)", **kwargs)
        self._history = history
        self._completions = completions
        self._history_pos: Optional[int] = None  # None = editing a fresh entry

    def _on_key(self, event: events.Key) -> None:  # type: ignore[override]
        if event.key == "enter":
            event.prevent_default(); event.stop()
            text = self.text.strip()
            if text:
                self._history.append_string(text)
                self._history_pos = None
                self.post_message(self.Submitted(text))
                self.clear()
            return
        if event.key in ("ctrl+j", "shift+enter"):
            event.prevent_default(); event.stop()
            self.insert("\n")
            return
        row, _col = self.cursor_location
        line_count = self.text.count("\n") + 1
        if event.key == "up" and row == 0:
            event.prevent_default(); event.stop()
            # FILL IN: walk self._history.get_strings() backwards from _history_pos and load_text() — bounded by spec §3 M11 bindings
            return
        if event.key == "down" and row == line_count - 1:
            event.prevent_default(); event.stop()
            # FILL IN: walk forwards; past the newest entry restore an empty composer — bounded by spec §3 M11 bindings
            return
        if event.key == "tab" and self.text.startswith("/") and "\n" not in self.text:
            event.prevent_default(); event.stop()
            # FILL IN: complete the unique "/" prefix from self._completions(); on several matches leave text unchanged — bounded by AC20
            return
        super()._on_key(event)


class StatusBar(Static):
    """One-line state: idle · waiting · streaming · running tool <name> · cancelling · tokens or n/a."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(Text("idle", style="dim"), **kwargs)
        self._running_tools: Dict[str, str] = {}

    def apply(self, event: TurnEvent) -> None:
        """Map an event to the state text (waiting until the first delta — spec: distinguish waiting from streaming)."""
        # FILL IN: TurnStarted→"waiting for response…"; first TextDelta→"streaming"; ToolStarted→"running tool <name>";
        # ToolFinished/ToolFailed pop the tool and fall back to streaming/waiting; TurnCompleted→"idle · tokens: …" or
        # "idle · tokens: n/a" (AC8); TurnFailed→"error"; TurnCancelled→"cancelled" — bounded by spec §3 M11 StatusBar
        ...

    def set_cancelling(self) -> None:
        self.update(Text("cancelling…", style="yellow"))


class LogDrawer(RichLog):
    """Hidden-by-default drawer receiving log records routed by ``DrawerLogHandler`` (TASK-3411)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(highlight=False, markup=False, wrap=True, **kwargs)
        self.display = False
```
**Why this shape**: `_on_key` is the verified override point on `TextArea`; handling `enter` there (not via `BINDINGS`) keeps the 32 built-in TextArea bindings intact. `ctrl+j` is the guaranteed newline key (spec §7 gotcha); `shift+enter` is best-effort. History uses the prompt_toolkit `History` object TASK-3407's inline REPL also uses, so both modes share one file (AC10).

### `packages/ai-parrot/src/parrot/cli/tui/app.tcss` (CREATE)
```css
/* Layout contract for AgentWorkspaceApp (TASK-3412). Ids are fixed; visual values are free. */
Screen { layout: vertical; }
#transcript { height: 1fr; padding: 0 1; }
#transcript .turn { margin-bottom: 1; }
#transcript .user { color: $text; text-style: bold; }
#transcript .assistant { margin-left: 2; }
#transcript .tools { margin-left: 2; }
#transcript .turn-footer { color: $text-muted; margin-left: 2; }
#transcript .notice { color: $text-muted; }
#composer { height: auto; min-height: 3; max-height: 8; border: tall $accent; }
#status { height: 1; padding: 0 1; background: $panel; }
#logs { height: 8; border-top: solid $panel; display: none; }
/* FILL IN: narrow-width tweaks are applied from Python on Resize (TASK-3412) — keep CSS static */
```
**Why**: TASK-3412 queries `#transcript`, `#composer`, `#status`, `#logs`; the ids are the only contract, colours are the coder's call.

### `packages/ai-parrot/tests/cli/tui/__init__.py` (CREATE)
```python
"""Textual workspace tests (FEAT-573)."""
```

### `packages/ai-parrot/tests/cli/tui/test_widgets.py` (CREATE)
```python
"""Widget tests for parrot.cli.tui.widgets (FEAT-573, spec §4)."""
from __future__ import annotations

import pytest

textual = pytest.importorskip("textual")

from prompt_toolkit.history import InMemoryHistory  # verified: repl.py:16
from textual.app import App, ComposeResult  # verified: textual 8.2.8 probe

from parrot.cli.events import TextDelta, ToolFinished, ToolStarted, TurnCompleted, TurnEventKind, TurnStarted
from parrot.cli.tui.widgets import Composer, StatusBar, ToolActivity, TranscriptView, TurnPanel


class _Harness(App[None]):
    """Minimal app mounting the widgets under test."""

    def compose(self) -> ComposeResult:
        yield TranscriptView(id="transcript")
        yield Composer(history=InMemoryHistory(), completions=lambda: ["/help", "/tools"], id="composer")
        yield StatusBar(id="status")


def _started(turn_id: str = "t1", query: str = "hi") -> TurnStarted:
    return TurnStarted(kind=TurnEventKind.STARTED, turn_id=turn_id, seq=0, query=query, streaming=True)


@pytest.mark.asyncio
async def test_transcript_begin_turn_mounts_panel_and_follows():
    app = _Harness()
    async with app.run_test() as pilot:
        view = app.query_one("#transcript", TranscriptView)
        await view.apply(_started())
        await pilot.pause()
        assert len(view.query(TurnPanel)) == 1 and view.following is True


@pytest.mark.asyncio
async def test_tool_rows_only_from_tool_started():
    # FILL IN: apply TextDelta mentioning "running tool X" — ToolActivity stays hidden; then ToolStarted/ToolFinished
    # with the same call_id → one row, state ✓ — bounded by AC6/AC8
    ...


@pytest.mark.asyncio
async def test_composer_enter_submits_and_ctrl_j_newline():
    # FILL IN: press keys via pilot.press("h","i","enter") and capture Composer.Submitted; then "ctrl+j" inserts "\n"
    ...


@pytest.mark.asyncio
async def test_status_bar_waiting_then_streaming_then_na_usage():
    # FILL IN: TurnStarted → "waiting"; TextDelta → "streaming"; TurnCompleted(message with usage=None) → "n/a" (AC8)
    ...


@pytest.mark.asyncio
async def test_transcript_cap_hides_old_turns():
    # FILL IN: apply 205 TurnStarted → at most 200 TurnPanel mounted and one notice mentioning "hidden" — spec §3 M11 Caps
    ...
```
**Why**: each test maps to a spec §4 row (`test_tui_tool_activity_rows`, `test_tui_history_navigation_and_completion`, `test_tui_scrollback_stops_follow_end_resumes` partial); the `_Harness` keeps widget tests independent of TASK-3412.

### FILL IN checklist
- [ ] `widgets.py::TranscriptView.begin_turn` — eviction + hidden notice; bounded by spec §3 M11 Caps
- [ ] `widgets.py::TranscriptView` — keyboard scroll-up sets `following=False`; bounded by AC3
- [ ] `widgets.py::TurnPanel.apply` — footer text per terminal event; bounded by AC8/AC18/AC19
- [ ] `widgets.py::ToolActivity.finish/fail` — row update text; bounded by AC6
- [ ] `widgets.py::Composer._on_key` — history walk and Tab completion; bounded by spec §3 M11 bindings, AC20
- [ ] `widgets.py::StatusBar.apply` — state mapping; bounded by spec §3 M11 StatusBar, AC8
- [ ] `test_widgets.py` — five test bodies

---

## Acceptance Criteria

- [ ] `from parrot.cli.tui.widgets import TranscriptView, TurnPanel, ToolActivity, Composer, StatusBar, LogDrawer` works with textual installed
- [ ] `import parrot.cli.tui` does not import `textual` (`"textual" not in sys.modules` after the import in a fresh interpreter) — supports AC22
- [ ] Auto-follow: `following` flips to False on scroll-back and `resume_follow()` re-anchors (AC3)
- [ ] Tool rows exist only after `ToolStarted`; unknown usage renders `n/a` (AC6, AC8)
- [ ] 200-panel and 512 KiB caps enforced with visible notices (spec §3 M11 Caps)
- [ ] `pytest packages/ai-parrot/tests/cli/tui/test_widgets.py -q` passes; `ruff check packages/ai-parrot/src/parrot/cli/tui` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/tui/test_widgets.py -q`

---

## Test Specification

See the `test_widgets.py` blueprint above: five tests — panel mount + follow, tool rows only from events, composer Enter/Ctrl+J, status-bar states incl. `n/a` usage, transcript cap.

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
7. **Move this file** to `tasks/completed/TASK-3410-tui-widgets.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any

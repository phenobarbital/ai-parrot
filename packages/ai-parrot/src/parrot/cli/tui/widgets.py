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

from parrot.cli.events import (  # provided by TASK-3403 (parrot/cli/events.py)
    TextDelta,
    ToolFailed,
    ToolFinished,
    ToolStarted,
    TurnCancelled,
    TurnCompleted,
    TurnEvent,
    TurnFailed,
    TurnStarted,
)

logger = logging.getLogger(__name__)

MAX_PANELS = 200  # spec §3 M11 "Caps"
MAX_TURN_TEXT = 512 * 1024
TRUNCATION_MARKER = "\n\n*… output truncated at 512 KiB (use /export for the full text)*"


def _format_usage_text(usage: Any) -> str:
    """Format a usage line like ``renderer.py:135-147``; ``tokens: n/a`` when unknown (AC8).

    Args:
        usage: A ``CompletionUsage``-shaped object (duck-typed) or ``None``.

    Returns:
        A short ``"tokens: prompt=…, completion=…, total=…"`` string, or
        ``"tokens: n/a"`` when nothing usable is present.
    """
    if usage is None:
        return "tokens: n/a"
    parts: List[str] = []
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    total_tokens = getattr(usage, "total_tokens", None)
    if prompt_tokens:
        parts.append(f"prompt={prompt_tokens}")
    if completion_tokens:
        parts.append(f"completion={completion_tokens}")
    if total_tokens:
        parts.append(f"total={total_tokens}")
    if not parts:
        return "tokens: n/a"
    return f"tokens: {', '.join(parts)}"


class TranscriptView(VerticalScroll):
    """Scrolling list of :class:`TurnPanel`; auto-follows the tail while ``following``."""

    following: reactive[bool] = reactive(True)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._panels: List["TurnPanel"] = []
        self._hidden_notice: Optional[Static] = None
        self._hidden_notice_text: str = ""
        self._hidden_count = 0

    def begin_turn(self, event: TurnStarted) -> "TurnPanel":
        """Mount a new panel for ``event`` and enforce the 200-panel cap."""
        panel = TurnPanel(event, classes="turn")
        self._panels.append(panel)
        self.mount(panel)
        if len(self._panels) > MAX_PANELS:
            evicted = self._panels.pop(0)
            evicted.remove()
            self._hidden_count += 1
            self._hidden_notice_text = f"({self._hidden_count} earlier turns hidden — /export saves all)"
            if self._hidden_notice is None:
                self._hidden_notice = Static(self._hidden_notice_text, classes="notice")
                before = self._panels[0] if self._panels else None
                self.mount(self._hidden_notice, before=before)
            else:
                self._hidden_notice.update(self._hidden_notice_text)
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

    def action_scroll_up(self) -> None:
        """Keyboard scroll-up (Up arrow) also disengages auto-follow (AC3)."""
        self.following = False
        super().action_scroll_up()

    def action_page_up(self) -> None:
        """Keyboard page-up also disengages auto-follow (AC3)."""
        self.following = False
        super().action_page_up()


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
            if isinstance(event, TurnCompleted):
                usage = getattr(event.message, "usage", None)
                self._footer.update(Text(_format_usage_text(usage), style="dim"))
                tool_calls = getattr(event.message, "tool_calls", None) or []
                if tool_calls:
                    self._tools.finalize(tool_calls)
            elif isinstance(event, TurnFailed):
                self._footer.update(Text(f"{event.error_type}: {event.error_message}", style="bold red"))
            else:
                self._footer.update(Text("Interrupted", style="yellow"))

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
        """Update the row for ``ev.call_id`` to a "done" state, creating it if the start event was missed."""
        text = Text(f"✓ {ev.tool_name} ({ev.duration_ms:.0f} ms, {ev.result_status})", style="green")
        row = self._rows.get(ev.call_id)
        if row is None:
            row = Static(text, classes="tool-row")
            self._rows[ev.call_id] = row
            self.display = True
            self.mount(row)
        else:
            row.update(text)
        self.title = f"Tools ({len(self._rows)})"

    def fail(self, ev: ToolFailed) -> None:
        """Update the row for ``ev.call_id`` to a "failed" state, creating it if the start event was missed."""
        text = Text(f"✗ {ev.tool_name} — {ev.error_type}: {ev.error_message}", style="red")
        row = self._rows.get(ev.call_id)
        if row is None:
            row = Static(text, classes="tool-row")
            self._rows[ev.call_id] = row
            self.display = True
            self.mount(row)
        else:
            row.update(text)
        self.title = f"Tools ({len(self._rows)})"

    def finalize(self, tool_calls: List[Any]) -> None:
        """Enrich existing rows with the final result/error from ``TurnCompleted.message.tool_calls``.

        Only updates rows that already exist (matched by ``call_id == ToolCall.id``, spec §2 Data
        Models); never creates a row from this data (AC8: tool rows come only from ``ToolStarted``).
        """
        for tool_call in tool_calls:
            call_id = getattr(tool_call, "id", None)
            row = self._rows.get(call_id) if call_id else None
            if row is None:
                continue
            name = getattr(tool_call, "name", call_id)
            error = getattr(tool_call, "error", None)
            if error:
                row.update(Text(f"✗ {name} — {error}", style="red"))
            elif getattr(tool_call, "result", None) is not None:
                row.update(Text(f"✓ {name} — {tool_call.result}", style="green"))


class Composer(TextArea):
    """Multiline composer: Enter sends, ctrl+j / shift+enter newline, Up/Down history, Tab completion."""

    class Submitted(Message):
        """Posted when the user submits text."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self, *, history: History, completions: Callable[[], List[str]], **kwargs: Any) -> None:
        super().__init__(
            "", soft_wrap=True, show_line_numbers=False, placeholder="Message… (Enter sends, Ctrl+J newline)", **kwargs
        )
        self._history = history
        self._completions = completions
        self._history_pos: Optional[int] = None  # None = editing a fresh entry

    def _on_key(self, event: events.Key) -> None:  # type: ignore[override]
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            text = self.text.strip()
            if text:
                self._history.append_string(text)
                self._history_pos = None
                self.post_message(self.Submitted(text))
                self.clear()
            return
        if event.key in ("ctrl+j", "shift+enter"):
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        row, _col = self.cursor_location
        line_count = self.text.count("\n") + 1
        if event.key == "up" and row == 0:
            event.prevent_default()
            event.stop()
            entries = self._history.get_strings()
            if entries:
                if self._history_pos is None:
                    self._history_pos = len(entries) - 1
                else:
                    self._history_pos = max(0, self._history_pos - 1)
                self.load_text(entries[self._history_pos])
            return
        if event.key == "down" and row == line_count - 1:
            event.prevent_default()
            event.stop()
            if self._history_pos is not None:
                entries = self._history.get_strings()
                self._history_pos += 1
                if self._history_pos >= len(entries):
                    self._history_pos = None
                    self.clear()
                else:
                    self.load_text(entries[self._history_pos])
            return
        if event.key == "tab" and self.text.startswith("/") and "\n" not in self.text:
            event.prevent_default()
            event.stop()
            prefix = self.text
            matches = [candidate for candidate in self._completions() if candidate.startswith(prefix)]
            if len(matches) == 1:
                self.load_text(matches[0])
            return
        super()._on_key(event)


class StatusBar(Static):
    """One-line state: idle · waiting · streaming · running tool <name> · cancelling · tokens or n/a."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(Text("idle", style="dim"), **kwargs)
        self._running_tools: Dict[str, str] = {}
        self._streaming = False

    def apply(self, event: TurnEvent) -> None:
        """Map an event to the state text (waiting until the first delta — spec: distinguish waiting from streaming)."""
        if isinstance(event, TurnStarted):
            self._streaming = False
            self._running_tools.clear()
            self.update(Text("waiting for response…", style="dim"))
            return
        if isinstance(event, TextDelta):
            self._streaming = True
            if not self._running_tools:
                self.update(Text("streaming", style="green"))
            return
        if isinstance(event, ToolStarted):
            self._running_tools[event.call_id] = event.tool_name
            self.update(Text(f"running tool {event.tool_name}", style="cyan"))
            return
        if isinstance(event, (ToolFinished, ToolFailed)):
            self._running_tools.pop(event.call_id, None)
            if self._running_tools:
                remaining = next(reversed(list(self._running_tools.values())))
                self.update(Text(f"running tool {remaining}", style="cyan"))
            elif self._streaming:
                self.update(Text("streaming", style="green"))
            else:
                self.update(Text("waiting for response…", style="dim"))
            return
        if isinstance(event, TurnCompleted):
            usage = getattr(event.message, "usage", None)
            self.update(Text(f"idle · {_format_usage_text(usage)}", style="dim"))
            return
        if isinstance(event, TurnFailed):
            self.update(Text("error", style="bold red"))
            return
        if isinstance(event, TurnCancelled):
            self.update(Text("cancelled", style="yellow"))
            return

    def set_cancelling(self) -> None:
        self.update(Text("cancelling…", style="yellow"))


class LogDrawer(RichLog):
    """Hidden-by-default drawer receiving log records routed by ``DrawerLogHandler`` (TASK-3411)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(highlight=False, markup=False, wrap=True, **kwargs)
        self.display = False

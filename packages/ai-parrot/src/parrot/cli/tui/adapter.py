"""TUI adapters: renderer, command context and log handler (spec §3 Module 12)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import traceback
from typing import TYPE_CHECKING, Any, Iterator, List, Optional

from rich.markdown import Markdown as RichMarkdown  # verified: renderer.py:14
from rich.panel import Panel  # verified: renderer.py:15
from rich.table import Table  # verified: renderer.py:16
from rich.text import Text  # verified: renderer.py:17

from parrot.cli.commands import ConversationTurn, SlashCommandDispatcher  # verified: commands.py:38, :70
from parrot.cli.repl import REPLConfig  # verified: repl.py:61
from parrot.cli.session import TurnRunner  # provided by TASK-3404
from parrot.cli.tui.widgets import LogDrawer, TranscriptView  # provided by TASK-3410

if TYPE_CHECKING:
    from textual.app import App  # verified: textual 8.2.8 probe

logger = logging.getLogger(__name__)


def _format_usage_line(usage: Any) -> str:
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
    if getattr(usage, "prompt_tokens", None):
        parts.append(f"prompt={usage.prompt_tokens}")
    if getattr(usage, "completion_tokens", None):
        parts.append(f"completion={usage.completion_tokens}")
    if getattr(usage, "total_tokens", None):
        parts.append(f"total={usage.total_tokens}")
    if not parts:
        return "tokens: n/a"
    return f"tokens: {', '.join(parts)}"


class TUIRenderer:
    """``RendererProtocol`` implementation that appends renderables to the transcript."""

    def __init__(self, transcript: TranscriptView) -> None:
        self._transcript = transcript
        self.logger = logging.getLogger(__name__)

    def print(self, *args: Any, **kwargs: Any) -> None:  # noqa: A003 — protocol name
        """Rich-markup strings become ``Text``; other renderables pass through."""
        if len(args) == 1 and not isinstance(args[0], str):
            self._transcript.append_renderable(args[0])
            return
        self._transcript.append_renderable(Text.from_markup(" ".join(str(a) for a in args)))

    def render(self, response: Any) -> None:
        """Mirror ``ResponseRenderer.render`` (renderer.py:89-122): output, tool panels, usage."""
        output = getattr(response, "output", None)
        if output is None:
            output = getattr(response, "response", None) or ""

        if isinstance(output, str) and output.strip():
            self._transcript.append_renderable(RichMarkdown(output))
        elif isinstance(output, (dict, list)):
            try:
                formatted = json.dumps(output, indent=2, default=str)
                self._transcript.append_renderable(RichMarkdown(f"```json\n{formatted}\n```"))
            except (TypeError, ValueError):
                self._transcript.append_renderable(Text(str(output)))
        elif output is not None:
            self._transcript.append_renderable(Text(str(output)))

        tool_calls = getattr(response, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                try:
                    args_json = json.dumps(tc.arguments, indent=2, default=str)
                except (TypeError, AttributeError):
                    args_json = str(getattr(tc, "arguments", tc))
                tool_name = getattr(tc, "name", "unknown")
                panel_content = Text()
                panel_content.append("Arguments:\n", style="bold yellow")
                panel_content.append(args_json)
                if getattr(tc, "result", None) is not None:
                    panel_content.append("\n\nResult:\n", style="bold green")
                    panel_content.append(str(tc.result))
                if getattr(tc, "error", None):
                    panel_content.append("\n\nError:\n", style="bold red")
                    panel_content.append(str(tc.error))
                self._transcript.append_renderable(
                    Panel(panel_content, title=f"[bold cyan]Tool: {tool_name}[/bold cyan]", border_style="cyan")
                )

        usage = getattr(response, "usage", None)
        self._transcript.append_renderable(Text(_format_usage_line(usage), style="dim"))

    def render_error(self, error: Exception) -> None:
        content = Text()
        content.append(f"{type(error).__name__}: ", style="bold red")
        content.append(str(error))
        tb = traceback.format_exc()
        if tb and "NoneType" not in tb:
            content.append(f"\n\n{tb}", style="dim red")
        self._transcript.append_renderable(Panel(content, title="[bold red]Error[/bold red]", border_style="red"))

    def render_table(self, headers: List[str], rows: List[List[str]], title: Optional[str] = None) -> None:
        table = Table(title=title, show_header=True, header_style="bold magenta")
        for header in headers:
            table.add_column(header)
        for row in rows:
            table.add_row(*[str(cell) for cell in row])
        self._transcript.append_renderable(table)

    def render_info(self, lines: List[tuple[str, str]]) -> None:
        text = Text()
        for key, value in lines:
            text.append(f"{key}: ", style="bold cyan")
            text.append(f"{value}\n")
        self._transcript.append_renderable(Panel(text, title="[bold]Agent Info[/bold]", border_style="blue"))

    def render_history(self, turns: List[ConversationTurn], *, session_id: str) -> None:
        """Resumed transcript header + one user/assistant pair per turn (spec §3 M6 render_history shape)."""
        self._transcript.append_renderable(Text(f"Resumed session {session_id} ({len(turns)} turns)", style="bold"))
        for turn in turns:
            self._transcript.append_renderable(Text(f"you> {turn.query}", style="bold cyan"))
            if turn.response is not None:
                output = getattr(turn.response, "output", None) or ""
                self._transcript.append_renderable(RichMarkdown(output))


class TUICommandContext:
    """``CommandContext`` implementation for the workspace app."""

    def __init__(
        self,
        app: "App[Any]",
        bot: Any,
        config: REPLConfig,
        runner: TurnRunner,
        dispatcher: SlashCommandDispatcher,
        renderer: TUIRenderer,
    ) -> None:
        self.app = app
        self.bot = bot
        self.config = config
        self.runner = runner
        self.dispatcher = dispatcher
        self.renderer = renderer

    @property
    def history(self) -> List[ConversationTurn]:
        """Display/export history is owned by the runner (spec §3 M5)."""
        return self.runner.history

    @contextlib.contextmanager
    def suspend(self) -> Iterator[None]:
        """Release the terminal to a foreign prompt (HITL, device code), then redraw."""
        with self.app.suspend():
            yield


class DrawerLogHandler(logging.Handler):
    """Route log records into the ``LogDrawer`` without touching other handlers' levels (AC14)."""

    def __init__(self, app: "App[Any]", drawer: LogDrawer) -> None:
        super().__init__()
        self._app = app
        self._drawer = drawer
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None and loop is getattr(self._app, "_loop", loop):
                self._drawer.write(line)
            else:
                self._app.call_from_thread(self._drawer.write, line)
        except Exception:  # noqa: BLE001 — logging handlers must never raise
            self.handleError(record)

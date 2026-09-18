"""Response renderer for AI-Parrot CLI agent REPL.

Renders ``AIMessage`` objects to the terminal using Rich for markdown,
code blocks, tool call panels, usage stats, and streaming live display.
"""

import json
import logging
import traceback
from typing import Any, List, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from parrot.models.responses import AIMessage
from parrot.cli.commands import ConversationTurn
from parrot.cli.console import LiveRegion, get_console
from parrot.cli.events import (
    TextDelta,
    ToolFailed,
    ToolFinished,
    ToolStarted,
    TurnCancelled,
    TurnCompleted,
    TurnEvent,
    TurnFailed,
)


class ResponseRenderer:
    """Renders AIMessage responses to the terminal via Rich.

    Supports both batch mode (full response rendered at once) and streaming
    mode (incremental Markdown repaints inside a shared ``LiveRegion``).

    Attributes:
        console: Rich Console instance used for all output.
    """

    def __init__(self, console: Optional[Console] = None, region: Optional[LiveRegion] = None) -> None:
        """Initialise the renderer.

        Args:
            console: Rich console; defaults to the process-wide ``get_console()``.
            region: Live region for streaming; created lazily from ``self.console`` when omitted,
                so a console swapped in after construction (tests) is honoured.
        """
        self.logger = logging.getLogger(__name__)
        self.console: Console = console or get_console()
        self._region: Optional[LiveRegion] = region
        self._stream_buffer: str = ""

    @property
    def region(self) -> LiveRegion:
        """The streaming region, built on first access from ``self.console``."""
        if self._region is None:
            self._region = LiveRegion(self.console)
        return self._region

    # ------------------------------------------------------------------
    # Batch rendering
    # ------------------------------------------------------------------

    def render(self, response: AIMessage) -> None:
        """Render a complete AIMessage to the terminal.

        Displays the response output as Markdown, tool calls in panels,
        and token usage stats if available.

        Args:
            response: The AIMessage to render.
        """
        output = response.output
        if output is None:
            output = response.response or ""

        # Render main output as Markdown
        if isinstance(output, str) and output.strip():
            self.console.print(Markdown(output))
        elif isinstance(output, (dict, list)):
            try:
                formatted = json.dumps(output, indent=2, default=str)
                self.console.print(Markdown(f"```json\n{formatted}\n```"))
            except (TypeError, ValueError):
                self.console.print(str(output))
        elif output is not None:
            self.console.print(str(output))

        # Render tool calls
        if response.tool_calls:
            self._render_tool_calls(response.tool_calls)

        # Render usage stats
        if response.usage and (response.usage.prompt_tokens or response.usage.completion_tokens):
            self._render_usage(response.usage)

    def _render_tool_calls(self, tool_calls: List[Any]) -> None:
        """Render tool calls in Rich panels.

        Args:
            tool_calls: List of ToolCall objects to display.
        """
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
            self.console.print(
                Panel(
                    panel_content,
                    title=f"[bold cyan]Tool: {tool_name}[/bold cyan]",
                    border_style="cyan",
                )
            )

    def _render_usage(self, usage: Any) -> None:
        """Render token usage statistics.

        Args:
            usage: CompletionUsage object with token counts.
        """
        parts: list[str] = []
        if usage.prompt_tokens:
            parts.append(f"prompt={usage.prompt_tokens}")
        if usage.completion_tokens:
            parts.append(f"completion={usage.completion_tokens}")
        if usage.total_tokens:
            parts.append(f"total={usage.total_tokens}")
        if usage.total_time is not None:
            parts.append(f"time={usage.total_time:.2f}s")
        if usage.estimated_cost is not None:
            parts.append(f"cost=${usage.estimated_cost:.6f}")
        if parts:
            self.console.print(f"[dim]tokens: {', '.join(parts)}[/dim]")

    def render_error(self, error: Exception) -> None:
        """Render an exception in a styled Rich panel.

        Args:
            error: The exception to display.
        """
        tb = traceback.format_exc()
        content = Text()
        content.append(f"{type(error).__name__}: ", style="bold red")
        content.append(str(error))
        if tb and "NoneType" not in tb:
            content.append(f"\n\n{tb}", style="dim red")
        self.console.print(
            Panel(
                content,
                title="[bold red]Error[/bold red]",
                border_style="red",
            )
        )

    def render_table(
        self,
        headers: List[str],
        rows: List[List[str]],
        title: Optional[str] = None,
    ) -> None:
        """Render tabular data using Rich Table.

        Args:
            headers: Column header labels.
            rows: List of row data (each row is a list of cell strings).
            title: Optional table title.
        """
        table = Table(title=title, show_header=True, header_style="bold magenta")
        for header in headers:
            table.add_column(header)
        for row in rows:
            table.add_row(*[str(cell) for cell in row])
        self.console.print(table)

    def render_info(self, lines: List[tuple[str, str]]) -> None:
        """Render key-value info lines.

        Args:
            lines: List of (key, value) tuples to display.
        """
        text = Text()
        for key, value in lines:
            text.append(f"{key}: ", style="bold cyan")
            text.append(f"{value}\n")
        self.console.print(Panel(text, title="[bold]Agent Info[/bold]", border_style="blue"))

    # ------------------------------------------------------------------
    # Streaming rendering
    # ------------------------------------------------------------------

    def render_stream_start(self) -> None:
        """Begin a streaming session: reset the buffer and start the live region."""
        self._stream_buffer = ""
        self.region.start()

    def _stream_renderable(self) -> Any:
        """``Markdown`` of the buffer; falls back to plain ``Text`` when the partial document cannot parse."""
        try:
            return Markdown(self._stream_buffer)
        except Exception:  # noqa: BLE001 — unclosed fence/table mid-stream (spec §7)
            return Text(self._stream_buffer)

    def render_stream_chunk(self, text: str) -> None:
        """Append a streamed chunk and repaint the region (throttled by its refresh tick). Never touches stdout.

        Args:
            text: The text chunk to append to the output.
        """
        self._stream_buffer += text
        self.region.update(self._stream_renderable())

    def render_stream_end(self, response: Optional[AIMessage] = None) -> None:
        """Stop the region, then render tool panels and usage exactly as before.

        Args:
            response: The final AIMessage (used for tool calls and usage stats).
                      May be ``None`` if only streaming text was available.
        """
        self.region.update(self._stream_renderable())
        self.region.stop()

        if response is not None:
            if getattr(response, "tool_calls", None):
                self._render_tool_calls(response.tool_calls)
            usage = getattr(response, "usage", None)
            if usage and (usage.prompt_tokens or usage.completion_tokens):
                self._render_usage(usage)
            else:
                self.render_usage_unknown()

        self._stream_buffer = ""

    def print(self, *args: Any, **kwargs: Any) -> None:
        """Forward arbitrary print calls to the Rich console.

        Args:
            *args: Positional arguments passed to ``Console.print``.
            **kwargs: Keyword arguments passed to ``Console.print``.
        """
        self.console.print(*args, **kwargs)

    # ------------------------------------------------------------------
    # TurnEvent / history rendering
    # ------------------------------------------------------------------

    def render_usage_unknown(self) -> None:
        """Render a placeholder for unknown usage; never shown as zero (AC8)."""
        self.console.print("[dim]tokens: n/a[/dim]")

    def render_tool_started(self, event: ToolStarted) -> None:
        """Print one dim status line when a tool starts running.

        Args:
            event: The ``ToolStarted`` event.
        """
        self.console.print(f"[dim]⏵ tool [bold]{event.tool_name}[/bold] …[/dim]")

    def render_turn_event(self, event: TurnEvent) -> None:
        """Dispatch a ``TurnEvent`` to the inline rendering primitives.

        Args:
            event: The turn-lifecycle event to render.
        """
        if isinstance(event, TextDelta):
            self.render_stream_chunk(event.text)
        elif isinstance(event, ToolStarted):
            self.region.pause()
            self.render_tool_started(event)
            self.region.resume()
        elif isinstance(event, (ToolFinished, ToolFailed)):
            self.region.pause()
            if isinstance(event, ToolFinished):
                self.console.print(f"[dim]✓ tool [bold]{event.tool_name}[/bold] ({event.duration_ms:.0f} ms)[/dim]")
            else:
                self.console.print(f"[red]✗ tool [bold]{event.tool_name}[/bold]: {event.error_type}[/red]")
            self.region.resume()
        elif isinstance(event, TurnCompleted):
            self.render_stream_end(event.message)
        elif isinstance(event, TurnCancelled):
            self.region.stop()
            self.console.print("[yellow]Interrupted — partial answer kept above.[/yellow]")
        elif isinstance(event, TurnFailed):
            self.region.stop()
            content = Text()
            content.append(f"{event.error_type}: ", style="bold red")
            content.append(event.error_message)
            self.console.print(Panel(content, title="[bold red]Error[/bold red]", border_style="red"))

    def render_history(self, turns: List[ConversationTurn], *, session_id: str) -> None:
        """Render a resumed transcript: header, then each turn as ``you> …`` plus its response.

        Args:
            turns: Prior conversation turns to render, in order.
            session_id: The session id the transcript belongs to.
        """
        self.console.print(f"[bold]Resumed session[/bold] {session_id} [dim]({len(turns)} turns)[/dim]")
        for turn in turns:
            self.console.print(f"[bold cyan]you>[/bold cyan] {turn.query}")
            if turn.response is not None:
                self.render(turn.response)

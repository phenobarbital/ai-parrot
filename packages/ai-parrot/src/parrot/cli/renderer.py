"""Response renderer for AI-Parrot CLI agent REPL.

Renders ``AIMessage`` objects to the terminal using Rich for markdown,
code blocks, tool call panels, usage stats, and streaming live display.
"""
import json
import logging
import traceback
from typing import Any, List, Optional

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from parrot.models.responses import AIMessage


class ResponseRenderer:
    """Renders AIMessage responses to the terminal via Rich.

    Supports both batch mode (full response rendered at once) and streaming
    mode (incremental token display via ``rich.live.Live``).

    Attributes:
        console: Rich Console instance used for all output.
    """

    def __init__(self) -> None:
        """Initialise the renderer with a Rich Console."""
        self.logger = logging.getLogger(__name__)
        self.console = Console()
        self._live: Optional[Live] = None
        self._stream_buffer: str = ""

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
        if response.usage and (
            response.usage.prompt_tokens or response.usage.completion_tokens
        ):
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
            self.console.print(
                f"[dim]tokens: {', '.join(parts)}[/dim]"
            )

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
        self.console.print(
            Panel(text, title="[bold]Agent Info[/bold]", border_style="blue")
        )

    # ------------------------------------------------------------------
    # Streaming rendering
    # ------------------------------------------------------------------

    def render_stream_start(self) -> None:
        """Begin a streaming live display session.

        Must be called before the first ``render_stream_chunk()`` call.
        Creates a ``rich.live.Live`` context that accumulates token output.
        """
        self._stream_buffer = ""
        self._live = Live(
            Text(""),
            console=self.console,
            refresh_per_second=10,
            vertical_overflow="visible",
        )
        self._live.__enter__()

    def render_stream_chunk(self, text: str) -> None:
        """Append a streamed token chunk to the live display.

        Args:
            text: The text chunk to append to the live output.
        """
        if self._live is None:
            # Fallback: print without live context
            self.console.print(text, end="")
            return
        self._stream_buffer += text
        try:
            self._live.update(Markdown(self._stream_buffer))
        except Exception:
            # If markdown parse fails on partial input, show as plain text
            self._live.update(Text(self._stream_buffer))

    def render_stream_end(self, response: Optional[AIMessage] = None) -> None:
        """Finalise the streaming display and show metadata.

        Args:
            response: The final AIMessage (used for tool calls and usage stats).
                      May be None if only streaming text was available.
        """
        if self._live is not None:
            try:
                self._live.__exit__(None, None, None)
            except Exception as exc:
                self.logger.debug("Live context exit error: %s", exc)
            finally:
                self._live = None

        # Ensure a newline after stream
        self.console.print()

        if response is not None:
            if response.tool_calls:
                self._render_tool_calls(response.tool_calls)
            if response.usage and (
                response.usage.prompt_tokens or response.usage.completion_tokens
            ):
                self._render_usage(response.usage)

        self._stream_buffer = ""

    def print(self, *args: Any, **kwargs: Any) -> None:
        """Forward arbitrary print calls to the Rich console.

        Args:
            *args: Positional arguments passed to ``Console.print``.
            **kwargs: Keyword arguments passed to ``Console.print``.
        """
        self.console.print(*args, **kwargs)

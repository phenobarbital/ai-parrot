"""Response renderer for AI-Parrot CLI agent REPL.

Renders ``AIMessage`` objects to the terminal using Rich for markdown,
code blocks, tool call panels, usage stats, and streaming live display.
"""
import json
import logging
import sys
import time
import traceback
from typing import Any, List, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from parrot.models.responses import AIMessage


class _BlockingSafeFile:
    """Thin proxy that retries writes on ``BlockingIOError``.

    When ``prompt_toolkit.patch_stdout()`` puts ``sys.__stdout__`` into
    non-blocking mode, a large ``Rich.Console.print()`` can overflow the
    kernel pipe buffer and raise ``BlockingIOError`` (errno 11 / EAGAIN).
    This wrapper catches the error, waits briefly for the fd to drain,
    and retries — keeping the fd non-blocking for prompt_toolkit's own
    I/O while making Rich writes effectively blocking.
    """

    _MAX_RETRIES: int = 200  # ~1 s total at 5 ms per retry

    def __init__(self, wrapped) -> None:
        self._wrapped = wrapped

    def write(self, s: str) -> int:
        for _ in range(self._MAX_RETRIES):
            try:
                return self._wrapped.write(s)
            except BlockingIOError:
                time.sleep(0.005)
        # Final attempt — let it raise if still blocked.
        return self._wrapped.write(s)

    def flush(self) -> None:
        for _ in range(self._MAX_RETRIES):
            try:
                return self._wrapped.flush()
            except BlockingIOError:
                time.sleep(0.005)
        return self._wrapped.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


class ResponseRenderer:
    """Renders AIMessage responses to the terminal via Rich.

    Supports both batch mode (full response rendered at once) and streaming
    mode (incremental token display via direct stdout writes).

    Attributes:
        console: Rich Console instance used for all output.
    """

    def __init__(self) -> None:
        """Initialise the renderer with a Rich Console.

        The Console writes to ``sys.__stdout__`` (the original file
        descriptor) instead of ``sys.stdout``.  Inside the REPL,
        ``prompt_toolkit.patch_stdout()`` replaces ``sys.stdout``
        with a proxy that corrupts ANSI escape sequences — the ESC
        byte (``\\x1b``) is rendered as a literal ``?``.  Bypassing
        the proxy lets Rich emit ANSI codes straight to the terminal.
        """
        self.logger = logging.getLogger(__name__)
        self.console = Console(
            file=_BlockingSafeFile(sys.__stdout__), force_terminal=True
        )
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
        """Begin a streaming session.

        Must be called before the first ``render_stream_chunk()`` call.

        Uses direct incremental writes (``sys.stdout``) instead of
        ``rich.live.Live``.  ``Live`` emits ANSI cursor-control sequences
        (``\\x1b[2K``, ``\\x1b[?25l``, …) that conflict with
        ``prompt_toolkit.patch_stdout()`` — the patched stdout does not
        forward them correctly, so they render as literal ``?[2K`` garbage.
        Plain writes avoid this entirely and match the character-by-character
        streaming UX users expect.
        """
        self._stream_buffer = ""

    def render_stream_chunk(self, text: str) -> None:
        """Write a streamed token chunk directly to stdout.

        Args:
            text: The text chunk to append to the output.
        """
        import sys
        self._stream_buffer += text
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except Exception:
            pass

    def render_stream_end(self, response: Optional[AIMessage] = None) -> None:
        """Finalise the streaming display and show metadata.

        Args:
            response: The final AIMessage (used for tool calls and usage stats).
                      May be ``None`` if only streaming text was available.
        """
        # Newline after the streamed text
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

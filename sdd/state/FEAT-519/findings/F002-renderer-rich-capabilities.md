---
id: F002
query_id: Q004
type: read
intent: Establish what rendering capability already exists and whether it uses Rich
executed_at: 2026-09-02T21:57:30Z
parent_id: null
depth: 0
---

# F002 — `ResponseRenderer` already implements Markdown, panels, tables and usage stats

## Summary

`cli/renderer.py` is a complete Rich renderer: batch responses render through
`rich.markdown.Markdown`, tool calls through `rich.panel.Panel`, tabular data
through `rich.table.Table`, errors through a red-bordered Panel, and token usage
as a dim line. The batch path (`--no-stream`) therefore already produces a good
look & feel. The capability gap is confined to the streaming path (F003).

## Citations

- path: `packages/ai-parrot/src/parrot/cli/renderer.py`
  lines: 13-19
  symbol: imports
  excerpt: |
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

- path: `packages/ai-parrot/src/parrot/cli/renderer.py`
  lines: 102-104
  symbol: `ResponseRenderer.render`
  excerpt: |
    # Render main output as Markdown
    if isinstance(output, str) and output.strip():
        self.console.print(Markdown(output))

- path: `packages/ai-parrot/src/parrot/cli/renderer.py`
  lines: 145-151
  symbol: `_render_tool_calls`
  excerpt: |
    self.console.print(
        Panel(
            panel_content,
            title=f"[bold cyan]Tool: {tool_name}[/bold cyan]",
            border_style="cyan",
        )
    )

- path: `packages/ai-parrot/src/parrot/cli/renderer.py`
  lines: 208-213
  symbol: `render_table`
  excerpt: |
    table = Table(title=title, show_header=True, header_style="bold magenta")

- path: `packages/ai-parrot/src/parrot/cli/renderer.py`
  lines: 282-289
  symbol: `ResponseRenderer.print`
  excerpt: |
    def print(self, *args: Any, **kwargs: Any) -> None:
        """Forward arbitrary print calls to the Rich console."""
        self.console.print(*args, **kwargs)

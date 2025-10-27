from typing import Any
import pprint
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode



@register_renderer(OutputMode.TERMINAL)
class TerminalRenderer(BaseRenderer):
    """Render for terminal"""
    @staticmethod
    def render(response: Any, **kwargs) -> str:
        try:
            from rich.console import Console
            from rich.markdown import Markdown
            from rich.panel import Panel as RichPanel
            from rich.table import Table
            from rich.json import JSON
            from rich.pretty import Pretty
            show_sources = kwargs.get('show_sources', True)
            show_context = kwargs.get('show_context', False)
            show_tools = kwargs.get('show_tools', False)
            if is_ipython := kwargs.get('is_ipython', False):
                console = Console(
                    force_jupyter=True,
                    force_terminal=False,
                    width=100  # Fixed width for Jupyter
                )
            else:
                console = Console(force_terminal=True)

            content = TerminalRenderer._get_content(response)
            with console.capture() as capture:

                if any(marker in content for marker in ['#', '```', '*', '-', '>']):
                    md = Markdown(content)
                    console.print(
                        RichPanel(md, title="🤖 Response", border_style="blue")
                    )
                else:
                    console.print(Pretty(content))

                # Show tool calls if requested and available
                if show_tools and hasattr(response, 'tool_calls') and response.tool_calls:
                    tools_list = TerminalRenderer._create_tools_list(response.tool_calls)
                    tools_table = Table(
                        title="🔧 Tool Calls", show_header=True, header_style="bold green"
                    )
                    tools_table.add_column("No.", style="dim", width=4)
                    tools_table.add_column("Tool Name", style="cyan")
                    tools_table.add_column("Status", style="green")
                    for tool in tools_list:
                        tools_table.add_row(tool["No."], tool["Tool Name"], tool["Status"])
                    console.print(tools_table)
                # Show metadata if requested
                if kwargs.get('show_metadata', False):
                    metadata_table = Table(
                        title="📊 Metadata",
                        show_header=True,
                        header_style="bold magenta"
                    )
                    metadata_table.add_column("Key", style="cyan", width=20)
                    metadata_table.add_column("Value", style="green")
                    if hasattr(response, 'model'):
                        metadata_table.add_row("Model", str(response.model))
                    if hasattr(response, 'provider'):
                        metadata_table.add_row("Provider", str(response.provider))
                    if hasattr(response, 'session_id') and response.session_id:
                        metadata_table.add_row("Session ID", str(response.session_id)[:16] + "...")
                    if hasattr(response, 'turn_id') and response.turn_id:
                        metadata_table.add_row("Turn ID", str(response.turn_id)[:16] + "...")
                    if hasattr(response, 'usage') and response.usage:
                        usage = response.usage
                        if hasattr(usage, 'total_tokens'):
                            metadata_table.add_row("Total Tokens", str(usage.total_tokens))
                        if hasattr(usage, 'prompt_tokens'):
                            metadata_table.add_row("Prompt Tokens", str(usage.prompt_tokens))
                        if hasattr(usage, 'completion_tokens'):
                            metadata_table.add_row("Completion Tokens", str(usage.completion_tokens))
                    if hasattr(response, 'response_time') and response.response_time:
                        metadata_table.add_row("Response Time", f"{response.response_time:.2f}s")

                    console.print(metadata_table)
                            # Show sources if available and requested
                if show_sources and hasattr(response, 'source_documents') and response.source_documents:
                    sources_list = TerminalRenderer._create_sources_list(response.source_documents)
                    sources_table = Table(show_header=True, header_style="bold cyan")
                    sources_table.add_column("No.", style="dim", width=4)
                    sources_table.add_column("Source", style="cyan")
                    sources_table.add_column("Score", style="green")
                    for source in sources_list:
                        sources_table.add_row(source["No."], source["Source"], source["Score"])
                    console.print(sources_table)

            return capture.get()
        except ImportError:
            return pprint.pformat(response)

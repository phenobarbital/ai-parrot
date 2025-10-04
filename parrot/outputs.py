"""
Output formatters for AI-Parrot using Rich (terminal) and Panel (HTML)
"""
from typing import Any, List
from enum import Enum
import json

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel as RichPanel
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.json import JSON
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    import panel as pn
    from panel.pane import Markdown as PanelMarkdown
    from panel.pane import HTML, JSON as PanelJSON
    from panel.layout import Column, Row
    PANEL_AVAILABLE = True
except ImportError:
    PANEL_AVAILABLE = False


class OutputMode(str, Enum):
    """Output mode enumeration"""
    DEFAULT = "default"
    TERMINAL = "terminal"
    HTML = "html"
    JSON = "json"


class OutputFormatter:
    """
    Formatter for AI responses supporting multiple output modes.
    """

    def __init__(self, mode: OutputMode = OutputMode.DEFAULT):
        self.mode = mode
        self._is_ipython = self._detect_ipython()

        # Configure Rich Console for the environment
        if RICH_AVAILABLE:
            if self._is_ipython:
                # Use Jupyter-friendly settings
                self.console = Console(
                    force_jupyter=True,
                    force_terminal=False,
                    width=100  # Fixed width for Jupyter
                )
            else:
                self.console = Console()
        else:
            self.console = None

        # Initialize Panel if available
        if PANEL_AVAILABLE and mode == OutputMode.HTML:
            pn.extension()

    def _detect_ipython(self) -> bool:
        """Detect if running in IPython/Jupyter environment."""
        try:
            # Check if IPython is available and active
            from IPython import get_ipython
            return get_ipython() is not None
        except (ImportError, NameError):
            return False

    def format(self, response: Any, **kwargs) -> Any:
        """
        Format the response based on the current mode.

        Args:
            response: AIMessage response object
            **kwargs: Additional formatting options

        Returns:
            Formatted output based on mode
        """
        if self.mode == OutputMode.TERMINAL:
            return self._format_terminal(response, **kwargs)
        elif self.mode == OutputMode.HTML:
            return self._format_html(response, **kwargs)
        elif self.mode == OutputMode.JSON:
            return self._format_json(response, **kwargs)
        else:
            return response

    def _get_content(self, response: Any) -> str:
        """
        Extract content from response safely.

        Args:
            response: AIMessage response object

        Returns:
            String content from the response
        """
        # Try content property first (if added to AIMessage)
        if hasattr(response, 'content'):
            return response.content
        # Try to_text property
        elif hasattr(response, 'to_text'):
            return response.to_text
        # Try output attribute
        elif hasattr(response, 'output'):
            output = response.output
            if isinstance(output, str):
                return output
            return str(output)
        # Try response attribute
        elif hasattr(response, 'response'):
            return response.response or ""
        # Fallback
        return str(response)

    def _format_terminal(self, response: Any, **kwargs) -> None:
        """
        Format output for terminal using Rich.

        Args:
            response: AIMessage response object
            **kwargs: Additional options (show_metadata, show_sources, etc.)
        """
        if not RICH_AVAILABLE:
            print("Rich library not available. Install with: pip install rich")
            print(f"\n{self._get_content(response)}\n")
            return

        show_metadata = kwargs.get('show_metadata', True)
        show_sources = kwargs.get('show_sources', True)
        show_context = kwargs.get('show_context', False)
        show_tools = kwargs.get('show_tools', False)

        try:
            # Main response content
            content = self._get_content(response)
            if content:
                # Try to render as markdown if it looks like markdown
                if any(marker in content for marker in ['#', '```', '*', '-', '>']):
                    md = Markdown(content)
                    self.console.print(RichPanel(md, title="🤖 Response", border_style="blue"))
                else:
                    self.console.print(RichPanel(content, title="🤖 Response", border_style="blue"))

            # Show tool calls if requested and available
            if show_tools and hasattr(response, 'tool_calls') and response.tool_calls:
                tools_table = self._create_tools_table(response.tool_calls)
                self.console.print(tools_table)

            # Show metadata if requested
            if show_metadata:
                metadata_table = Table(title="📊 Metadata", show_header=True, header_style="bold magenta")
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

                self.console.print(metadata_table)

            # Show context information
            if show_context:
                context_table = Table(title="📚 Context Info", show_header=True, header_style="bold yellow")
                context_table.add_column("Type", style="cyan", width=20)
                context_table.add_column("Details", style="green")

                if hasattr(response, 'used_vector_context'):
                    status = "✓ Used" if response.used_vector_context else "✗ Not used"
                    context_table.add_row("Vector Context", status)
                    if response.used_vector_context:
                        context_table.add_row("  - Length", str(response.vector_context_length))
                        context_table.add_row("  - Search Type", str(response.search_type or "N/A"))
                        context_table.add_row("  - Results", str(response.search_results_count))

                if hasattr(response, 'used_conversation_history'):
                    status = "✓ Used" if response.used_conversation_history else "✗ Not used"
                    context_table.add_row("Conversation History", status)
                    if response.used_conversation_history:
                        context_table.add_row("  - Length", str(response.conversation_context_length))

                self.console.print(context_table)

            # Show sources if available and requested
            if show_sources and hasattr(response, 'source_documents') and response.source_documents:
                sources_panel = self._create_sources_panel(response.source_documents)
                self.console.print(sources_panel)

        except BlockingIOError:
            # Handle IPython/Jupyter async blocking issues
            self._fallback_print(response, show_metadata, show_sources, show_context, show_tools)
        except Exception as e:
            # Fallback to simple print on any Rich error
            print(f"Warning: Rich formatting failed ({e}), using fallback display")
            self._fallback_print(response, show_metadata, show_sources, show_context, show_tools)

    def _fallback_print(self, response: Any, show_metadata: bool, show_sources: bool,
                       show_context: bool, show_tools: bool) -> None:
        """
        Fallback print method when Rich fails (e.g., in IPython async contexts).
        Uses IPython's display system if available, otherwise plain print.
        """
        content = self._get_content(response)

        if self._is_ipython:
            try:
                from IPython.display import display, Markdown as IPyMarkdown, HTML

                # Display content
                if any(marker in content for marker in ['#', '```', '*', '-', '>']):
                    display(IPyMarkdown(content))
                else:
                    print(content)

                # Display metadata
                if show_metadata:
                    metadata_lines = ["**Metadata:**"]
                    if hasattr(response, 'model'):
                        metadata_lines.append(f"- Model: {response.model}")
                    if hasattr(response, 'provider'):
                        metadata_lines.append(f"- Provider: {response.provider}")
                    if hasattr(response, 'usage') and response.usage:
                        if hasattr(response.usage, 'total_tokens'):
                            metadata_lines.append(f"- Total Tokens: {response.usage.total_tokens}")
                    display(IPyMarkdown("\n".join(metadata_lines)))

                # Display sources
                if show_sources and hasattr(response, 'source_documents') and response.source_documents:
                    sources_lines = ["**Sources:**"]
                    for idx, source in enumerate(response.source_documents, 1):
                        source_name = getattr(source, 'source', 'Unknown') if hasattr(source, 'source') else source.get('source', 'Unknown')
                        score = getattr(source, 'score', 'N/A') if hasattr(source, 'score') else source.get('score', 'N/A')
                        score_str = f"{score:.4f}" if isinstance(score, float) else str(score)
                        sources_lines.append(f"{idx}. {source_name} (Score: {score_str})")
                    display(IPyMarkdown("\n".join(sources_lines)))

            except Exception:
                # If IPython display fails, fall back to plain print
                self._plain_print(response, show_metadata, show_sources, show_context, show_tools)
        else:
            # Not in IPython, use plain print
            self._plain_print(response, show_metadata, show_sources, show_context, show_tools)

    def _plain_print(self, response: Any, show_metadata: bool, show_sources: bool,
                    show_context: bool, show_tools: bool) -> None:
        """Plain text output without any formatting libraries."""
        content = self._get_content(response)

        print("\n" + "="*80)
        print("RESPONSE")
        print("="*80)
        print(content)

        if show_metadata:
            print("\n" + "-"*80)
            print("METADATA")
            print("-"*80)
            if hasattr(response, 'model'):
                print(f"Model: {response.model}")
            if hasattr(response, 'provider'):
                print(f"Provider: {response.provider}")
            if hasattr(response, 'usage') and response.usage:
                if hasattr(response.usage, 'total_tokens'):
                    print(f"Total Tokens: {response.usage.total_tokens}")

        if show_sources and hasattr(response, 'source_documents') and response.source_documents:
            print("\n" + "-"*80)
            print("SOURCES")
            print("-"*80)
            for idx, source in enumerate(response.source_documents, 1):
                source_name = getattr(source, 'source', 'Unknown') if hasattr(source, 'source') else source.get('source', 'Unknown')
                score = getattr(source, 'score', 'N/A') if hasattr(source, 'score') else source.get('score', 'N/A')
                score_str = f"{score:.4f}" if isinstance(score, float) else str(score)
                print(f"{idx}. {source_name} (Score: {score_str})")

        print("="*80 + "\n")

    def _create_tools_table(self, tool_calls: List[Any]) -> Table:
        """Create a Rich table for tool calls."""
        tools_table = Table(title="🔧 Tool Calls", show_header=True, header_style="bold green")
        tools_table.add_column("#", style="dim", width=4)
        tools_table.add_column("Tool Name", style="cyan")
        tools_table.add_column("Status", style="green")

        for idx, tool in enumerate(tool_calls, 1):
            name = getattr(tool, 'name', 'Unknown')
            status = getattr(tool, 'status', 'completed')
            tools_table.add_row(str(idx), name, status)

        return tools_table

    def _create_sources_panel(self, sources: List[Any]) -> RichPanel:
        """Create a Rich panel for sources."""
        sources_table = Table(show_header=True, header_style="bold cyan")
        sources_table.add_column("#", style="dim", width=4)
        sources_table.add_column("Source", style="cyan")
        sources_table.add_column("Score", style="green", width=10)

        for idx, source in enumerate(sources, 1):
            # Handle both SourceDocument objects and dict-like sources
            if hasattr(source, 'source'):
                source_name = source.source
            elif isinstance(source, dict):
                source_name = source.get('source', 'Unknown')
            else:
                source_name = str(source)

            if hasattr(source, 'score'):
                score = source.score
            elif isinstance(source, dict):
                score = source.get('score', 'N/A')
            else:
                score = 'N/A'

            score_str = f"{score:.4f}" if isinstance(score, float) else str(score)
            sources_table.add_row(str(idx), source_name, score_str)

        return RichPanel(sources_table, title="📄 Sources", border_style="cyan")

    def _format_html(self, response: Any, **kwargs) -> Any:
        """
        Format output as HTML using Panel.

        Args:
            response: AIMessage response object
            **kwargs: Additional options

        Returns:
            Panel dashboard or HTML string
        """
        if not PANEL_AVAILABLE:
            content = self._get_content(response)
            return f"<div>Panel library not available. Install with: pip install panel</div><div>{content}</div>"

        show_metadata = kwargs.get('show_metadata', True)
        show_sources = kwargs.get('show_sources', True)
        show_tools = kwargs.get('show_tools', False)
        return_html = kwargs.get('return_html', False)

        components = []

        # Main response
        content = self._get_content(response)
        if content:
            response_md = PanelMarkdown(
                content,
                sizing_mode='stretch_width',
                styles={'background': '#f0f8ff', 'padding': '20px', 'border-radius': '5px'}
            )
            components.append(pn.pane.HTML("<h2>🤖 Response</h2>"))
            components.append(response_md)

        # Tool calls section
        if show_tools and hasattr(response, 'tool_calls') and response.tool_calls:
            tools_html = self._create_tools_html(response.tool_calls)
            components.append(pn.pane.HTML("<h3>🔧 Tool Calls</h3>"))
            components.append(pn.pane.HTML(tools_html))

        # Metadata section
        if show_metadata:
            metadata_html = self._create_metadata_html(response)
            components.append(pn.pane.HTML("<h3>📊 Metadata</h3>"))
            components.append(pn.pane.HTML(metadata_html))

        # Sources section
        if show_sources and hasattr(response, 'source_documents') and response.source_documents:
            sources_html = self._create_sources_html(response.source_documents)
            components.append(pn.pane.HTML("<h3>📄 Sources</h3>"))
            components.append(pn.pane.HTML(sources_html))

        # Create dashboard
        dashboard = Column(*components, sizing_mode='stretch_width')

        if return_html:
            return dashboard.save('response.html', embed=True)

        return dashboard

    def _create_tools_html(self, tool_calls: List[Any]) -> str:
        """Create HTML table for tool calls."""
        html = "<table style='width:100%; border-collapse: collapse; margin-top: 10px;'>"
        html += "<tr style='background-color: #d0f0d0;'><th style='padding: 8px;'>#</th><th style='padding: 8px;'>Tool Name</th><th style='padding: 8px;'>Status</th></tr>"

        for idx, tool in enumerate(tool_calls, 1):
            name = getattr(tool, 'name', 'Unknown')
            status = getattr(tool, 'status', 'completed')

            bg_color = '#ffffff' if idx % 2 == 0 else '#f9f9f9'
            html += f"<tr style='background-color: {bg_color};'>"
            html += f"<td style='padding: 8px;'>{idx}</td>"
            html += f"<td style='padding: 8px;'>{name}</td>"
            html += f"<td style='padding: 8px;'>{status}</td>"
            html += "</tr>"

        html += "</table>"
        return html

    def _create_metadata_html(self, response: Any) -> str:
        """Create HTML table for metadata."""
        html = "<table style='width:100%; border-collapse: collapse;'>"
        html += "<tr style='background-color: #e0e0e0;'><th style='padding: 8px; text-align: left;'>Key</th><th style='padding: 8px; text-align: left;'>Value</th></tr>"

        if hasattr(response, 'model'):
            html += f"<tr><td style='padding: 8px;'>Model</td><td style='padding: 8px;'>{response.model}</td></tr>"
        if hasattr(response, 'provider'):
            html += f"<tr><td style='padding: 8px;'>Provider</td><td style='padding: 8px;'>{response.provider}</td></tr>"
        if hasattr(response, 'session_id') and response.session_id:
            html += f"<tr><td style='padding: 8px;'>Session ID</td><td style='padding: 8px;'>{str(response.session_id)[:16]}...</td></tr>"
        if hasattr(response, 'turn_id') and response.turn_id:
            html += f"<tr><td style='padding: 8px;'>Turn ID</td><td style='padding: 8px;'>{str(response.turn_id)[:16]}...</td></tr>"
        if hasattr(response, 'usage') and response.usage:
            usage = response.usage
            if hasattr(usage, 'total_tokens'):
                html += f"<tr><td style='padding: 8px;'>Total Tokens</td><td style='padding: 8px;'>{usage.total_tokens}</td></tr>"
        if hasattr(response, 'response_time') and response.response_time:
            html += f"<tr><td style='padding: 8px;'>Response Time</td><td style='padding: 8px;'>{response.response_time:.2f}s</td></tr>"

        html += "</table>"
        return html

    def _create_sources_html(self, sources: List[Any]) -> str:
        """Create HTML table for sources."""
        html = "<table style='width:100%; border-collapse: collapse; margin-top: 10px;'>"
        html += "<tr style='background-color: #d0e8f0;'><th style='padding: 8px;'>#</th><th style='padding: 8px;'>Source</th><th style='padding: 8px;'>Score</th></tr>"

        for idx, source in enumerate(sources, 1):
            # Handle both SourceDocument objects and dict-like sources
            if hasattr(source, 'source'):
                source_name = source.source
            elif isinstance(source, dict):
                source_name = source.get('source', 'Unknown')
            else:
                source_name = str(source)

            if hasattr(source, 'score'):
                score = source.score
            elif isinstance(source, dict):
                score = source.get('score', 'N/A')
            else:
                score = 'N/A'

            score_str = f"{score:.4f}" if isinstance(score, float) else str(score)

            bg_color = '#ffffff' if idx % 2 == 0 else '#f9f9f9'
            html += f"<tr style='background-color: {bg_color};'>"
            html += f"<td style='padding: 8px;'>{idx}</td>"
            html += f"<td style='padding: 8px;'>{source_name}</td>"
            html += f"<td style='padding: 8px;'>{score_str}</td>"
            html += "</tr>"

        html += "</table>"
        return html

    def _format_json(self, response: Any, **kwargs) -> dict:
        """
        Format output as JSON.

        Args:
            response: AIMessage response object
            **kwargs: Additional options

        Returns:
            Dictionary representation of the response
        """
        result = {
            'content': self._get_content(response),
        }

        if hasattr(response, 'model'):
            result['model'] = response.model
        if hasattr(response, 'provider'):
            result['provider'] = response.provider
        if hasattr(response, 'session_id'):
            result['session_id'] = response.session_id
        if hasattr(response, 'turn_id'):
            result['turn_id'] = response.turn_id
        if hasattr(response, 'usage'):
            result['usage'] = {
                'total_tokens': getattr(response.usage, 'total_tokens', None),
                'prompt_tokens': getattr(response.usage, 'prompt_tokens', None),
                'completion_tokens': getattr(response.usage, 'completion_tokens', None),
            }
        if hasattr(response, 'response_time'):
            result['response_time'] = response.response_time
        if hasattr(response, 'tool_calls') and response.tool_calls:
            result['tool_calls'] = [
                {
                    'name': getattr(tool, 'name', 'Unknown'),
                    'status': getattr(tool, 'status', 'completed')
                }
                for tool in response.tool_calls
            ]
        if hasattr(response, 'source_documents') and response.source_documents:
            result['sources'] = [
                {
                    'source': getattr(doc, 'source', str(doc)) if hasattr(doc, 'source') else doc.get('source', 'Unknown'),
                    'score': getattr(doc, 'score', None) if hasattr(doc, 'score') else doc.get('score', None)
                }
                for doc in response.source_documents
            ]
        if hasattr(response, 'context_summary'):
            result['context'] = response.context_summary

        if kwargs.get('pretty', False):
            if RICH_AVAILABLE and self.console:
                self.console.print(JSON(json.dumps(result)))
            else:
                print(json.dumps(result, indent=2))

        return result

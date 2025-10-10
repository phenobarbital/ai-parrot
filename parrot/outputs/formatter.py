from typing import Any, List, Optional, Union
import os
import tempfile
import re
import json
import markdown
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
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

try:
    import ipywidgets as widgets
    IPYWIDGETS_AVAILABLE = True
except ImportError:
    IPYWIDGETS_AVAILABLE = False

try:
    import folium
    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False

try:
    import plotly.graph_objects as go
    import plotly.io as pio
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

try:
    import matplotlib.pyplot as plt
    import matplotlib as mp
    from matplotlib.figure import Figure
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

from .base import (
    OutputMode,
    OutputType,
    OutputDetector,
    RenderableOutput
)
from .renderer import (
    FoliumRenderer,
    PlotlyRenderer,
    MatplotlibRenderer,
    DataFrameRenderer,
    AltairRenderer,
    HTMLWidgetRenderer
)

class OutputFormatter:
    """
    Formatter for AI responses supporting multiple output modes.
    """

    def __init__(self, mode: OutputMode = OutputMode.DEFAULT, use_panel: bool = True):
        self.mode = mode
        self._is_ipython = self._detect_ipython()
        self._is_notebook = self._detect_notebook()
        self.use_panel = use_panel

        # Auto-detect Jupyter and switch to JUPYTER mode if appropriate
        if self.mode == OutputMode.DEFAULT and self._is_notebook:
            self.mode = OutputMode.JUPYTER

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

        # Initialize renderers
        self.renderers = {
            OutputType.FOLIUM_MAP: FoliumRenderer(),
            OutputType.PLOTLY_CHART: PlotlyRenderer(),
            OutputType.MATPLOTLIB_FIGURE: MatplotlibRenderer(),
            OutputType.DATAFRAME: DataFrameRenderer(),
            OutputType.ALTAIR_CHART: AltairRenderer(),
            OutputType.HTML_WIDGET: HTMLWidgetRenderer(),
        }

    def _detect_ipython(self) -> bool:
        """Detect if running in IPython/Jupyter environment."""
        try:
            import sys
            if 'IPython' not in sys.modules:
                return False
            # Check if IPython is available and active
            from IPython import get_ipython
            return get_ipython() is not None
        except (ImportError, NameError):
            return False

    def _detect_notebook(self) -> bool:
        """Detect if running specifically in Jupyter notebook (not just IPython)."""
        try:
            from IPython import get_ipython
            ipython = get_ipython()
            if ipython is None:
                return False
            # Check if it's a notebook kernel
            return 'IPKernelApp' in ipython.config
        except:
            return False

    def format(self, response: Any, **kwargs) -> Any:
        """
        Smart format that detects output types and renders appropriately.

        Args:
            response: Response object or visualization object
            **kwargs: Rendering options
                - title: Title for the output
                - description: Description
                - For HTML mode:
                    - return_html: Return HTML string instead of displaying
                    - embed_resources: Embed all resources inline
                - For each output type: specific rendering options

        Returns:
            Rendered output (displayed or returned based on mode and options)
        """
        # Extract actual content from response if it's an AI response object
        content = self._extract_content(response)

        # Detect output types
        renderables = OutputDetector.detect_multiple(content)
        if renderables:
            if self.mode == OutputMode.TERMINAL:
                return self._render_terminal(renderables, **kwargs)
            elif self.mode == OutputMode.HTML:
                return self._render_html(renderables, **kwargs)
            elif self.mode in (OutputMode.JUPYTER, OutputMode.NOTEBOOK):
                return self._render_jupyter(renderables, **kwargs)
            elif self.mode == OutputMode.JSON:
                return self._render_json(renderables, **kwargs)

        # Fallback: plain text rendering
        if self.mode == OutputMode.TERMINAL:
            return self._format_terminal(response, **kwargs)
        elif self.mode == OutputMode.HTML:
            return self._format_html(response, **kwargs)
        elif self.mode == OutputMode.JSON:
            return self._format_json(response, **kwargs)
        elif self.mode in (OutputMode.JUPYTER, OutputMode.NOTEBOOK):
            return self._format_jupyter(response, **kwargs)
        else:
            return response

    def has_visualizations(self, response: Any) -> bool:
        """
        Check if response contains renderable visualizations.

        Args:
            response: Response object to check

        Returns:
            True if visualizations found, False otherwise
        """
        content = self._extract_content(response)
        renderables = OutputDetector.detect_multiple(content)
        return renderables is not None and len(renderables) > 0

    def _render_terminal(self, renderables: List[RenderableOutput], **kwargs) -> None:
        """Render for terminal"""
        for renderable in renderables:
            # Title
            if renderable.title and self.console:
                self.console.print(f"\n[bold cyan]{renderable.title}[/bold cyan]")

            # Render based on type
            renderer = self.renderers.get(renderable.output_type)
            if renderer:
                output = renderer.render_terminal(renderable.obj, **kwargs)
                if self.console and isinstance(output, str):
                    self.console.print(output)
                elif self.console:
                    self.console.print(output)  # For Rich objects like Table
                else:
                    print(output)
            else:
                # Fallback
                print(str(renderable.obj))

    def _render_html(self, renderables: List[RenderableOutput], **kwargs) -> Union[str, None]:
        """Render as embeddable HTML"""
        return_html = kwargs.get('return_html', True)
        embed_resources = kwargs.get('embed_resources', True)

        html_parts = []

        # Wrapper style
        html_parts.append('''
        <style>
            .ai-output-container {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                max-width: 100%;
                margin: 20px 0;
            }
            .ai-output-item {
                margin: 20px 0;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                overflow: hidden;
            }
            .ai-output-title {
                background-color: #f5f5f5;
                padding: 12px 16px;
                font-weight: 600;
                border-bottom: 1px solid #e0e0e0;
            }
            .ai-output-content {
                padding: 16px;
            }
        </style>
        <div class="ai-output-container">
        ''')

        # Render each item
        for idx, renderable in enumerate(renderables):
            html_parts.append('<div class="ai-output-item">')

            # Title
            if renderable.title:
                html_parts.append(f'<div class="ai-output-title">{renderable.title}</div>')

            html_parts.append('<div class="ai-output-content">')

            # Render
            renderer = self.renderers.get(renderable.output_type)
            if renderer:
                content_html = renderer.render_html(renderable.obj, **kwargs)
                html_parts.append(content_html)
            else:
                # Fallback
                html_parts.append(f'<pre>{str(renderable.obj)}</pre>')

            html_parts.append('</div>')  # content
            html_parts.append('</div>')  # item

        html_parts.append('</div>')  # container

        html = '\n'.join(html_parts)

        if return_html:
            return html
        else:
            # Display if in IPython
            if self._is_ipython:
                from IPython.display import (
                    display, HTML as IPyHTML
                )
                display(IPyHTML(html))
            else:
                print("HTML mode requires return_html=True outside of Jupyter")

    def _render_jupyter(self, renderables: List[RenderableOutput], **kwargs) -> None:
        """Render for Jupyter notebook"""
        from IPython.display import (
            display, Markdown as IPyMarkdown,
        )
        for renderable in renderables:
            # Title
            if renderable.title:
                display(IPyMarkdown(f"### {renderable.title}"))

            # Render
            renderer = self.renderers.get(renderable.output_type)
            if renderer:
                output = renderer.render_jupyter(renderable.obj, **kwargs)
                display(output)
            else:
                # Native Jupyter display
                display(renderable.obj)

    def _render_json(self, renderables: List[RenderableOutput], **kwargs) -> dict:
        """Render as JSON (metadata only)"""
        result = {
            'outputs': [],
            'count': len(renderables)
        }

        for renderable in renderables:
            result['outputs'].append({
                'type': renderable.output_type.value,
                'title': renderable.title,
                'description': renderable.description,
                'has_object': renderable.obj is not None
            })

        return result

    def _extract_content(self, response: Any) -> Any:
        """Extract actual content from response object"""
        # If it's already a visualization object, return as-is
        if any([
            FOLIUM_AVAILABLE and isinstance(response, folium.Map),
            PLOTLY_AVAILABLE and isinstance(response, go.Figure),
            MATPLOTLIB_AVAILABLE and isinstance(response, Figure),
            PANDAS_AVAILABLE and isinstance(response, pd.DataFrame),
        ]):
            return response

        # Try to extract from AI response object
        if hasattr(response, 'output'):
            return response.output
        elif hasattr(response, 'content'):
            return response.content
        elif hasattr(response, 'result'):
            return response.result

        return response

    def _format_jupyter(self, response: Any, **kwargs) -> None:
        """
        Format output specifically for Jupyter notebooks with rich interactive elements.

        Args:
            response: AIMessage response object
            **kwargs: Additional options
                - show_metadata: Show metadata (default: True)
                - show_sources: Show sources (default: True)
                - show_tools: Show tool calls (default: True)
                - show_context: Show context information (default: False)
                - use_widgets: Use interactive widgets (default: True)
                - collapsible: Make sections collapsible (default: True)
                - theme: Color theme ('light' or 'dark', default: 'light')
        """
        if not self._is_ipython:
            print("IPython.display not available. Falling back to plain output.")
            self._plain_print(
                response,
                kwargs.get('show_metadata', True),
                kwargs.get('show_sources', True),
                kwargs.get('show_context', False),
                kwargs.get('show_tools', True)
            )
            return

        show_metadata = kwargs.get('show_metadata', True)
        show_sources = kwargs.get('show_sources', True)
        show_tools = kwargs.get('show_tools', True)
        show_context = kwargs.get('show_context', False)
        use_widgets = kwargs.get('use_widgets', True)
        collapsible = kwargs.get('collapsible', True)
        theme = kwargs.get('theme', 'light')

        content = self._get_content(response)

        if use_widgets and collapsible:
            # Use interactive widgets for a rich experience
            self._display_with_widgets(
                response, content,
                show_metadata, show_sources, show_tools, show_context,
                theme
            )
        else:
            # Use simple IPython.display elements
            self._display_simple_jupyter(
                response, content,
                show_metadata, show_sources, show_tools, show_context,
                theme
            )

    def _display_with_widgets(
        self,
        response: Any,
        content: str,
        show_metadata: bool,
        show_sources: bool,
        show_tools: bool,
        show_context: bool,
        theme: str
    ) -> None:
        """Display response using ipywidgets for interactive experience."""

        try:
            from IPython.display import (
                display, HTML as IPyHTML,
            )
            import ipywidgets as widgets
            from ipywidgets import Accordion
        except ImportError:
            print("ipywidgets not available. Falling back to simple display.")
            self._display_simple_jupyter(
                response, content, show_metadata, show_sources,
                show_tools, show_context, theme
            )
            return

        # Color scheme based on theme
        if theme == 'dark':
            bg_color = '#1e1e1e'
            text_color = '#d4d4d4'
            accent_color = '#007acc'
            border_color = '#3e3e3e'
        else:
            bg_color = '#f8f9fa'
            text_color = '#212529'
            accent_color = '#0066cc'
            border_color = '#dee2e6'

        # Main response display
        response_html = f"""
        <div style="background-color: {bg_color}; padding: 20px; border-radius: 8px;
                    border-left: 4px solid {accent_color}; margin-bottom: 15px;">
            <h3 style="color: {accent_color}; margin-top: 0;">🤖 AI Response</h3>
            <div style="color: {text_color}; line-height: 1.6;">
                {self._markdown_to_html(content)}
            </div>
        </div>
        """
        display(IPyHTML(response_html))

        # Create accordion for additional information
        accordion_items = []

        # Tool calls section
        if show_tools and hasattr(response, 'tool_calls') and response.tool_calls:
            tools_widget = self._create_tools_widget(response.tool_calls, theme)
            accordion_items.append(('🔧 Tool Calls', tools_widget))

        # Metadata section
        if show_metadata:
            metadata_widget = self._create_metadata_widget(response, theme)
            accordion_items.append(('📊 Metadata', metadata_widget))

        # Context section
        if show_context:
            context_widget = self._create_context_widget(response, theme)
            if context_widget:
                accordion_items.append(('🔍 Context', context_widget))

        # Sources section
        if show_sources and hasattr(response, 'source_documents') and response.source_documents:
            sources_widget = self._create_sources_widget(response.source_documents, theme)
            accordion_items.append(('📄 Sources', sources_widget))

        # Display accordion if there are items
        if accordion_items:
            accordion = Accordion(
                children=[item[1] for item in accordion_items],
                titles=[item[0] for item in accordion_items]
            )
            # Close all sections by default
            for i, _ in enumerate(accordion_items):
                accordion.set_title(i, accordion_items[i][0])

            display(accordion)

    def _display_simple_jupyter(
        self,
        response: Any,
        content: str,
        show_metadata: bool,
        show_sources: bool,
        show_tools: bool,
        show_context: bool,
        theme: str
    ) -> None:
        """Display response using simple IPython.display elements without widgets."""

        from IPython.display import (
            display, Markdown as IPyMarkdown, HTML as IPyHTML
        )
        # Display main response with markdown
        display(IPyMarkdown(f"## 🤖 AI Response\n\n{content}"))

        # Tool calls
        if show_tools and hasattr(response, 'tool_calls') and response.tool_calls:
            display(IPyMarkdown("### 🔧 Tool Calls"))
            tools_html = self._create_tools_html_simple(response.tool_calls)
            display(IPyHTML(tools_html))

        # Metadata
        if show_metadata:
            display(IPyMarkdown("### 📊 Metadata"))
            metadata_md = self._create_metadata_markdown(response)
            display(IPyMarkdown(metadata_md))

        # Context
        if show_context:
            context_md = self._create_context_markdown(response)
            if context_md:
                display(IPyMarkdown("### 🔍 Context"))
                display(IPyMarkdown(context_md))

        # Sources
        if show_sources and hasattr(response, 'source_documents') and response.source_documents:
            display(IPyMarkdown("### 📄 Sources"))
            sources_md = self._create_sources_markdown(response.source_documents)
            display(IPyMarkdown(sources_md))

    def _create_tools_widget(self, tool_calls: List[Any], theme: str) -> widgets.Widget:
        """Create widget for tool calls."""
        rows = []
        for idx, tool in enumerate(tool_calls, 1):
            name = getattr(tool, 'name', 'Unknown')
            status = getattr(tool, 'status', 'completed')

            status_color = '#28a745' if status == 'completed' else '#dc3545'
            row_html = f"""
            <div style="padding: 10px; margin: 5px 0; border: 1px solid #ddd; border-radius: 4px;">
                <strong>{idx}. {name}</strong>
                <span style="color: {status_color}; float: right;">● {status}</span>
            </div>
            """
            rows.append(row_html)

        html_content = ''.join(rows)
        return widgets.HTML(value=html_content)

    def _create_metadata_widget(self, response: Any, theme: str) -> widgets.Widget:
        """Create widget for metadata."""
        metadata_items = []

        if hasattr(response, 'model'):
            metadata_items.append(f"**Model:** {response.model}")
        if hasattr(response, 'provider'):
            metadata_items.append(f"**Provider:** {response.provider}")
        if hasattr(response, 'usage') and response.usage:
            if hasattr(response.usage, 'total_tokens'):
                metadata_items.append(f"**Total Tokens:** {response.usage.total_tokens}")
            if hasattr(response.usage, 'prompt_tokens'):
                metadata_items.append(f"**Prompt Tokens:** {response.usage.prompt_tokens}")
            if hasattr(response.usage, 'completion_tokens'):
                metadata_items.append(f"**Completion Tokens:** {response.usage.completion_tokens}")
        if hasattr(response, 'response_time') and response.response_time:
            metadata_items.append(f"**Response Time:** {response.response_time:.2f}s")

        html_content = '<br>'.join(metadata_items)
        return widgets.HTML(value=html_content)

    def _create_context_widget(self, response: Any, theme: str) -> Optional[widgets.Widget]:
        """Create widget for context information."""
        context_items = []

        if hasattr(response, 'used_vector_context'):
            status = "✓ Used" if response.used_vector_context else "✗ Not used"
            context_items.append(f"**Vector Context:** {status}")
            if response.used_vector_context:
                if hasattr(response, 'vector_context_length'):
                    context_items.append(f"  - Length: {response.vector_context_length}")
                if hasattr(response, 'search_type'):
                    context_items.append(f"  - Search Type: {response.search_type}")

        if hasattr(response, 'used_conversation_history'):
            status = "✓ Used" if response.used_conversation_history else "✗ Not used"
            context_items.append(f"**Conversation History:** {status}")

        if not context_items:
            return None

        html_content = '<br>'.join(context_items)
        return widgets.HTML(value=html_content)

    def _create_sources_widget(self, sources: List[Any], theme: str) -> widgets.Widget:
        """Create widget for sources."""
        rows = []
        for idx, source in enumerate(sources, 1):
            source_name = getattr(source, 'source', 'Unknown') if hasattr(source, 'source') else source.get('source', 'Unknown')
            score = getattr(source, 'score', 'N/A') if hasattr(source, 'score') else source.get('score', 'N/A')
            score_str = f"{score:.4f}" if isinstance(score, float) else str(score)

            # Color code by score
            if isinstance(score, float):
                if score > 0.8:
                    score_color = '#28a745'
                elif score > 0.6:
                    score_color = '#ffc107'
                else:
                    score_color = '#dc3545'
            else:
                score_color = '#6c757d'

            row_html = f"""
            <div style="padding: 10px; margin: 5px 0; border: 1px solid #ddd; border-radius: 4px;">
                <strong>{idx}.</strong> {source_name}
                <span style="color: {score_color}; float: right;">Score: {score_str}</span>
            </div>
            """
            rows.append(row_html)

        html_content = ''.join(rows)
        return widgets.HTML(value=html_content)

    def _create_tools_html_simple(self, tool_calls: List[Any]) -> str:
        """Create simple HTML table for tool calls."""
        html = '<table style="width:100%; border-collapse: collapse;">'
        html += '<tr style="background-color: #f0f0f0;"><th style="padding: 8px;">#</th><th style="padding: 8px;">Tool</th><th style="padding: 8px;">Status</th></tr>'

        for idx, tool in enumerate(tool_calls, 1):
            name = getattr(tool, 'name', 'Unknown')
            status = getattr(tool, 'status', 'completed')
            html += f'<tr><td style="padding: 8px;">{idx}</td><td style="padding: 8px;">{name}</td><td style="padding: 8px;">{status}</td></tr>'

        html += '</table>'
        return html

    def _create_metadata_markdown(self, response: Any) -> str:
        """Create markdown for metadata."""
        lines = []
        if hasattr(response, 'model'):
            lines.append(f"- **Model:** {response.model}")
        if hasattr(response, 'provider'):
            lines.append(f"- **Provider:** {response.provider}")
        if hasattr(response, 'usage') and response.usage:
            if hasattr(response.usage, 'total_tokens'):
                lines.append(f"- **Total Tokens:** {response.usage.total_tokens}")
        if hasattr(response, 'response_time') and response.response_time:
            lines.append(f"- **Response Time:** {response.response_time:.2f}s")
        return '\n'.join(lines)

    def _create_context_markdown(self, response: Any) -> Optional[str]:
        """Create markdown for context information."""
        lines = []

        if hasattr(response, 'used_vector_context'):
            status = "✓ Used" if response.used_vector_context else "✗ Not used"
            lines.append(f"**Vector Context:** {status}")

        if hasattr(response, 'used_conversation_history'):
            status = "✓ Used" if response.used_conversation_history else "✗ Not used"
            lines.append(f"**Conversation History:** {status}")

        return '\n'.join(lines) if lines else None

    def _create_sources_markdown(self, sources: List[Any]) -> str:
        """Create markdown table for sources."""
        lines = ["| # | Source | Score |", "| --- | --- | --- |"]

        for idx, source in enumerate(sources, 1):
            source_name = getattr(source, 'source', 'Unknown') if hasattr(source, 'source') else source.get('source', 'Unknown')
            score = getattr(source, 'score', 'N/A') if hasattr(source, 'score') else source.get('score', 'N/A')
            score_str = f"{score:.4f}" if isinstance(score, float) else str(score)
            lines.append(f"| {idx} | {source_name} | {score_str} |")

        return '\n'.join(lines)

    def _markdown_to_html(self, markdown_text: str) -> str:
        """Convert markdown to HTML (simple implementation)."""
        try:
            return markdown.markdown(markdown_text, extensions=['fenced_code', 'tables'])
        except ImportError:
            # Fallback: basic conversion
            html = markdown_text.replace('\n\n', '</p><p>')
            html = html.replace('\n', '<br>')
            html = f'<p>{html}</p>'
            # Handle code blocks
            html = re.sub(r'```(\w+)?\n(.*?)```', r'<pre><code>\2</code></pre>', html, flags=re.DOTALL)
            return html

    def _get_content(self, response: Any) -> str:
        """Extract content from response safely."""
        if hasattr(response, 'content'):
            return response.content
        elif hasattr(response, 'to_text'):
            return response.to_text
        elif hasattr(response, 'output'):
            output = response.output
            if isinstance(output, str):
                return output
            return str(output)
        elif hasattr(response, 'response'):
            return response.response or ""
        return str(response)

    def _get_content(self, response: Any) -> str:
        """
        Extract content from response safely.

        Args:
            response: AIMessage response object

        Returns:
            String content from the response
        """
        # Try response property first (if added to AIMessage)
        if hasattr(response, 'response'):
            return response.response or response.output
        if hasattr(response, 'content'):
            return response.content
        # Try to_text property
        if hasattr(response, 'to_text'):
            return response.to_text
        # Try output attribute
        if hasattr(response, 'output'):
            output = response.output
            return output if isinstance(output, str) else str(output)
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

    def _fallback_print(
        self,
        response: Any,
        show_metadata: bool,
        show_sources: bool,
        show_context: bool,
        show_tools: bool
    ) -> None:
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
            return self._format_html_simple(response, **kwargs)

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

        # Convert to HTML string if requested
        if return_html:
            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as tmp:
                tmp_path = tmp.name

            try:
                # Save Panel dashboard to HTML file
                dashboard.save(tmp_path, embed=True)

                # Read the HTML content
                with open(tmp_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()

                return html_content
            finally:
                # Clean up temporary file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        # Return Panel object for interactive use
        return dashboard

    def _format_html_simple(self, response: Any, **kwargs) -> str:
        """
        Format output as HTML without Panel (manual construction).
        Faster and simpler for basic HTML export.

        Args:
            response: AIMessage response object
            **kwargs: Additional options

        Returns:
            HTML string
        """
        show_metadata = kwargs.get('show_metadata', True)
        show_sources = kwargs.get('show_sources', True)
        show_tools = kwargs.get('show_tools', False)

        html_parts = []

        # Add CSS
        html_parts.append('''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    max-width: 1200px;
                    margin: 20px auto;
                    padding: 20px;
                    background-color: #f5f5f5;
                }
                .response-container {
                    background-color: #f0f8ff;
                    padding: 20px;
                    border-radius: 5px;
                    margin-bottom: 20px;
                }
                .response-container h2 {
                    margin-top: 0;
                    color: #333;
                }
                .section {
                    background-color: white;
                    padding: 15px;
                    border-radius: 5px;
                    margin-bottom: 15px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }
                .section h3 {
                    margin-top: 0;
                    color: #555;
                }
                table {
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 10px;
                }
                th, td {
                    padding: 8px;
                    text-align: left;
                    border-bottom: 1px solid #ddd;
                }
                th {
                    background-color: #f0f0f0;
                    font-weight: bold;
                }
                tr:nth-child(even) {
                    background-color: #f9f9f9;
                }
            </style>
        </head>
        <body>
        ''')

        # Main response
        content = self._get_content(response)
        if content:
            # Convert markdown to HTML if needed
            html_content = self._markdown_to_html(content)
            html_parts.append(f'''
            <div class="response-container">
                <h2>🤖 Response</h2>
                <div>{html_content}</div>
            </div>
            ''')

        # Tool calls section
        if show_tools and hasattr(response, 'tool_calls') and response.tool_calls:
            tools_html = self._create_tools_html(response.tool_calls)
            html_parts.append(f'''
            <div class="section">
                <h3>🔧 Tool Calls</h3>
                {tools_html}
            </div>
            ''')

        # Metadata section
        if show_metadata:
            metadata_html = self._create_metadata_html(response)
            html_parts.append(f'''
            <div class="section">
                <h3>📊 Metadata</h3>
                {metadata_html}
            </div>
            ''')

        # Sources section
        if show_sources and hasattr(response, 'source_documents') and response.source_documents:
            sources_html = self._create_sources_html(response.source_documents)
            html_parts.append(f'''
            <div class="section">
                <h3>📄 Sources</h3>
                {sources_html}
            </div>
            ''')

        html_parts.append('</body></html>')

        return '\n'.join(html_parts)

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

    def _get_tool_output(self, tool_result: Any) -> Any:
        """Extract tool output safely."""
        if tool_result is None:
            return None
        if isinstance(tool_result, str):
            return tool_result
        if hasattr(tool_result, 'to_text'):
            return tool_result.to_text
        if isinstance(tool_result, pd.DataFrame):
            return tool_result.to_dict(orient='records')
        if hasattr(tool_result, 'output'):
            output = tool_result.output
            return output if isinstance(output, str) else str(output)
        if hasattr(tool_result, 'result'):
            return str(tool_result.result)
        return str(tool_result)

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
            'input': getattr(response, 'input', None),
            "output": getattr(response, 'output', None),
            'response': self._get_content(response),
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
                    'status': getattr(tool, 'status', 'completed'),
                    'arguments': json_encoder(getattr(tool, 'arguments', {})),
                    'output': self._get_tool_output(tool.result),
                }
                for tool in response.tool_calls
            ]
        # Processing Source Documents:
        if hasattr(response, 'source_documents') and response.source_documents:
            result['source_documents'] = [
                {
                    **doc
                }
                for doc in response.source_documents
            ]
        if hasattr(response, 'context_summary'):
            result['context'] = response.context_summary

        # Also show all files if available:
        if hasattr(response, 'files') and response.files:
            # response.files is a list of files:
            result['files'] = [json_encoder(f) for f in response.files]

        if kwargs.get('pretty', False):
            if RICH_AVAILABLE and self.console:
                self.console.print(JSON(json_encoder(result)))
            else:
                print(json.dumps(result, indent=2))

        return result

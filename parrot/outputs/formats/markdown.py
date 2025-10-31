# parrot/outputs/formats/markdown.py
from typing import Any, Optional
import html as html_module
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode

# Check dependencies
try:
    from rich.console import Console
    from rich.markdown import Markdown as RichMarkdown
    from rich.panel import Panel as RichPanel
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    from ipywidgets import HTML as IPyHTML
    IPYWIDGETS_AVAILABLE = True
except ImportError:
    IPYWIDGETS_AVAILABLE = False

try:
    import panel as pn
    from panel.pane import Markdown as PanelMarkdown
    PANEL_AVAILABLE = True
except ImportError:
    PANEL_AVAILABLE = False

try:
    from IPython.display import Markdown as IPythonMarkdown, display
    IPYTHON_AVAILABLE = True
except ImportError:
    IPYTHON_AVAILABLE = False


@register_renderer(OutputMode.MARKDOWN)
class MarkdownRenderer(BaseRenderer):
    """Renderer for Markdown with environment-specific formatting"""

    @staticmethod
    def render(response: Any, **kwargs) -> Any:
        """
        Render markdown content.

        Args:
            response: AIMessage with markdown content
            **kwargs:
                - format: 'plain', 'terminal', 'jupyter', 'panel' (auto-detect by default)
                - environment: Execution environment ('jupyter', 'terminal', 'colab')
                - show_panel: Wrap in Rich Panel for terminal (default: True)
                - panel_title: Title for Rich Panel (default: "📝 Markdown")
                - theme: Syntax highlighting theme for code blocks

        Returns:
            String (plain/terminal) or widget (jupyter)
        """
        # Get markdown content
        content = MarkdownRenderer._get_content(response)

        # Determine format
        format_type = kwargs.get('format')
        environment = kwargs.get('environment', 'terminal')

        # Auto-detect format if not specified
        if not format_type:
            format_type = MarkdownRenderer._auto_detect_format(environment)

        # Route to appropriate renderer
        if format_type == 'plain':
            return MarkdownRenderer._render_plain(content)

        elif format_type == 'terminal':
            return MarkdownRenderer._render_terminal(content, **kwargs)

        elif format_type == 'jupyter':
            return MarkdownRenderer._render_jupyter(content, **kwargs)

        elif format_type == 'panel':
            return MarkdownRenderer._render_panel(content, **kwargs)

        else:
            # Fallback to plain
            return content

    @staticmethod
    def _auto_detect_format(environment: str) -> str:
        """Auto-detect best format based on environment."""
        if environment in ('jupyter', 'colab'):
            # Prefer Panel if available, otherwise IPython
            if PANEL_AVAILABLE:
                return 'panel'
            elif IPYTHON_AVAILABLE:
                return 'jupyter'
            else:
                return 'plain'
        else:
            # Terminal
            if RICH_AVAILABLE:
                return 'terminal'
            else:
                return 'plain'

    @staticmethod
    def _render_plain(content: str) -> str:
        """Render as plain markdown text."""
        return content

    @staticmethod
    def _render_terminal(content: str, **kwargs) -> str:
        """Render using Rich for terminal display."""
        if not RICH_AVAILABLE:
            return content

        show_panel = kwargs.get('show_panel', True)
        panel_title = kwargs.get('panel_title', "📝 Markdown")

        console = Console(force_terminal=True)
        md = RichMarkdown(content)

        with console.capture() as capture:
            if show_panel:
                console.print(
                    RichPanel(
                        md,
                        title=panel_title,
                        border_style="blue",
                        expand=False
                    )
                )
            else:
                console.print(md)

        return capture.get()

    @staticmethod
    def _render_jupyter(content: str, **kwargs) -> Any:
        """Render using IPython.display.Markdown or ipywidgets."""
        use_widget = kwargs.get('use_widget', False)

        if use_widget and IPYWIDGETS_AVAILABLE:
            # Render as HTML widget with syntax highlighting
            html_content = MarkdownRenderer._markdown_to_html(content)
            return IPyHTML(value=html_content)

        elif IPYTHON_AVAILABLE:
            # Use IPython's native Markdown display
            return IPythonMarkdown(content)

        else:
            # Fallback to plain
            return content

    @staticmethod
    def _render_panel(content: str, **kwargs) -> Any:
        """Render using Panel for interactive Jupyter display."""
        if not PANEL_AVAILABLE:
            # Fallback to IPython
            return MarkdownRenderer._render_jupyter(content, **kwargs)

        styles = kwargs.get('styles', {
            'background': '#f9f9f9',
            'padding': '20px',
            'border-radius': '5px',
            'box-shadow': '0 2px 4px rgba(0,0,0,0.1)'
        })

        return PanelMarkdown(
            content,
            sizing_mode='stretch_width',
            styles=styles
        )

    @staticmethod
    def _markdown_to_html(content: str) -> str:
        """Convert markdown to HTML with syntax highlighting."""
        try:
            import markdown
            from markdown.extensions.codehilite import CodeHiliteExtension
            from markdown.extensions.fenced_code import FencedCodeExtension

            html = markdown.markdown(
                content,
                extensions=[
                    'fenced_code',
                    'tables',
                    'nl2br',
                    CodeHiliteExtension(
                        css_class='highlight',
                        linenums=False
                    )
                ]
            )

            # Wrap with styles
            return f'''
            <style>
                .markdown-content {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    background: white;
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                }}
                .markdown-content h1, .markdown-content h2, .markdown-content h3 {{
                    color: #2c3e50;
                    margin-top: 1.5em;
                    margin-bottom: 0.5em;
                }}
                .markdown-content code {{
                    background: #f4f4f4;
                    padding: 2px 6px;
                    border-radius: 3px;
                    font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
                    font-size: 0.9em;
                }}
                .markdown-content pre {{
                    background: #2d2d2d;
                    color: #f8f8f2;
                    padding: 15px;
                    border-radius: 5px;
                    overflow-x: auto;
                }}
                .markdown-content pre code {{
                    background: transparent;
                    color: inherit;
                    padding: 0;
                }}
                .markdown-content blockquote {{
                    border-left: 4px solid #667eea;
                    margin: 10px 0;
                    padding-left: 15px;
                    color: #666;
                    font-style: italic;
                }}
                .markdown-content table {{
                    border-collapse: collapse;
                    width: 100%;
                    margin: 1em 0;
                }}
                .markdown-content th, .markdown-content td {{
                    border: 1px solid #ddd;
                    padding: 8px;
                    text-align: left;
                }}
                .markdown-content th {{
                    background-color: #667eea;
                    color: white;
                }}
            </style>
            <div class="markdown-content">
                {html}
            </div>
            '''

        except ImportError:
            # Fallback: basic HTML conversion
            escaped = html_module.escape(content)
            return f'<pre style="white-space: pre-wrap;">{escaped}</pre>'

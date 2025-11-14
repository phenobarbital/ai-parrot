from typing import Any, Optional, Tuple
import html as html_module
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode

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
    from IPython.display import Markdown as IPythonMarkdown
    IPYTHON_AVAILABLE = True
except ImportError:
    IPYTHON_AVAILABLE = False


@register_renderer(OutputMode.MARKDOWN)
class MarkdownRenderer(BaseRenderer):
    """Renderer for Markdown with environment-specific formatting"""

    async def render(
        self,
        response: Any,
        **kwargs,
    ) -> Tuple[str, Any]:
        """
        Render markdown content.
        """
        content = self._get_content(response)
        environment = kwargs.get('environment', 'terminal')
        format_type = kwargs.get('format')

        if not format_type:
            format_type = self._auto_detect_format(environment)

        if format_type == 'plain':
            wrapped_output = self._render_plain(content)
        elif format_type == 'terminal':
            wrapped_output = self._render_terminal(content, **kwargs)
        elif format_type == 'jupyter':
            wrapped_output = self._render_jupyter(content, **kwargs)
        elif format_type == 'panel':
            wrapped_output = self._render_panel(content, **kwargs)
        elif format_type == 'html':
            wrapped_output = self._markdown_to_html(content)
        else:
            wrapped_output = content

        return content, wrapped_output

    def _auto_detect_format(self, environment: str) -> str:
        """Auto-detect best format based on environment."""
        if environment in ('jupyter', 'colab'):
            if PANEL_AVAILABLE:
                return 'panel'
            elif IPYTHON_AVAILABLE:
                return 'jupyter'
            else:
                return 'html'
        elif environment == 'html':
            return 'html'
        else:  # terminal
            return 'terminal' if RICH_AVAILABLE else 'plain'

    def _render_plain(self, content: str) -> str:
        """Render as plain markdown text."""
        return content

    def _render_terminal(self, content: str, **kwargs) -> str:
        """Render using Rich for terminal display."""
        if not RICH_AVAILABLE:
            return content

        show_panel = kwargs.get('show_panel', True)
        panel_title = kwargs.get('panel_title', "📝 Markdown")
        console = Console(force_terminal=True)
        md = RichMarkdown(content)

        with console.capture() as capture:
            if show_panel:
                console.print(RichPanel(md, title=panel_title, border_style="blue", expand=False))
            else:
                console.print(md)
        return capture.get()

    def _render_jupyter(self, content: str, **kwargs) -> Any:
        """Render using IPython.display.Markdown or ipywidgets."""
        use_widget = kwargs.get('use_widget', False)

        if use_widget and IPYWIDGETS_AVAILABLE:
            html_content = self._markdown_to_html(content)
            return IPyHTML(value=html_content)
        elif IPYTHON_AVAILABLE:
            return IPythonMarkdown(content)
        else:
            return content

    def _render_panel(self, content: str, **kwargs) -> Any:
        """Render using Panel for interactive Jupyter display."""
        if not PANEL_AVAILABLE:
            return self._render_jupyter(content, **kwargs)

        styles = kwargs.get('styles', {
            'background': '#f9f9f9', 'padding': '20px', 'border-radius': '5px',
            'box-shadow': '0 2px 4px rgba(0,0,0,0.1)'
        })
        return PanelMarkdown(content, sizing_mode='stretch_width', styles=styles)

    def _markdown_to_html(self, content: str) -> str:
        """Convert markdown to HTML with syntax highlighting."""
        try:
            import markdown
            from markdown.extensions.codehilite import CodeHiliteExtension

            html = markdown.markdown(
                content,
                extensions=[
                    'fenced_code', 'tables', 'nl2br',
                    CodeHiliteExtension(css_class='highlight', linenums=False)
                ]
            )
            return f'''
            <style>
                .markdown-content {{ line-height: 1.6; }}
                .markdown-content h1, .markdown-content h2, .markdown-content h3 {{ margin-top: 1.5em; }}
                .markdown-content code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }}
                .markdown-content pre {{ background: #2d2d2d; color: #f8f8f2; padding: 15px; border-radius: 5px; }}
            </style>
            <div class="markdown-content">{html}</div>
            '''
        except ImportError:
            escaped = html_module.escape(content)
            return f'<pre style="white-space: pre-wrap;">{escaped}</pre>'

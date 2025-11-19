from typing import Any, Optional, Tuple
import html as html_module
import markdown
from markdown.extensions.codehilite import CodeHiliteExtension
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
    """
    Renderer for Markdown output.
    Handles PandasAgentResponse (explanation), AIMessage, and generic text.
    Adapts output format to Terminal (Rich), HTML, Jupyter, and Panel.
    """
    def _extract_content(self, response: Any) -> str:
        """
        Extract Markdown text content based on response type rules.
        """
        # 1. Check for PandasAgentResponse (duck typing)
        # We check for specific attributes that define a PandasAgentResponse
        output = getattr(response, 'output', None)

        if output is not None:
            # Handle PandasAgentResponse: The 'explanation' is usually the markdown text
            if hasattr(output, 'explanation') and output.explanation:
                return str(output.explanation)

            # If it has a 'response' attribute (some agent responses)
            if hasattr(output, 'response') and output.response:
                return str(output.response)

        # 2. Check standard AIMessage response text
        if hasattr(response, 'response') and response.response:
            return str(response.response)

        # 3. Fallback: Use output if string, or stringify
        if output is not None:
            return output if isinstance(output, str) else str(output)

        # 4. Last resort: stringify the whole response object
        return str(response)

    async def render(
        self,
        response: Any,
        environment: str = 'terminal',
        **kwargs,
    ) -> Tuple[str, Any]:
        """
        Render markdown content.
        """
        # 1. Extract Content
        content = self._extract_content(response)

        # 2. Determine Format
        # Allow overriding format via kwargs, else default to environment
        output_format = kwargs.get('format') or kwargs.get('output_format', environment)

        # 3. Wrap content based on environment/format
        wrapped_output = self._wrap_output(content, output_format, **kwargs)

        return content, wrapped_output

    def _wrap_output(self, content: str, environment: str, **kwargs) -> Any:
        """
        Wrap the Markdown content into an environment-specific container.
        """
        # --- Terminal (Rich) ---
        if environment == 'terminal':
            if RICH_AVAILABLE:
                show_panel = kwargs.get('show_panel', True)
                panel_title = kwargs.get('panel_title', "📝 Response")

                console = Console(force_terminal=True)
                md = RichMarkdown(content)

                # Capture rich output to string/object
                with console.capture() as capture:
                    if show_panel:
                        console.print(RichPanel(md, title=panel_title, border_style="blue", expand=False))
                    else:
                        console.print(md)
                return capture.get()
            return content

        # --- Jupyter / Notebook ---
        elif environment in ('jupyter', 'notebook', 'colab'):
            # Priority 1: Panel (if requested or available and appropriate)
            if environment == 'panel' or (kwargs.get('use_panel', False) and PANEL_AVAILABLE):
                styles = kwargs.get('styles', {
                    'background': '#f9f9f9', 'padding': '20px', 'border-radius': '5px',
                    'box-shadow': '0 2px 4px rgba(0,0,0,0.1)'
                })
                return PanelMarkdown(content, sizing_mode='stretch_width', styles=styles)

            # Priority 2: IPyWidgets (if interactive requested)
            use_widget = kwargs.get('use_widget', False)
            if use_widget and IPYWIDGETS_AVAILABLE:
                html_content = self._markdown_to_html(content)
                return IPyHTML(value=html_content)

            # Priority 3: Standard IPython Display
            if IPYTHON_AVAILABLE:
                return IPythonMarkdown(content)

            # Fallback
            return self._markdown_to_html(content)

        # --- HTML ---
        elif environment == 'html':
            return self._markdown_to_html(content)

        # --- Default / Plain ---
        return content

    def _markdown_to_html(self, content: str) -> str:
        """Convert markdown to HTML with syntax highlighting."""
        try:
            html = markdown.markdown(
                content,
                extensions=[
                    'fenced_code', 'tables', 'nl2br',
                    CodeHiliteExtension(css_class='highlight', linenums=False)
                ]
            )
            # Add basic styling for the HTML output
            return f'''
            <div class="markdown-content" style="line-height: 1.6;">
                <style>
                    .markdown-content h1, .markdown-content h2, .markdown-content h3 {{ margin-top: 1.5em; }}
                    .markdown-content code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-family: monospace; }}
                    .markdown-content pre {{ background: #2d2d2d; color: #f8f8f2; padding: 15px; border-radius: 5px; overflow-x: auto; }}
                    .markdown-content table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
                    .markdown-content th, .markdown-content td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                    .markdown-content th {{ background-color: #f2f2f2; }}
                </style>
                {html}
            </div>
            '''
        except ImportError:
            # Fallback if markdown lib is missing
            escaped = html_module.escape(content)
            return f'<pre style="white-space: pre-wrap; font-family: sans-serif;">{escaped}</pre>'

# parrot/outputs/formats/chart.py
from typing import Any, Optional, Tuple
import re
import base64
from io import BytesIO
from pathlib import Path
import html
from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode

try:
    from ipywidgets import HTML as IPyHTML
    IPYWIDGETS_AVAILABLE = True
except ImportError:
    IPYWIDGETS_AVAILABLE = False


@register_renderer(OutputMode.CHART)
class ChartRenderer(BaseRenderer):
    """Render charts from code or images with optional code display"""

    @staticmethod
    def render(response: Any, **kwargs) -> str:
        """
        Render chart as HTML with optional code display.

        Args:
            response: AIMessage with chart code or image
            **kwargs:
                - return_code: Show code in collapsible section (default: True)
                - execute_code: Execute code to generate chart (default: True)
                - theme: Code highlight theme (default: 'monokai')

        Returns:
            HTML string with embedded chart
        """
        return_code = kwargs.get('return_code', True)
        execute_code = kwargs.get('execute_code', True)
        theme = kwargs.get('theme', 'monokai')
        environment = kwargs.get('environment', 'terminal')

        content = ChartRenderer._get_content(response)

        # Detect response type
        code = ChartRenderer._extract_code(content)
        image_path = ChartRenderer._extract_image_path(response)

        if code and execute_code:
            # Execute code to generate chart
            html_chart, error = ChartRenderer._execute_chart_code(code)
            if error:
                return ChartRenderer._render_error(error, code, theme)
            final_html = ChartRenderer._build_html(html_chart, code if return_code else None, theme)
            if environment in ('jupyter', 'colab') and IPYWIDGETS_AVAILABLE:
                return IPyHTML(value=final_html)

        elif image_path:
            # LLM returned image - embed it
            img_html = ChartRenderer._embed_image(image_path)
            final_html = ChartRenderer._build_html(img_html, code if return_code else None, theme)
            if environment in ('jupyter', 'colab') and IPYWIDGETS_AVAILABLE:
                return IPyHTML(value=final_html)

        else:
            return "<div class='error'>No chart code or image found in response</div>"

    @staticmethod
    def _extract_code(content: str) -> Optional[str]:
        """Extract Python code from markdown code blocks."""
        # Match ```python ... ``` blocks
        pattern = r'```(?:python)?\n(.*?)```'
        matches = re.findall(pattern, content, re.DOTALL)
        return matches[0].strip() if matches else None

    @staticmethod
    def _extract_image_path(response: Any) -> Optional[Path]:
        """Check if response has generated images."""
        if hasattr(response, 'images') and response.images:
            return response.images[0]
        if hasattr(response, 'files') and response.files:
            # Check for image files
            for file in response.files:
                if Path(file).suffix.lower() in ['.png', '.jpg', '.jpeg', '.svg']:
                    return Path(file)
        return None

    @staticmethod
    def _execute_chart_code(code: str) -> Tuple[str, Optional[str]]:
        """Execute code and return HTML representation."""
        try:
            # Create execution namespace
            namespace = {}
            exec(code, namespace)

            # Look for 'fig' variable
            if 'fig' not in namespace:
                return None, "Code must define a 'fig' variable"

            fig = namespace['fig']

            # Convert based on library type
            if hasattr(fig, 'to_html'):  # Plotly
                return fig.to_html(include_plotlyjs='cdn', div_id='chart'), None

            elif hasattr(fig, 'savefig'):  # Matplotlib
                buf = BytesIO()
                fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
                buf.seek(0)
                img_b64 = base64.b64encode(buf.read()).decode()
                return f'<img src="data:image/png;base64,{img_b64}" style="max-width:100%;">', None

            elif hasattr(fig, 'to_json'):  # Altair
                import altair as alt
                return fig.to_html(), None

            elif hasattr(fig, 'output_backend'):  # Bokeh
                from bokeh.embed import file_html
                from bokeh.resources import CDN
                return file_html(fig, CDN, "Chart"), None

            else:
                return None, f"Unsupported figure type: {type(fig)}"

        except Exception as e:
            return None, f"Execution error: {str(e)}"

    @staticmethod
    def _embed_image(image_path: Path) -> str:
        """Embed image as base64 data URL."""
        try:
            with open(image_path, 'rb') as f:
                img_data = base64.b64encode(f.read()).decode()

            ext = image_path.suffix.lower()
            mime_type = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.svg': 'image/svg+xml'
            }.get(ext, 'image/png')

            return f'<img src="data:{mime_type};base64,{img_data}" style="max-width:100%; height:auto;">'
        except Exception as e:
            return f'<div class="error">Failed to load image: {e}</div>'

    @staticmethod
    def _build_html(chart_html: str, code: Optional[str], theme: str) -> str:
        """Build final HTML with chart and optional code."""
        html_parts = [ChartRenderer._get_html_styles()]

        # Chart container
        html_parts.append(f'''
        <div class="chart-container">
            <div class="chart-wrapper">
                {chart_html}
            </div>
        </div>
        ''')

        # Code section (collapsible)
        if code:
            highlighted_code = ChartRenderer._highlight_code(code, theme)
            html_parts.append(f'''
            <details class="code-accordion">
                <summary class="code-header">
                    <span>📝 View Python Code</span>
                    <span class="toggle-icon">▶</span>
                </summary>
                <div class="code-content">
                    {highlighted_code}
                </div>
            </details>
            ''')

        return '\n'.join(html_parts)

    @staticmethod
    def _highlight_code(code: str, theme: str = 'monokai') -> str:
        """Apply syntax highlighting to code."""
        try:
            from pygments import highlight
            from pygments.lexers import PythonLexer
            from pygments.formatters import HtmlFormatter

            formatter = HtmlFormatter(style=theme, noclasses=True, cssclass='code')
            return highlight(code, PythonLexer(), formatter)
        except ImportError:
            # Fallback: basic HTML escaping
            escaped = html.escape(code)
            return f'<pre class="code"><code>{escaped}</code></pre>'

    @staticmethod
    def _render_error(error: str, code: str, theme: str) -> str:
        """Render error message with code."""
        highlighted = ChartRenderer._highlight_code(code, theme)
        return f'''
        {ChartRenderer._get_html_styles()}
        <div class="error-container">
            <h3>⚠️ Chart Generation Error</h3>
            <p class="error-message">{error}</p>
            <details class="code-accordion" open>
                <summary class="code-header">Code with Error</summary>
                <div class="code-content">{highlighted}</div>
            </details>
        </div>
        '''

    @staticmethod
    def _get_html_styles() -> str:
        """Get CSS styles for chart rendering."""
        return '''
        <style>
            .chart-container {
                background: white;
                border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                padding: 20px;
                margin: 20px 0;
            }
            .chart-wrapper {
                min-height: 400px;
                display: flex;
                justify-content: center;
                align-items: center;
            }
            .code-accordion {
                margin-top: 20px;
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                overflow: hidden;
            }
            .code-header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 12px 20px;
                cursor: pointer;
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-weight: 600;
                user-select: none;
            }
            .code-header:hover {
                background: linear-gradient(135deg, #5568d3 0%, #653a8e 100%);
            }
            .toggle-icon {
                transition: transform 0.3s ease;
            }
            details[open] .toggle-icon {
                transform: rotate(90deg);
            }
            .code-content {
                background: #272822;
                padding: 15px;
                overflow-x: auto;
            }
            .code-content pre {
                margin: 0;
                font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
                font-size: 13px;
                line-height: 1.5;
            }
            .error-container {
                background: #fff3cd;
                border: 1px solid #ffc107;
                border-radius: 8px;
                padding: 20px;
                margin: 20px 0;
            }
            .error-message {
                color: #856404;
                font-weight: 500;
                margin: 10px 0;
            }
        </style>
        '''

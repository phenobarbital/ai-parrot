# parrot/outputs/formats/chart.py
from typing import Any, Optional, Tuple
import re
import base64
from io import BytesIO
from pathlib import Path
from bokeh.embed import file_html
from bokeh.resources import CDN
from . import register_renderer
from .base import BaseChart
from .altair import AltairRenderer
from ...models.outputs import OutputMode


@register_renderer(OutputMode.CHART)
class ChartRenderer(BaseChart):
    """Main chart renderer that delegates to specific implementations"""

    # Library-specific renderers
    RENDERERS = {
        'altair': AltairRenderer(),
    }

    def render(self, response: Any, **kwargs) -> Any:
        """Render chart with auto-detection or explicit library."""
        library = kwargs.get('library')
        export_format = kwargs.get('export_format', 'html')
        return_code = kwargs.get('return_code', True)
        execute_code = kwargs.get('execute_code', True)
        theme = kwargs.get('theme', 'monokai')
        environment = kwargs.get('environment', 'terminal')

        content = self._get_content(response)

        # Auto-detect library
        if not library:
            library = self._detect_library(content)

        # Delegate to Altair renderer
        if library == 'altair':
            renderer = self.RENDERERS['altair']
            return renderer.render(
                response,
                export_format=export_format,
                return_code=return_code,
                theme=theme,
                environment=environment,
                **kwargs
            )

        # Generic rendering for other libraries
        return self._render_generic(
            content,
            library,
            return_code,
            execute_code,
            theme,
            environment
        )

    @staticmethod
    def _detect_library(content: str) -> str:
        """Auto-detect charting library from imports."""
        if 'import altair' in content or 'from altair' in content:
            return 'altair'
        elif 'import plotly' in content or 'from plotly' in content:
            return 'plotly'
        elif 'import matplotlib' in content or 'from matplotlib' in content:
            return 'matplotlib'
        elif 'import bokeh' in content or 'from bokeh' in content:
            return 'bokeh'
        return 'unknown'

    def _render_generic(
        self,
        content: str,
        library: str,
        return_code: bool,
        execute_code: bool,
        theme: str,
        environment: str
    ) -> Any:
        """Generic rendering for non-Altair charts."""
        code = self._extract_code(content)
        if not code:
            return "<div class='error'>No chart code found</div>"

        if not execute_code:
            return f"<pre>{code}</pre>"

        html_chart, error = self._execute_generic_code(code)

        if error:
            return self._render_error(error, code, theme)

        # Build HTML
        parts = [self._get_chart_styles()]
        parts.append(f'<div class="chart-container">{html_chart}</div>')

        if return_code:
            parts.append(self._build_code_section(code, theme, "📊"))

        final_html = '\n'.join(parts)
        return self._wrap_for_environment(final_html, environment)

    def execute_code(self, code: str) -> Tuple[Any, Optional[str]]:
        """Required by BaseChart abstract method."""
        return self._execute_generic_code(code)

    def to_html(self, chart_obj: Any, **kwargs) -> str:
        """Required by BaseChart abstract method."""
        # Generic HTML conversion
        if hasattr(chart_obj, 'to_html'):
            return chart_obj.to_html(include_plotlyjs='cdn')
        elif hasattr(chart_obj, 'savefig'):
            buf = BytesIO()
            chart_obj.savefig(buf, format='png', bbox_inches='tight', dpi=150)
            buf.seek(0)
            img_b64 = base64.b64encode(buf.read()).decode()
            return f'<img src="data:image/png;base64,{img_b64}">'
        return str(chart_obj)

    @staticmethod
    def _execute_generic_code(code: str) -> Tuple[str, Optional[str]]:
        """Execute code for Plotly/Matplotlib/Bokeh."""
        try:
            namespace = {}
            exec(code, namespace)

            fig = next(
                (
                    namespace[var_name]
                    for var_name in ['fig', 'figure', 'chart', 'plot']
                    if var_name in namespace
                ),
                None,
            )

            if fig is None:
                return None, "Code must define a 'fig' variable"

            if hasattr(fig, 'to_html'):  # Plotly
                return fig.to_html(include_plotlyjs='cdn', div_id='chart'), None

            elif hasattr(fig, 'savefig'):  # Matplotlib
                buf = BytesIO()
                fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
                buf.seek(0)
                img_b64 = base64.b64encode(buf.read()).decode()
                return f'<img src="data:image/png;base64,{img_b64}">', None

            elif hasattr(fig, 'output_backend'):  # Bokeh
                return file_html(fig, CDN, "Chart"), None

            return None, f"Unsupported figure type: {type(fig)}"

        except Exception as e:
            return None, f"Execution error: {str(e)}"

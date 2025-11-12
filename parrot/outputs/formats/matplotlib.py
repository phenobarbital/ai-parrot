from typing import Any, Optional, Tuple, Dict
import io
import base64
import uuid
from .base import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode


MATPLOTLIB_SYSTEM_PROMPT = """MATPLOTLIB CHART OUTPUT MODE:
Generate a chart using Matplotlib.

REQUIREMENTS:
1. Return Python code in a markdown code block (```python)
2. Use matplotlib.pyplot (import matplotlib.pyplot as plt)
3. Store the figure in a variable named 'fig' or use plt.gcf()
4. Make the chart self-contained with inline data
5. Use appropriate plot types (plot, bar, scatter, hist, pie, etc.)
6. Add titles, labels, legends, and grid for clarity
7. Use plt.tight_layout() for better spacing
8. DO NOT call plt.show() or save files - return code only

EXAMPLE:
```python
import matplotlib.pyplot as plt
import numpy as np

categories = ['A', 'B', 'C', 'D']
values = [23, 45, 12, 67]

fig, ax = plt.subplots(figsize=(10, 6))
ax.bar(categories, values, color='steelblue')
ax.set_title('Sales by Category', fontsize=16, fontweight='bold')
ax.set_xlabel('Category')
ax.set_ylabel('Sales')
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
```
"""


@register_renderer(OutputMode.MATPLOTLIB, system_prompt=MATPLOTLIB_SYSTEM_PROMPT)
class MatplotlibRenderer(BaseChart):
    """Renderer for Matplotlib charts"""

    def execute_code(self, code: str) -> Tuple[Any, Optional[str]]:
        """Execute Matplotlib code and return figure object."""
        try:
            # Import matplotlib with non-interactive backend
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt

            namespace = {'plt': plt, 'matplotlib': matplotlib}
            exec(code, namespace)

            # Try to find figure
            fig = namespace.get('fig') or namespace.get('figure')

            # If not found, try to get current figure
            if fig is None:
                fig = plt.gcf()

            if fig is None or not hasattr(fig, 'savefig'):
                return None, "Code must create a matplotlib figure (fig) or use plt functions"

            return fig, None

        except Exception as e:
            return None, f"Execution error: {str(e)}"
        finally:
            # Clean up
            try:
                import matplotlib.pyplot as plt
                plt.close('all')
            except:
                pass

    def _render_chart_content(self, chart_obj: Any, **kwargs) -> str:
        """Render Matplotlib chart as base64 embedded image."""
        img_id = f"matplotlib-chart-{uuid.uuid4().hex[:8]}"

        # Get image format and DPI
        img_format = kwargs.get('format', 'png')
        dpi = kwargs.get('dpi', 100)

        # Save figure to bytes buffer
        buf = io.BytesIO()
        chart_obj.savefig(buf, format=img_format, dpi=dpi, bbox_inches='tight')
        buf.seek(0)

        # Encode to base64
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
        buf.close()

        # Create img tag with base64 data
        return f'''
        <img id="{img_id}"
             src="data:image/{img_format};base64,{img_base64}"
             style="max-width: 100%; height: auto; display: block; margin: 0 auto;"
             alt="Matplotlib Chart" />
        '''

    def to_html(
        self,
        chart_obj: Any,
        mode: str = 'partial',
        **kwargs
    ) -> str:
        """
        Convert Matplotlib chart to HTML.

        Args:
            chart_obj: Matplotlib figure object
            mode: 'partial' or 'complete'
            **kwargs: Additional parameters (dpi, format)

        Returns:
            HTML string
        """
        # Matplotlib doesn't need external scripts
        kwargs['extra_head'] = kwargs.get('extra_head', '')

        # Call parent to_html
        return super().to_html(chart_obj, mode=mode, **kwargs)

    def to_json(self, chart_obj: Any) -> Optional[Dict]:
        """Matplotlib doesn't have native JSON export."""
        return {
            'type': 'matplotlib',
            'note': 'Matplotlib figures are rendered as images and do not have JSON representation'
        }

    async def render(
        self,
        response: Any,
        theme: str = 'monokai',
        environment: str = 'terminal',
        export_format: str = 'html',
        return_code: bool = True,
        html_mode: str = 'partial',
        **kwargs
    ) -> Tuple[Any, Optional[Any]]:
        """Render Matplotlib chart."""
        content = self._get_content(response)
        code = self._extract_code(content)

        if not code:
            error_html = self._wrap_for_environment(
                "<div class='error'>No chart code found in response</div>",
                environment
            )
            return error_html, None

        # Execute code
        chart_obj, error = self.execute_code(code)

        if error:
            error_html = self._wrap_for_environment(
                self._render_error(error, code, theme),
                environment
            )
            return error_html, None

        # Generate HTML
        html_output = self.to_html(
            chart_obj,
            mode=html_mode,
            include_code=return_code,
            code=code,
            theme=theme,
            title=kwargs.pop('title', 'Matplotlib Chart'),
            icon='📈',
            dpi=kwargs.pop('dpi', 100),
            format=kwargs.pop('img_format', 'png'),
            **kwargs
        )

        # Wrap for environment
        if environment in {'jupyter', 'ipython'} and html_mode == 'partial':
            wrapped_html = self._wrap_for_environment(html_output, environment)
        else:
            wrapped_html = html_output

        # Return based on export_format
        if export_format == 'json':
            return self.to_json(chart_obj), None
        elif export_format == 'html':
            return wrapped_html, None
        elif export_format == 'both':
            return self.to_json(chart_obj), wrapped_html
        else:
            return code, wrapped_html  # Return code as content for matplotlib

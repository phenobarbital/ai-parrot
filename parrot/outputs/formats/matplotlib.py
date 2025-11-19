from typing import Any, Optional, Tuple, Dict
import io
import base64
import uuid
from pathlib import Path
from .base import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode

try:
    from rich.panel import Panel
    from rich.console import Console
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


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

    def execute_code(
        self,
        code: str,
        pandas_tool: Any = None,
        execution_state: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Tuple[Any, Optional[str]]:
        """Execute Matplotlib code within the shared Python environment."""
        extra_namespace = None
        # If no pandas tool is provided, we need to setup the backend manually
        # to ensure we don't try to open a GUI window
        manual_backend = pandas_tool is None

        if manual_backend:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            extra_namespace = {'plt': plt, 'matplotlib': matplotlib}

        context, error = super().execute_code(
            code,
            pandas_tool=pandas_tool,
            execution_state=execution_state,
            extra_namespace=extra_namespace,
            **kwargs,
        )

        try:
            if error:
                return None, error

            if not context:
                return None, "Execution context was empty"

            # Try to find the figure object in the context
            fig = context.get('fig') or context.get('figure')

            # Fallback: get current figure if available
            if fig is None:
                if 'plt' in context:
                    fig = context['plt'].gcf()
                elif not manual_backend and pandas_tool:
                    # Try to get plt from tool locals if available
                    plt_ref = pandas_tool.locals.get('plt')
                    if plt_ref:
                        fig = plt_ref.gcf()

            if fig is None or not hasattr(fig, 'savefig'):
                return None, "Code must create a matplotlib figure (fig) or use plt functions"

            return fig, None
        finally:
            # Cleanup to avoid memory leaks
            if manual_backend and 'plt' in locals():
                try:
                    plt.close('all')
                except Exception:
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
            style="max-width: 100%; height: auto; display: block; margin: 0 auto; border-radius: 4px;"
            alt="Matplotlib Chart" />
        '''

    def _save_to_disk(self, chart_obj: Any, filename: str = None) -> str:
        """Save chart to disk for terminal viewing."""
        if not filename:
            filename = f"chart_{uuid.uuid4().hex[:8]}.png"

        # Ensure we have a directory
        output_dir = Path("outputs/charts")
        output_dir.mkdir(parents=True, exist_ok=True)

        filepath = output_dir / filename
        chart_obj.savefig(str(filepath), bbox_inches='tight', dpi=100)
        return str(filepath)

    def to_html(
        self,
        chart_obj: Any,
        mode: str = 'partial',
        **kwargs
    ) -> str:
        """
        Convert Matplotlib chart to HTML.
        """
        # Matplotlib doesn't need external scripts in head
        kwargs['extra_head'] = kwargs.get('extra_head', '')

        # Call parent to_html
        return super().to_html(chart_obj, mode=mode, **kwargs)

    def to_json(self, chart_obj: Any) -> Optional[Dict]:
        """Matplotlib figures don't have a standard native JSON representation."""
        return None

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

        # 1. Extract Code
        # Check if code is explicitly provided in the structured response
        code = getattr(response, 'code', None)

        # Fallback to extracting from text content
        if not code:
            content = self._get_content(response)
            code = self._extract_code(content)

        if not code:
            error_msg = "No chart code found in response"
            if environment == 'terminal':
                return error_msg, None
            return self._wrap_for_environment(
                f"<div class='error'>{error_msg}</div>",
                environment
            ), None

        # 2. Execute Code
        chart_obj, error = self.execute_code(
            code,
            pandas_tool=kwargs.pop('pandas_tool', None),
            execution_state=kwargs.pop('execution_state', None),
            **kwargs,
        )

        if error:
            if environment == 'terminal':
                return f"Error generating chart: {error}", None
            return self._wrap_for_environment(
                self._render_error(error, code, theme),
                environment
            ), None

        # 3. Handle Terminal Environment (Save to Disk)
        if environment == 'terminal':
            saved_path = self._save_to_disk(chart_obj)
            msg = f"Chart generated successfully and saved to: {saved_path}"

            if RICH_AVAILABLE:
                return Panel(msg, title="📊 Chart Generated", border_style="green"), None
            return msg, None

        # 4. Generate HTML for Web/Jupyter
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

        # 5. Wrap for Environment
        if environment in {'jupyter', 'notebook', 'ipython', 'colab'}:
            wrapped_html = self._wrap_for_environment(html_output, environment)
        else:
            wrapped_html = html_output

        # 6. Return based on export format
        if export_format == 'html':
            return wrapped_html, None
        else:
            # Default behavior: Return code as content, HTML widget as wrapped
            return code, wrapped_html

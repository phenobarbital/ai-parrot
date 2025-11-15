from typing import Any, Optional, Tuple, Dict
import contextlib
import io
import base64
import uuid

from .base import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode


SEABORN_SYSTEM_PROMPT = """SEABORN CHART OUTPUT MODE:
Generate polished statistical visualizations using Seaborn.

REQUIREMENTS:
1. Return Python code in a markdown code block (```python)
2. Import seaborn as sns and set a theme with sns.set_theme()
3. Load or create data directly in the example (use sns.load_dataset or inline data)
4. Store the figure in 'fig' (sns.relplot returns a FacetGrid; use .fig) or fall back to plt.gcf()
5. Add descriptive titles, axis labels, and legend/annotation cues
6. Prefer seaborn high-level functions (relplot, catplot, histplot, heatmap, etc.)
7. Keep charts self-contained—no external files or plt.show()

EXAMPLE:
```python
# Import seaborn
import seaborn as sns

# Apply the default theme
sns.set_theme()

# Load an example dataset
tips = sns.load_dataset("tips")

# Create a visualization
sns.relplot(
    data=tips,
    x="total_bill", y="tip", col="time",
    hue="smoker", style="smoker", size="size",
)
```

Explanation:
- sns.set_theme() ensures a consistent, modern aesthetic.
- Inline dataset loading keeps the code runnable anywhere.
- relplot showcases multi-faceted Seaborn features (faceting, hue, style, size).
- Returning only the code snippet allows the renderer to execute it safely.
"""


@register_renderer(OutputMode.SEABORN, system_prompt=SEABORN_SYSTEM_PROMPT)
class SeabornRenderer(BaseChart):
    """Renderer for Seaborn charts (rendered as static images)."""

    def execute_code(
        self,
        code: str,
        pandas_tool: "PythonPandasTool | None" = None,
        **kwargs,
    ) -> Tuple[Any, Optional[str]]:
        """Execute Seaborn code and return the underlying Matplotlib figure."""
        manual_backend = pandas_tool is None
        extra_namespace = None
        if manual_backend:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import seaborn as sns
            extra_namespace = {
                'sns': sns,
                'plt': plt,
                'matplotlib': matplotlib,
            }

        context, error = super().execute_code(
            code,
            pandas_tool=pandas_tool,
            extra_namespace=extra_namespace,
            **kwargs,
        )

        try:
            if error:
                return None, error

            if not context:
                return None, "Execution context was empty"

            fig = context.get('fig') or context.get('figure')

            if fig is None:
                grid = context.get('g') or context.get('grid') or context.get('chart')
                if grid is not None and hasattr(grid, 'fig'):
                    fig = grid.fig

            if fig is None:
                axis = context.get('ax') or context.get('axes')
                if axis is not None and hasattr(axis, 'figure'):
                    fig = axis.figure

            if fig is None and 'plt' in context:
                fig = context['plt'].gcf()

            if fig is None or not hasattr(fig, 'savefig'):
                return None, (
                    "Code must create a seaborn visualization that exposes a Matplotlib figure "
                    "(assign to fig, use FacetGrid.fig, or rely on plt.gcf())."
                )

            return fig, None
        finally:
            if manual_backend:
                with contextlib.suppress(Exception):
                    import matplotlib.pyplot as plt
                    plt.close('all')

    def _render_chart_content(self, chart_obj: Any, **kwargs) -> str:
        """Render Seaborn chart as an embedded base64 image."""
        img_id = f"seaborn-chart-{uuid.uuid4().hex[:8]}"
        img_format = kwargs.get('format', 'png')
        dpi = kwargs.get('dpi', 110)

        buffer = io.BytesIO()
        chart_obj.savefig(buffer, format=img_format, dpi=dpi, bbox_inches='tight')
        buffer.seek(0)
        img_base64 = base64.b64encode(buffer.read()).decode('utf-8')
        buffer.close()

        return f'''
        <img id="{img_id}"
             src="data:image/{img_format};base64,{img_base64}"
             style="max-width: 100%; height: auto; display: block; margin: 0 auto;"
             alt="Seaborn Chart" />
        '''

    def to_html(
        self,
        chart_obj: Any,
        mode: str = 'partial',
        **kwargs
    ) -> str:
        """Convert Seaborn chart to HTML."""
        kwargs['extra_head'] = kwargs.get('extra_head', '')
        return super().to_html(chart_obj, mode=mode, **kwargs)

    def to_json(self, chart_obj: Any) -> Optional[Dict]:
        """Return metadata noting Seaborn renders as static images."""
        return {
            'type': 'seaborn',
            'note': 'Seaborn visualizations render as Matplotlib figures encoded into base64 images.'
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
        """Render Seaborn chart."""
        content = self._get_content(response)
        code = self._extract_code(content)

        if not code:
            error_html = self._wrap_for_environment(
                "<div class='error'>No chart code found in response</div>",
                environment
            )
            return error_html, None

        chart_obj, error = self.execute_code(
            code,
            pandas_tool=kwargs.pop('pandas_tool'),
            execution_state=kwargs.get('execution_state'),
            **kwargs,
        )

        if error:
            error_html = self._wrap_for_environment(
                self._render_error(error, code, theme),
                environment
            )
            return error_html, None

        if environment in {'terminal', 'console', 'jupyter', 'notebook', 'ipython', 'colab'}:
            # For Jupyter, return the figure object directly
            # The frontend will handle rendering it
            return code, chart_obj

        html_output = self.to_html(
            chart_obj,
            mode=html_mode,
            include_code=return_code,
            code=code,
            theme=theme,
            title=kwargs.pop('title', 'Seaborn Chart'),
            icon='🎨',
            dpi=kwargs.pop('dpi', 110),
            format=kwargs.pop('img_format', 'png'),
            **kwargs
        )

        wrapped_html = (
            self._wrap_for_environment(html_output, environment)
            if environment in {'jupyter', 'ipython'} and html_mode == 'partial'
            else html_output
        )

        if export_format == 'json':
            return self.to_json(chart_obj), None
        if export_format == 'both':
            return self.to_json(chart_obj), wrapped_html

        return code, wrapped_html

from typing import Any, Optional, Tuple, Dict, List
import contextlib
import io
import base64
import uuid
from .chart import BaseChart
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
        pandas_tool: Any = None,
        execution_state: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Tuple[Any, Optional[str]]:
        """Execute Seaborn code and return all underlying Matplotlib figures."""
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

        try:
            # Execute using BaseRenderer logic
            context, error = super().execute_code(
                code,
                pandas_tool=pandas_tool,
                execution_state=execution_state,
                extra_namespace=extra_namespace,
                **kwargs,
            )

            if error:
                return None, error

            if not context:
                return None, "Execution context was empty"

            # Find all figure objects
            figures = self._find_chart_objects(context)

            if figures:
                return figures, None

            return None, "Code must define a figure variable (fig, chart, plot) or create matplotlib figures"

        finally:
            if manual_backend:
                with contextlib.suppress(Exception):
                    import matplotlib.pyplot as plt
                    plt.close('all')

    @staticmethod
    def _find_chart_objects(context: Dict[str, Any]) -> List[Any]:
        """Locate all matplotlib figure objects in the local namespace."""
        figures: List[Any] = []
        seen_ids = set()

        def add_fig(obj: Any) -> None:
            if obj is None:
                return

            # Skip renderer / BaseChart instances (like `self`)
            if isinstance(obj, BaseChart):
                return

            # Check if it's a matplotlib Figure
            has_savefig = hasattr(obj, 'savefig')
            has_axes = hasattr(obj, 'axes')

            # Check if it's a Seaborn FacetGrid or similar
            has_fig_attr = hasattr(obj, 'fig') and hasattr(obj.fig, 'savefig')

            # Check if it's a matplotlib Axes
            is_axes = hasattr(obj, 'figure') and hasattr(obj.figure, 'savefig')

            if has_fig_attr:
                # Handle FacetGrid, PairGrid, etc.
                fig = obj.fig
                if id(fig) not in seen_ids:
                    figures.append(fig)
                    seen_ids.add(id(fig))
            elif is_axes:
                # Handle Axes objects
                fig = obj.figure
                if id(fig) not in seen_ids:
                    figures.append(fig)
                    seen_ids.add(id(fig))
            elif has_savefig and has_axes and id(obj) not in seen_ids:
                # Handle Figure objects directly
                figures.append(obj)
                seen_ids.add(id(obj))

        # 1. Priority search for common variable names to preserve order
        priority_vars = ['fig', 'figure', 'chart', 'plot', 'g', 'grid', 'ax', 'axes']
        for var_name in priority_vars:
            if var_name in context:
                add_fig(context[var_name])

        # 2. Scan all locals for other figure objects
        for var_name, obj in context.items():
            if var_name.startswith('_') or var_name in priority_vars:
                continue
            add_fig(obj)

        # 3. Fallback: try to get current figure from plt if available
        if not figures and 'plt' in context:
            try:
                fig = context['plt'].gcf()
                if fig and hasattr(fig, 'savefig') and id(fig) not in seen_ids:
                    figures.append(fig)
            except Exception:
                pass

        return figures

    def _render_chart_content(self, chart_objs: Any, **kwargs) -> str:
        """
        Render Seaborn chart(s) as embedded base64 image(s).
        Handles a single figure or a list of figures.
        """
        # Ensure we have a list
        figures = chart_objs if isinstance(chart_objs, list) else [chart_objs]

        html_parts = []
        img_format = kwargs.get('format', 'png')
        dpi = kwargs.get('dpi', 110)

        for i, chart_obj in enumerate(figures):
            img_id = f"seaborn-chart-{uuid.uuid4().hex[:8]}"

            # Render figure to base64
            buffer = io.BytesIO()
            chart_obj.savefig(buffer, format=img_format, dpi=dpi, bbox_inches='tight')
            buffer.seek(0)
            img_base64 = base64.b64encode(buffer.read()).decode('utf-8')
            buffer.close()

            chart_html = f'''
            <div class="seaborn-chart-wrapper" style="margin-bottom: 20px; width: 100%;">
                <img id="{img_id}"
                     src="data:image/{img_format};base64,{img_base64}"
                     style="width: 100%; height: auto; display: block; margin: 0 auto;"
                     alt="Seaborn Chart {i+1}" />
            </div>
            '''
            html_parts.append(chart_html)

        return "\n".join(html_parts)

    def to_html(
        self,
        chart_obj: Any,
        mode: str = 'partial',
        **kwargs
    ) -> str:
        """Convert Seaborn chart(s) to HTML."""
        kwargs['extra_head'] = kwargs.get('extra_head', '')

        # Call parent to_html (which calls _render_chart_content)
        return super().to_html(chart_obj, mode=mode, **kwargs)

    def to_json(self, chart_obj: Any) -> Optional[Any]:
        """Return metadata noting Seaborn renders as static images."""
        figures = chart_obj if isinstance(chart_obj, list) else [chart_obj]

        results = []
        for fig in figures:
            results.append({
                'type': 'seaborn',
                'note': 'Seaborn visualizations render as Matplotlib figures encoded into base64 images.',
                'figure_size': list(fig.get_size_inches()) if hasattr(fig, 'get_size_inches') else None,
                'dpi': fig.dpi if hasattr(fig, 'dpi') else None,
            })

        return results if len(results) > 1 else results[0] if results else None

    async def render(
        self,
        response: Any,
        theme: str = 'monokai',
        environment: str = 'html',
        include_code: bool = False,
        html_mode: str = 'partial',
        **kwargs
    ) -> Tuple[Any, Optional[Any]]:
        """Render Seaborn chart(s)."""

        # 1. Extract Code
        code = getattr(response, 'code', None)
        output_format = kwargs.get('output_format', environment)

        # Fallback to extracting from text content
        if not code:
            content = self._get_content(response)
            code = self._extract_code(content)

        if not code:
            error_msg = "No chart code found in response"
            if output_format == 'terminal':
                return error_msg, None
            return self._wrap_for_environment(
                f"<div class='error'>{error_msg}</div>",
                output_format
            ), None

        # 2. Execute Code
        chart_objs, error = self.execute_code(
            code,
            pandas_tool=kwargs.pop('pandas_tool', None),
            execution_state=kwargs.pop('execution_state', None),
            **kwargs,
        )

        if error:
            if output_format == 'terminal':
                return f"Error generating chart: {error}", None
            return self._wrap_for_environment(
                self._render_error(error, code, theme),
                output_format
            ), None

        # 3. Handle Jupyter/Notebook Environment
        if output_format in {'jupyter', 'notebook', 'ipython', 'colab'}:
            # For Jupyter, return the figure object(s) directly
            # The frontend will handle rendering them
            if isinstance(chart_objs, list):
                # If multiple figures, return them as a tuple
                return code, chart_objs if len(chart_objs) > 1 else chart_objs[0]
            return code, chart_objs

        # 4. Generate HTML for Web/Terminal
        html_output = self.to_html(
            chart_objs,
            mode=html_mode,
            include_code=include_code,
            code=code,
            theme=theme,
            title=kwargs.get('title', 'Seaborn Chart'),
            icon='🎨',
            dpi=kwargs.get('dpi', 110),
            format=kwargs.get('img_format', 'png'),
            **kwargs
        )

        # 5. Return based on output format
        if output_format == 'html':
            return code, html_output
        elif output_format == 'json':
            return code, self.to_json(chart_objs)
        elif output_format == 'terminal':
            # For terminal, could save to file like Plotly does
            # For now, return the HTML
            return code, html_output

        # Default behavior: Return code as content, HTML as wrapped
        return code, html_output

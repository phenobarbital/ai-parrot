from typing import Any, Optional, Tuple, Dict, List
import uuid
from pathlib import Path
import json
from .chart import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode

try:
    import holoviews as hv
    from bokeh.embed import components
    from bokeh.resources import CDN
    HOLOVIEWS_AVAILABLE = True
except ImportError:
    HOLOVIEWS_AVAILABLE = False

try:
    from rich.panel import Panel
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    from ipywidgets import HTML as IPyHTML
    IPYWIDGETS_AVAILABLE = True
except ImportError:
    IPYWIDGETS_AVAILABLE = False


HOLOVIEWS_SYSTEM_PROMPT = """HOLOVIEWS CHART OUTPUT MODE:
Generate interactive charts using HoloViews (typically with Bokeh backend).

REQUIREMENTS:
1. Return Python code in a markdown code block (```python).
2. MANDATORY: Start by importing holoviews and loading the extension:
   ```python
   import holoviews as hv
   from holoviews import opts
   hv.extension('bokeh')
3. Store the final layout/element in a variable named 'chart', 'plot', 'layout', or 'fig'
4. Make the chart self-contained with inline data (pandas or lists)
5. CHART TYPES:
    - PREFERRED: hv.Bars, hv.Curve, hv.Scatter, hv.HeatMap, hv.Histogram.
    - FORBIDDEN: Do NOT use hv.Pie. If the user asks for a Pie chart, you MUST generate a hv.Bars chart instead.
6. Use hv.opts for styling (width, height, tools, etc.)
7. DO NOT execute the code or save files - return code only

EXAMPLE:
```python
import pandas as pd
import holoviews as hv
from holoviews import opts
hv.extension('bokeh')

# Data
data = pd.DataFrame({
    'cyl': [4, 6, 8, 4, 6, 8],
    'mpg': [30, 20, 15, 32, 21, 14]
})

# Plot
hist = hv.Histogram(data, kdims='mpg', vdims='cyl')
hist.opts(opts.Histogram(alpha=0.9, width=600, height=400, title="MPG Histogram"))

# Assign to variable
chart = hist
"""

@register_renderer(OutputMode.HOLOVIEWS, system_prompt=HOLOVIEWS_SYSTEM_PROMPT)
class HoloviewsRenderer(BaseChart):
    """Renderer for HoloViews charts (via Bokeh backend)"""

    def execute_code(
        self,
        code: str,
        pandas_tool: Any = None,
        execution_state: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Tuple[Any, Optional[str]]:
        """Execute HoloViews code within the shared Python environment."""

        if not HOLOVIEWS_AVAILABLE:
            return None, "HoloViews or Bokeh not installed. Please install: pip install holoviews bokeh"

        # Execute using BaseRenderer logic
        context, error = super().execute_code(
            code,
            pandas_tool=pandas_tool,
            execution_state=execution_state,
            **kwargs,
        )

        if error:
            return None, error

        if not context:
            return None, "Execution context was empty"

        # Find the chart objects
        if figures := self._find_chart_objects(context):
            return figures, None

        return None, "Code must define a HoloViews object (chart, plot, layout)"

    @staticmethod
    def _find_chart_objects(context: Dict[str, Any]) -> List[Any]:
        """Locate all HoloViews objects in the local namespace."""
        figures: List[Any] = []
        seen_ids = set()

        def add_fig(obj: Any) -> None:
            if obj is None:
                return

            # Robust Check: Use isinstance if library is loaded, otherwise strict duck-typing
            is_holoviews = False
            if HOLOVIEWS_AVAILABLE:
                # hv.core.Dimensioned is the base for Elements, Layouts, Overlays
                if isinstance(obj, hv.core.Dimensioned):
                    is_holoviews = True

            # Fallback duck-typing if isinstance fails or library mix-up
            if not is_holoviews:
                # Relaxed duck-typing: check for 'opts' and 'kdims' OR 'data' (some containers)
                if hasattr(obj, 'opts') and (hasattr(obj, 'kdims') or hasattr(obj, 'data')):
                    is_holoviews = True

            if is_holoviews and id(obj) not in seen_ids:
                figures.append(obj)
                seen_ids.add(id(obj))

        # 1. Priority search for named variables
        priority_vars = ['chart', 'plot', 'layout', 'fig', 'renderer', 'pie_chart', 'bar_chart']
        for var_name in priority_vars:
            if var_name in context:
                add_fig(context[var_name])

        # 2. Scan all locals for other figure objects
        for var_name, obj in context.items():
            if var_name.startswith('_') or var_name in priority_vars:
                continue
            # Skip modules and basic types to save time
            if isinstance(obj, (int, float, str, bool, type(None))):
                continue
            add_fig(obj)

        return figures

    def _render_chart_content(self, chart_objs: Any, **kwargs) -> str:
        """
        Render HoloViews object to HTML/JS using Bokeh backend.
        """
        if not HOLOVIEWS_AVAILABLE:
            return "<div>HoloViews library not available.</div>"

        # Ensure we have a list
        figures = chart_objs if isinstance(chart_objs, list) else [chart_objs]
        html_parts = []

        # Ensure the bokeh extension is loaded
        try:
            # We try to set it silent to avoid console spam
            hv.extension('bokeh', logo=False)
            renderer = hv.renderer('bokeh')
        except Exception:
            # Fallback
            renderer = hv.renderer('bokeh')

        for fig in figures:
            try:
                # 1. Render HoloViews object to a Bokeh plot
                plot_state = renderer.get_plot(fig)

                # 2. Generate Script and Div using Bokeh's components
                script, div = components(plot_state.state)

                # 3. Combine them
                chart_html = f'''
                <div class="holoviews-chart-wrapper" style="margin-bottom: 20px; display: flex; justify-content: center; flex-direction: column; align-items: center;">
                    {div}
                    {script}
                </div>
                '''
                html_parts.append(chart_html)

            except Exception as e:
                html_parts.append(f'<div class="error" style="color:red; padding:10px;">Error rendering HoloViews chart: {str(e)}</div>')

        return "\n".join(html_parts)

    def _save_to_disk(self, chart_objs: Any, filename: str = None) -> str:
        """Save chart(s) to HTML file for terminal viewing."""
        if not filename:
            filename = f"holoviews_{uuid.uuid4().hex[:8]}.html"

        output_dir = Path("outputs/charts")
        output_dir.mkdir(parents=True, exist_ok=True)
        filepath = output_dir / filename

        if not HOLOVIEWS_AVAILABLE:
            return "Error: HoloViews not installed"

        figures = chart_objs if isinstance(chart_objs, list) else [chart_objs]

        try:
            # Use HoloViews save method (which handles the HTML boilerplate)
            # If multiple figures, we might want to wrap them in a Layout if possible,
            # but saving individually or the last one is standard fallback.
            # Here we combine them if there are multiple.

            final_obj = figures[0]
            if len(figures) > 1:
                final_obj = hv.Layout(figures).cols(1)

            hv.save(final_obj, filepath, backend='bokeh')
            return str(filepath)
        except Exception as e:
            raise e

    def to_html(
        self,
        chart_obj: Any,
        mode: str = 'partial',
        **kwargs
    ) -> str:
        """
        Convert HoloViews chart(s) to HTML.
        """
        # Generate Bokeh JS/CSS resources for the <head>
        # This is crucial for the scripts in _render_chart_content to work
        extra_head = CDN.render() if HOLOVIEWS_AVAILABLE else ""

        kwargs['extra_head'] = kwargs.get('extra_head', '') + "\n" + extra_head

        return super().to_html(chart_obj, mode=mode, **kwargs)

    async def render(
        self,
        response: Any,
        theme: str = 'monokai',
        environment: str = 'html',
        include_code: bool = False,
        html_mode: str = 'partial',
        **kwargs
    ) -> Tuple[Any, Optional[Any]]:
        """Render HoloViews chart."""

        # 1. Extract Code
        code = getattr(response, 'code', None)
        output_format = kwargs.get('output_format', environment)

        if not code:
            content = self._get_content(response)
            code = self._extract_code(content)

        if not code:
            error_msg = "No chart code found in response"
            if output_format == 'terminal':
                return error_msg, None
            return self._wrap_for_environment(
                f"<div class='error'>{error_msg}</div>", output_format
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
                self._render_error(error, code, theme), output_format
            ), None

        # 3. Handle Terminal Environment (Save to Disk)
        if output_format == 'terminal':
            try:
                saved_path = self._save_to_disk(chart_objs)
                msg = f"Interactive HoloViews chart saved to: {saved_path}"
                if RICH_AVAILABLE:
                    return Panel(msg, title="📊 HoloViews Chart", border_style="green"), None
                return msg, None
            except Exception as e:
                return f"Chart generated but failed to save: {e}", None

        # 4. Generate HTML
        # Pass title and other kwargs to to_html
        html_output = self.to_html(
            chart_objs,
            mode=html_mode,
            include_code=include_code,
            code=code,
            theme=theme,
            title=kwargs.get('title', 'HoloViews Chart'),
            icon='📈',
            **kwargs
        )

        # 5. Wrap for Environment
        if output_format in {'jupyter', 'notebook', 'ipython', 'colab'}:
            if IPYWIDGETS_AVAILABLE:
                return code, IPyHTML(value=html_output)
            return code, html_output

        # 6. Return default
        return code, html_output

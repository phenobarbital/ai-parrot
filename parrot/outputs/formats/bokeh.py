# ai_parrot/outputs/formats/charts/bokeh.py
from typing import Any, Optional, Tuple, Dict
import uuid
import json
from .base import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode


BOKEH_SYSTEM_PROMPT = """BOKEH CHART OUTPUT MODE:
Generate an interactive chart using Bokeh.

REQUIREMENTS:
1. Return Python code in a markdown code block (```python)
2. Use bokeh.plotting or bokeh.models
3. Store the plot in a variable named 'p' (recommended), 'plot', 'fig', or 'chart'
4. Make the chart self-contained with inline data
5. Use appropriate glyph types (circle, line, vbar, hbar, etc.)
6. Add titles, axis labels, and legends
7. Configure plot dimensions and tools
8. DO NOT call show() or save() - return code only
9. IMPORTANT: Use 'p' as the variable name for best compatibility

EXAMPLE:
```python
from bokeh.plotting import figure
from bokeh.models import HoverTool

x = ['A', 'B', 'C', 'D']
y = [23, 45, 12, 67]

p = figure(
    x_range=x,
    title="Sales by Category",
    width=800,
    height=400,
    toolbar_location="above"
)

p.vbar(x=x, top=y, width=0.8, color='navy', alpha=0.8)

p.xaxis.axis_label = "Category"
p.yaxis.axis_label = "Sales"

hover = HoverTool(tooltips=[("Category", "@x"), ("Sales", "@top")])
p.add_tools(hover)
```
"""


@register_renderer(OutputMode.BOKEH, system_prompt=BOKEH_SYSTEM_PROMPT)
class BokehRenderer(BaseChart):
    """Renderer for Bokeh charts"""

    def execute_code(
        self,
        code: str,
        pandas_tool: "PythonPandasTool | None" = None,
        execution_state: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Tuple[Any, Optional[str]]:
        """Execute Bokeh code using the shared Python execution context."""
        extra_namespace = None
        if pandas_tool is None:
            from bokeh.plotting import figure as bokeh_figure
            from bokeh import models, plotting
            extra_namespace = {
                'figure': bokeh_figure,
                'models': models,
                'plotting': plotting,
            }

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

        # Try to find the plot object - order matters!
        plot = None
        for var_name in ['p', 'plot', 'fig', 'chart']:
            if var_name in context and self._is_bokeh_plot(context[var_name]):
                plot = context[var_name]
                break

        if plot is None:
            for key, value in context.items():
                if not key.startswith('_') and self._is_bokeh_plot(value):
                    plot = value
                    break

        if plot is None:
            return None, "Code must define a plot variable (p, plot, fig, or chart)"

        return plot, None

    @staticmethod
    def _is_bokeh_plot(obj: Any) -> bool:
        """Check if object is a Bokeh plot/figure."""
        # Check for Bokeh plot attributes
        bokeh_attrs = ['renderers', 'toolbar', 'xaxis', 'yaxis']
        has_attrs = all(hasattr(obj, attr) for attr in bokeh_attrs)

        if has_attrs:
            return True

        # Check by class name
        class_name = obj.__class__.__name__
        bokeh_classes = ['Figure', 'Plot', 'GridPlot']
        if any(bc in class_name for bc in bokeh_classes):
            return True

        # Check module
        module = getattr(obj.__class__, '__module__', '')
        return 'bokeh' in module

    def _render_chart_content(self, chart_obj: Any, **kwargs) -> str:
        """Render Bokeh-specific chart content."""
        from bokeh.embed import json_item

        chart_id = f"bokeh-chart-{uuid.uuid4().hex[:8]}"

        try:
            # Get Bokeh JSON item
            item = json_item(chart_obj)
            item_json = json.dumps(item)
        except Exception as e:
            return f'<div class="error-container"><h3>⚠️ Bokeh Serialization Error</h3><p>{str(e)}</p></div>'

        return f'''
        <div id="{chart_id}" style="width: 100%;"></div>
        <script type="text/javascript">
            (function() {{
                var item = {item_json};
                Bokeh.embed.embed_item(item, "{chart_id}");
                console.log('Bokeh chart rendered successfully');
            }})();
        </script>
        '''

    def to_html(
        self,
        chart_obj: Any,
        mode: str = 'partial',
        **kwargs
    ) -> str:
        """
        Convert Bokeh chart to HTML.

        Args:
            chart_obj: Bokeh plot object
            mode: 'partial' or 'complete'
            **kwargs: Additional parameters

        Returns:
            HTML string
        """
        # Bokeh libraries for <head>
        try:
            from bokeh import __version__ as bokeh_version
        except:
            bokeh_version = "3.3.0"  # fallback version

        extra_head = f'''
    <!-- Bokeh -->
    <script src="https://cdn.bokeh.org/bokeh/release/bokeh-{bokeh_version}.min.js"></script>
    <script src="https://cdn.bokeh.org/bokeh/release/bokeh-widgets-{bokeh_version}.min.js"></script>
    <script src="https://cdn.bokeh.org/bokeh/release/bokeh-tables-{bokeh_version}.min.js"></script>
        '''

        kwargs['extra_head'] = extra_head

        # Call parent to_html
        return super().to_html(chart_obj, mode=mode, **kwargs)

    def to_json(self, chart_obj: Any) -> Optional[Dict]:
        """Export Bokeh JSON specification."""
        try:
            from bokeh.embed import json_item
            item = json_item(chart_obj)
            return json.loads(json.dumps(item))
        except Exception as e:
            return {'error': str(e)}

    async def render(
        self,
        response: Any,
        theme: str = 'monokai',
        environment: str = 'html',
        export_format: str = 'html',
        return_code: bool = True,
        html_mode: str = 'partial',
        **kwargs
    ) -> Tuple[Any, Optional[Any]]:
        """Render Bokeh chart."""
        content = self._get_content(response)
        code = self._extract_code(content)

        if not code:
            error_msg = "No chart code found in response"
            error_html = "<div class='error'>No chart code found in response</div>"
            if environment == 'terminal':
                return error_msg, error_msg
            return error_msg, error_html

        # Execute code
        chart_obj, error = self.execute_code(
            code,
            pandas_tool=kwargs.pop('pandas_tool'),
            execution_state=kwargs.get('execution_state'),
            **kwargs,
        )

        if error:
            error_html = self._render_error(error, code, theme)
            if environment == 'terminal':
                return code, error
            return code, error_html

        if environment == 'terminal':
            return code, code

        if environment == 'jupyter':
            from bokeh.embed import components
            script, div = components(chart_obj)
            return code, f"{script}{div}"

        # Generate HTML
        html_output = self.to_html(
            chart_obj,
            mode=html_mode,
            include_code=return_code,
            code=code,
            theme=theme,
            title=kwargs.get('title', 'Bokeh Chart'),
            icon='📊',
            **kwargs
        )
        return code, html_output

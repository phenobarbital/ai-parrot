# ai_parrot/outputs/formats/charts/bokeh.py
from typing import Any, Optional, Tuple, Dict, List
import uuid
import json
from .chart import BaseChart
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
        pandas_tool: Any = None,
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

        # Find all chart objects
        if charts := self._find_chart_objects(context):
            return charts, None

        return None, "Code must define a plot variable (p, plot, fig, or chart)"

    @staticmethod
    def _find_chart_objects(context: Dict[str, Any]) -> List[Any]:
        """Locate all Bokeh plot objects in the local namespace."""
        from bokeh.embed import json_item

        charts: List[Any] = []
        seen_ids = set()

        def is_bokeh_plot(obj: Any) -> bool:
            """Check if object is a Bokeh plot/figure."""
            if obj is None:
                return False

            # Skip renderer / BaseChart instances
            if isinstance(obj, BaseChart):
                return False

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

        def is_serializable(obj: Any) -> bool:
            """Check if the Bokeh object can actually be serialized."""
            try:
                json_item(obj)
                return True
            except Exception:
                return False

        def add_chart(obj: Any) -> None:
            if is_bokeh_plot(obj) and id(obj) not in seen_ids:
                # Only add if it can actually be serialized
                if is_serializable(obj):
                    charts.append(obj)
                    seen_ids.add(id(obj))
                else:
                    # Debug: log filtered objects (optional)
                    # print(f"Filtered non-serializable Bokeh object: {type(obj).__name__}")
                    pass

        # 1. Priority search for common variable names to preserve order
        priority_vars = ['p', 'plot', 'fig', 'figure', 'chart']
        for var_name in priority_vars:
            if var_name in context:
                add_chart(context[var_name])

        # 2. Scan all locals for other chart objects
        for var_name, obj in context.items():
            if var_name.startswith('_') or var_name in priority_vars:
                continue
            add_chart(obj)

        return charts

    def _render_chart_content(self, chart_objs: Any, **kwargs) -> str:
        """
        Render Bokeh-specific chart content (HTML/JS).
        Handles a single chart or a list of charts.
        """
        from bokeh.embed import json_item

        # Ensure we have a list
        charts = chart_objs if isinstance(chart_objs, list) else [chart_objs]

        html_parts = []

        for i, chart_obj in enumerate(charts):
            print('CHART > ', chart_obj, type(chart_obj))
            chart_id = f"bokeh-chart-{uuid.uuid4().hex[:8]}"

            try:
                # Get Bokeh JSON item
                item = json_item(chart_obj)
                item_json = json.dumps(item)
            except Exception as e:
                chart_html = f'''
                <div class="bokeh-chart-wrapper" style="margin-bottom: 20px;">
                    <div class="error-container">
                        <h3>⚠️ Bokeh Serialization Error</h3>
                        <p>{str(e)}</p>
                    </div>
                </div>
                '''
                html_parts.append(chart_html)
                continue

            chart_html = f'''
            <div class="bokeh-chart-wrapper" style="margin-bottom: 20px;">
                <div id="{chart_id}" style="width: 100%;"></div>
                <script type="text/javascript">
                    (function() {{
                        var item = {item_json};

                        if (typeof Bokeh === 'undefined') {{
                            console.error("Bokeh library not loaded");
                            document.getElementById('{chart_id}').innerHTML = "Error: Bokeh library not loaded.";
                            return;
                        }}

                        try {{
                            Bokeh.embed.embed_item(item, "{chart_id}");
                            console.log('Bokeh chart {chart_id} rendered successfully');
                        }} catch (error) {{
                            console.error('Error rendering Bokeh chart:', error);
                            document.getElementById('{chart_id}').innerHTML =
                                '<div style="color:red; padding:10px;">⚠️ Chart Rendering Error: ' + error.message + '</div>';
                        }}
                    }})();
                </script>
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
        """
        Convert Bokeh chart(s) to HTML.

        Args:
            chart_obj: Bokeh plot object or list of plot objects
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

        kwargs['extra_head'] = kwargs.get('extra_head', extra_head)

        # Call parent to_html (which calls _render_chart_content)
        return super().to_html(chart_obj, mode=mode, **kwargs)

    def to_json(self, chart_obj: Any) -> Optional[Any]:
        """Export Bokeh JSON specification (returns list if multiple)."""
        from bokeh.embed import json_item

        charts = chart_obj if isinstance(chart_obj, list) else [chart_obj]
        results = []

        for chart in charts:
            try:
                item = json_item(chart)
                results.append(json.loads(json.dumps(item)))
            except Exception as e:
                results.append({'error': str(e)})

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
        """Render Bokeh chart(s)."""

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
            from bokeh.embed import components

            charts = chart_objs if isinstance(chart_objs, list) else [chart_objs]

            if len(charts) == 1:
                # Single chart
                script, div = components(charts[0])
                return code, f"{script}{div}"
            else:
                # Multiple charts
                script, divs = components(charts)
                combined = script + "".join(divs)
                return code, combined

        # 4. Generate HTML for Web/Terminal
        html_output = self.to_html(
            chart_objs,
            mode=html_mode,
            include_code=include_code,
            code=code,
            theme=theme,
            title=kwargs.get('title', 'Bokeh Chart'),
            icon='📊',
            **kwargs
        )

        # 5. Return based on output format
        if output_format == 'html':
            return code, html_output
        elif output_format == 'json':
            return code, self.to_json(chart_objs)
        elif output_format == 'terminal':
            # For terminal, return the code and HTML
            return code, html_output

        # Default behavior: Return code as content, HTML as wrapped
        return code, html_output

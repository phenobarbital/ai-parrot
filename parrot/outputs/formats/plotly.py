from typing import Any, Optional, Tuple, Dict, List
import json
import uuid
from pathlib import Path
from .chart import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode

try:
    from rich.panel import Panel
    from rich.syntax import Syntax
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    from ipywidgets import HTML as IPyHTML
    IPYWIDGETS_AVAILABLE = True
except ImportError:
    IPYWIDGETS_AVAILABLE = False


PLOTLY_SYSTEM_PROMPT = """PLOTLY CHART OUTPUT MODE:
Generate an interactive chart using Plotly.

REQUIREMENTS:
1. Return Python code in a markdown code block (```python)
2. Use plotly.graph_objects or plotly.express
3. Store the figure in a variable named 'fig', 'chart', or 'plot'
4. Make the chart self-contained with inline data
5. Use appropriate chart types (scatter, bar, line, pie, etc.)
6. Add titles, labels, and legends for clarity
7. Configure layout for better visualization
8. DO NOT execute the code or save files - return code only

EXAMPLE:
```python
import plotly.graph_objects as go

fig = go.Figure(data=[
    go.Bar(
        x=['Product A', 'Product B', 'Product C', 'Product D'],
        y=[20, 14, 23, 25],
        marker_color='indianred'
    )
])

fig.update_layout(
    title='Sales by Product',
    xaxis_title='Product',
    yaxis_title='Sales',
    template='plotly_white'
)
```
"""


@register_renderer(OutputMode.PLOTLY, system_prompt=PLOTLY_SYSTEM_PROMPT)
class PlotlyRenderer(BaseChart):
    """Renderer for Plotly charts"""

    def execute_code(
        self,
        code: str,
        pandas_tool: Any = None,
        execution_state: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Tuple[Any, Optional[str]]:
        """Execute Plotly code within the shared Python environment."""

        # 1. Attempt to handle as JSON/Dict first (LLM sometimes outputs JSON)
        clean_code = code.strip()
        if clean_code.startswith('{') and clean_code.endswith('}'):
            try:
                # Try JSON parse
                chart_dict = json.loads(clean_code)
                # Check if it looks like a plotly spec
                if isinstance(chart_dict, dict) and ('data' in chart_dict or 'layout' in chart_dict):
                    return [chart_dict], None
            except json.JSONDecodeError:
                # Not valid JSON, might be Python dict or just code starting with {
                pass

        # 2. Execute using BaseRenderer logic
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

        # Find the figure objects
        if figures := self._find_chart_objects(context):
            return figures, None

        return None, "Code must define a figure variable (fig, chart, plot) or be valid Plotly JSON"

    @staticmethod
    def _find_chart_objects(context: Dict[str, Any]) -> List[Any]:
        """Locate all figure objects in the local namespace."""
        figures: List[Any] = []
        seen_ids = set()

        def add_fig(obj: Any) -> None:
            if obj is None:
                return

            # Skip renderer / BaseChart instances (like `self`)
            if isinstance(obj, BaseChart):
                return

            # Heuristic: Plotly figures usually have `to_json`, `to_dict`, and `data`
            looks_like_plotly_figure = (
                hasattr(obj, "to_json")
                and hasattr(obj, "to_dict")
                and hasattr(obj, "data")
            )

            # Also allow dict-like Plotly specs (e.g. already serialized)
            looks_like_figure_dict = isinstance(obj, dict) and "data" in obj

            if (looks_like_plotly_figure or looks_like_figure_dict) and id(obj) not in seen_ids:
                figures.append(obj)
                seen_ids.add(id(obj))

        # 1. Priority search for common variable names to preserve order
        priority_vars = ['fig', 'figure', 'chart', 'plot']
        for var_name in priority_vars:
            if var_name in context:
                add_fig(context[var_name])

        # 2. Scan all locals for other figure objects
        for var_name, obj in context.items():
            if var_name.startswith('_') or var_name in priority_vars:
                continue
            add_fig(obj)

        return figures

    def _render_chart_content(self, chart_objs: Any, **kwargs) -> str:
        """
        Render Plotly-specific chart content (HTML/JS).
        Handles a single figure or a list of figures.
        """
        # Ensure we have a list
        figures = chart_objs if isinstance(chart_objs, list) else [chart_objs]

        html_parts = []

        # Config options (can be passed via kwargs)
        config = kwargs.get('config', {
            'displayModeBar': True,
            'responsive': True,
            'displaylogo': False
        })
        config_json = json.dumps(config)

        for i, chart_obj in enumerate(figures):
            chart_id = f"plotly-chart-{uuid.uuid4().hex[:8]}"

            # Convert figure to JSON
            try:
                if hasattr(chart_obj, "to_json") and callable(chart_obj.to_json):
                    fig_json = chart_obj.to_json()
                else:
                    raise AttributeError
            except (AttributeError, TypeError):
                # Fallback if it's a dict or other format
                fig_json = json.dumps(chart_obj, default=str)

            # Generate HTML/JS for this specific chart
            chart_html = f'''
            <div class="plotly-chart-wrapper" style="margin-bottom: 20px;">
                <div id="{chart_id}" style="width: 100%; height: 100%; min-height: 450px;"></div>
                <script type="text/javascript">
                    (function() {{
                        var figure = {fig_json};
                        var config = {config_json};

                        if (typeof Plotly === 'undefined') {{
                            console.error("Plotly library not loaded");
                            document.getElementById('{chart_id}').innerHTML = "Error: Plotly library not loaded.";
                            return;
                        }}

                        Plotly.newPlot('{chart_id}', figure.data, figure.layout, config)
                            .then(function() {{
                                console.log('Plotly chart {chart_id} rendered successfully');
                            }})
                            .catch(function(error) {{
                                console.error('Error rendering Plotly chart:', error);
                                document.getElementById('{chart_id}').innerHTML =
                                    '<div style="color:red; padding:10px;">⚠️ Chart Rendering Error: ' + error.message + '</div>';
                            }});
                    }})();
                </script>
            </div>
            '''
            html_parts.append(chart_html)

        return "\n".join(html_parts)

    def _save_to_disk(self, chart_objs: Any, filename: str = None) -> str:
        """Save chart(s) to HTML file for terminal viewing."""
        if not filename:
            filename = f"plotly_{uuid.uuid4().hex[:8]}.html"

        output_dir = Path("outputs/charts")
        output_dir.mkdir(parents=True, exist_ok=True)

        filepath = output_dir / filename

        # Handle list or single object
        figures = chart_objs if isinstance(chart_objs, list) else [chart_objs]

        # Create a combined HTML file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('<html><head><script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script></head><body>')
            for fig in figures:
                if hasattr(fig, 'to_html'):
                    # Get inner HTML div
                    div = fig.to_html(include_plotlyjs=False, full_html=False)
                    f.write(f'<div style="margin-bottom: 30px;">{div}</div>')
                else:
                    f.write(f'<div>Unable to render object of type {type(fig)}</div>')
            f.write('</body></html>')

        return str(filepath)

    def to_html(
        self,
        chart_obj: Any,
        mode: str = 'partial',
        **kwargs
    ) -> str:
        """
        Convert Plotly chart(s) to HTML.
        """
        # Plotly library for <head>
        extra_head = '''
    <!-- Plotly.js -->
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
        '''

        kwargs['extra_head'] = kwargs.get('extra_head', extra_head)

        # Call parent to_html (which calls _render_chart_content)
        return super().to_html(chart_obj, mode=mode, **kwargs)

    def to_json(self, chart_obj: Any) -> Optional[Any]:
        """Export Plotly JSON specification (returns list if multiple)."""
        figures = chart_obj if isinstance(chart_obj, list) else [chart_obj]
        results = []

        for fig in figures:
            try:
                if hasattr(fig, 'to_json'):
                    results.append(json.loads(fig.to_json()))
                else:
                    results.append(fig) # It might already be a dict
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
        """Render Plotly chart."""

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

        # 3. Handle Terminal Environment (Save to Disk)
        if output_format == 'terminal':
            try:
                saved_path = self._save_to_disk(chart_objs)
                msg = f"Interactive chart saved to: {saved_path}"
                if RICH_AVAILABLE:
                    return Panel(msg, title="📊 Plotly Chart", border_style="blue"), None
                return msg, None
            except Exception as e:
                return f"Chart generated but failed to save: {e}", None

        # 4. Generate HTML for Web/Jupyter
        html_output = self.to_html(
            chart_objs,
            mode=html_mode,
            include_code=include_code,
            code=code,
            theme=theme,
            title=kwargs.get('title', 'Plotly Chart'),
            icon='📊',
            **kwargs
        )

        # 5. Wrap for Environment
        if output_format in {'jupyter', 'notebook', 'ipython', 'colab'}:
            # For Jupyter, we generally want the widget if possible, but pure HTML also works
            if IPYWIDGETS_AVAILABLE:
                return code, IPyHTML(value=html_output)
            return code, html_output

        # 6. Return based on output format
        if output_format == 'html':
            return code, html_output
        elif output_format == 'json':
            return code, self.to_json(chart_objs)

        # Default behavior: Return code as content, HTML as wrapped
        return code, html_output

# ai_parrot/outputs/formats/charts/plotly.py
from typing import Any, Optional, Tuple, Dict
import json
import uuid
from io import BytesIO
import base64
import pandas as pd
import numpy as np
from .base import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode


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
        pandas_tool: "PythonPandasTool | None" = None,
        **kwargs,
    ) -> Tuple[Any, Optional[str]]:
        """Execute Plotly code (leveraging PythonPandasTool when available)."""
        context, error = super().execute_code(
            code,
            pandas_tool=pandas_tool,
            **kwargs,
        )

        if error:
            return None, error

        if not context:
            return None, "Execution context was empty"

        fig = self._find_chart_object(context)
        if fig is None:
            return None, "Code must define a figure variable (fig, chart, plot, m, or map)"

        if hasattr(fig, 'to_html'):  # Plotly, Folium
            return fig.to_html(
                include_plotlyjs='cdn' if 'plotly' in str(type(fig)) else False,
                include_mathjax='cdn',
                full_html=False
            ), None

        if hasattr(fig, 'savefig'):  # Matplotlib fallback
            buf = BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
            buf.seek(0)
            img_b64 = base64.b64encode(buf.read()).decode()
            return f'<img src="data:image/png;base64,{img_b64}">', None

        if hasattr(fig, 'output_backend'):  # Bokeh
            from bokeh.embed import file_html
            from bokeh.resources import CDN
            return file_html(fig, CDN, "Chart"), None

        return None, f"Unsupported figure type: {type(fig)}"

    @staticmethod
    def _find_chart_object(context: Dict[str, Any]) -> Any:
        for var_name in ['fig', 'figure', 'chart', 'plot', 'm', 'map']:
            if var_name in context and context[var_name] is not None:
                return context[var_name]
        return None

    def _render_chart_content(self, chart_obj: Any, **kwargs) -> str:
        """Render Plotly-specific chart content."""
        chart_id = f"plotly-chart-{uuid.uuid4().hex[:8]}"

        # Get config options
        config = kwargs.get('config', {
            'displayModeBar': True,
            'responsive': True,
            'displaylogo': False
        })

        # Convert figure to JSON
        fig_json = chart_obj.to_json()
        config_json = json.dumps(config)

        return f'''
        <div id="{chart_id}" style="width: 100%; height: 100%;"></div>
        <script type="text/javascript">
            (function() {{
                var figure = {fig_json};
                var config = {config_json};

                Plotly.newPlot('{chart_id}', figure.data, figure.layout, config)
                    .then(function() {{
                        console.log('Plotly chart rendered successfully');
                    }})
                    .catch(function(error) {{
                        console.error('Error rendering Plotly chart:', error);
                        document.getElementById('{chart_id}').innerHTML =
                            '<div class="error-container">' +
                            '<h3>⚠️ Chart Rendering Error</h3>' +
                            '<p class="error-message">' + error.message + '</p>' +
                            '</div>';
                    }});
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
        Convert Plotly chart to HTML.

        Args:
            chart_obj: Plotly figure object
            mode: 'partial' or 'complete'
            **kwargs: Additional parameters

        Returns:
            HTML string
        """
        # Plotly library for <head>
        extra_head = '''
    <!-- Plotly.js -->
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
        '''

        kwargs['extra_head'] = extra_head

        # Call parent to_html
        return super().to_html(chart_obj, mode=mode, **kwargs)

    def to_json(self, chart_obj: Any) -> Optional[Dict]:
        """Export Plotly JSON specification."""
        try:
            return json.loads(chart_obj.to_json())
        except Exception as e:
            return {'error': str(e)}

    async def render(
        self,
        response: Any,
        theme: str = 'monokai',
        environment: str = 'html',
        return_code: bool = True,
        html_mode: str = 'partial',
        **kwargs
    ) -> Tuple[Any, Optional[Any]]:
        """Render Plotly chart."""
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
            **kwargs,
        )

        if error:
            error_html = self._render_error(error, code, theme)
            return (code, error) if environment == 'terminal' else (code, error_html)

        if environment in {'terminal', 'console', 'jupyter', 'notebook', 'ipython', 'colab'}:
            # For Jupyter, return the figure object directly
            # The frontend will handle rendering it
            return code, chart_obj

        # Generate HTML for web environments
        html_output = self.to_html(
            chart_obj,
            mode=html_mode,
            include_code=return_code,
            code=code,
            theme=theme,
            title=kwargs.pop('title', 'Plotly Chart'),
            icon='📊',
            **kwargs
        )
        return code, html_output

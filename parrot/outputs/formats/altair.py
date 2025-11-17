# parrot/outputs/formats/charts/altair.py
from typing import Any, Optional, Tuple, Dict
import json
import uuid
from .base import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode


ALTAIR_SYSTEM_PROMPT = """ALTAIR CHART OUTPUT MODE:
Generate an interactive chart using Altair (Vega-Lite).

REQUIREMENTS:
1. Return Python code in a markdown code block (```python)
2. Use altair library (import altair as alt)
3. Store the chart in a variable named 'chart', 'fig', 'c', or 'plot'
4. Make the chart self-contained with inline data when possible
5. Use appropriate mark types (mark_bar, mark_line, mark_point, etc.)
6. Include proper encodings (x, y, color, size, etc.)
7. Add titles and labels for clarity
8. DO NOT execute the code or save files - return code only

EXAMPLE:
```python
import altair as alt
import pandas as pd

data = pd.DataFrame({
    'category': ['A', 'B', 'C', 'D'],
    'values': [23, 45, 12, 67]
})

chart = alt.Chart(data).mark_bar().encode(
    x='category',
    y='values',
    color='category'
).properties(
    title='Sample Bar Chart',
    width=400,
    height=300
)
```
"""


@register_renderer(OutputMode.ALTAIR, system_prompt=ALTAIR_SYSTEM_PROMPT)
class AltairRenderer(BaseChart):
    """Renderer for Altair/Vega-Lite charts"""

    def execute_code(
        self,
        code: str,
        pandas_tool: "PythonPandasTool | None" = None,
        execution_state: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Tuple[Any, Optional[str]]:
        """Execute Altair code within the agent's Python environment."""
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

        chart = next(
            (
                context[var_name]
                for var_name in ['chart', 'fig', 'c', 'plot']
                if var_name in context
            ),
            None,
        )

        if chart is None:
            return None, "Code must define a chart variable (chart, fig, c, or plot)"

        if not hasattr(chart, 'to_dict'):
            return None, f"Object is not an Altair chart: {type(chart)}"

        return chart, None

    def _render_chart_content(self, chart_obj: Any, **kwargs) -> str:
        """Render Altair-specific chart content with vega-embed."""
        embed_options = kwargs.get('embed_options', {})
        spec = chart_obj.to_dict()
        spec_json = json.dumps(spec, indent=2)
        chart_id = f"altair-chart-{uuid.uuid4().hex[:8]}"

        default_options = {
            'actions': {'export': True, 'source': False, 'editor': False},
            'theme': kwargs.get('vega_theme', 'latimes')
        }
        default_options.update(embed_options)
        options_json = json.dumps(default_options)

        return f'''
        <div id="{chart_id}" style="width: 100%;"></div>
        <script type="text/javascript">
            vegaEmbed('#{chart_id}', {spec_json}, {options_json})
                .then(result => {{
                    console.log('Altair chart rendered successfully');
                }})
                .catch(error => {{
                    console.error('Error rendering Altair chart:', error);
                    document.getElementById('{chart_id}').innerHTML =
                        '<div class="error-container">' +
                        '<h3>⚠️ Chart Rendering Error</h3>' +
                        '<p class="error-message">' + error.message + '</p>' +
                        '</div>';
                }});
        </script>
        '''

    def to_html(
        self,
        chart_obj: Any,
        mode: str = 'partial',
        **kwargs
    ) -> str:
        """
        Convert Altair chart to HTML.

        Args:
            chart_obj: Altair chart object
            mode: 'partial' or 'complete'
            **kwargs: Additional parameters

        Returns:
            HTML string
        """
        # Vega libraries for <head>
        extra_head = '''
    <!-- Vega/Vega-Lite/Vega-Embed -->
    <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
        '''

        kwargs['extra_head'] = extra_head

        # Call parent to_html which uses _render_chart_content
        return super().to_html(chart_obj, mode=mode, **kwargs)

    def to_json(self, chart_obj: Any) -> Optional[Dict]:
        """Export Vega-Lite JSON specification."""
        try:
            return chart_obj.to_dict()
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
        """
        Render Altair chart.

        Returns:
            Tuple[Any, Optional[Any]]: (code, html)
            - code goes to response.output
            - html goes to response.response
        """
        content = self._get_content(response)
        code = self._extract_code(content)

        if not code:
            error_msg = "No chart code found in response"
            error_html = "<div class='error'>No chart code found in response</div>"
            if environment == 'terminal':
                return error_msg, error_msg
            return error_msg, error_html

        # Execute code to get chart object
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

        # Generate HTML with specified mode
        html_output = self.to_html(
            chart_obj,
            mode=html_mode,
            include_code=return_code,
            code=code,
            theme=theme,
            title=kwargs.pop('title', 'Altair Chart'),
            **kwargs
        )

        return chart_obj, html_output

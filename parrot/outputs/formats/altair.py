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

    def execute_code(self, code: str) -> Tuple[Any, Optional[str]]:
        """Execute Altair code and return chart object."""
        try:
            namespace = {}
            exec(code, namespace)

            chart = next(
                (
                    namespace[var_name]
                    for var_name in ['chart', 'fig', 'c', 'plot']
                    if var_name in namespace
                ),
                None,
            )

            if chart is None:
                return None, "Code must define a chart variable (chart, fig, c, plot)"

            if not hasattr(chart, 'to_dict'):
                return None, f"Object is not an Altair chart: {type(chart)}"

            return chart, None

        except Exception as e:
            return None, f"Execution error: {str(e)}"

    def to_html(
        self,
        chart_obj: Any,
        include_code: bool = True,
        code: Optional[str] = None,
        theme: str = 'monokai',
        title: str = 'Altair Chart',
        **kwargs
    ) -> str:
        """Convert Altair chart to HTML with vega-embed."""
        embed_options = kwargs.get('embed_options', {})
        spec = chart_obj.to_dict()
        spec_json = json.dumps(spec, indent=2)
        chart_id = f"altair-chart-{uuid.uuid4().hex[:8]}"

        default_options = {
            'actions': {'export': True, 'source': False, 'editor': False},
            'theme': 'latimes'
        }
        default_options |= embed_options
        options_json = json.dumps(default_options)

        # Code section if requested
        code_section = ''
        if include_code and code:
            code_section = self._build_code_section(code, theme, "📊")

        # Build complete HTML document
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>

    <!-- Vega/Vega-Lite Libraries -->
    <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>

    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                         'Helvetica Neue', Arial, sans-serif;
            background: #f5f7fa;
            padding: 20px;
            line-height: 1.6;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        .chart-container {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.07), 0 2px 4px rgba(0,0,0,0.05);
            padding: 30px;
            margin-bottom: 20px;
        }}

        .chart-wrapper {{
            min-height: 400px;
            display: flex;
            justify-content: center;
            align-items: center;
        }}

        #chart-{chart_id} {{
            width: 100%;
        }}

        .code-accordion {{
            margin-top: 20px;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            overflow: hidden;
            background: white;
        }}

        .code-header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 14px 20px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-weight: 600;
            user-select: none;
            transition: all 0.3s ease;
        }}

        .code-header:hover {{
            background: linear-gradient(135deg, #5568d3 0%, #653a8e 100%);
        }}

        .toggle-icon {{
            transition: transform 0.3s ease;
            font-size: 12px;
        }}

        details[open] .toggle-icon {{
            transform: rotate(90deg);
        }}

        .code-content {{
            background: #272822;
            padding: 20px;
            overflow-x: auto;
        }}

        .code-content pre {{
            margin: 0;
            font-family: 'Monaco', 'Menlo', 'Consolas', 'Courier New', monospace;
            font-size: 14px;
            line-height: 1.6;
        }}

        .error-container {{
            background: #fff3cd;
            border: 2px solid #ffc107;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
        }}

        .error-container h3 {{
            color: #856404;
            margin-bottom: 10px;
        }}

        .error-message {{
            color: #856404;
            font-weight: 500;
            margin: 10px 0;
        }}

        @media (max-width: 768px) {{
            body {{
                padding: 10px;
            }}

            .chart-container {{
                padding: 15px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="chart-container">
            <div class="chart-wrapper">
                <div id="chart-{chart_id}"></div>
            </div>
        </div>

        {code_section}
    </div>

    <script type="text/javascript">
        vegaEmbed('#chart-{chart_id}', {spec_json}, {options_json})
            .then(result => {{
                console.log('Chart rendered successfully');
            }})
            .catch(error => {{
                console.error('Error rendering chart:', error);
                document.getElementById('chart-{chart_id}').innerHTML =
                    '<div class="error-container">' +
                    '<h3>⚠️ Chart Rendering Error</h3>' +
                    '<p class="error-message">' + error.message + '</p>' +
                    '</div>';
            }});
    </script>
</body>
</html>'''

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
        environment: str = 'terminal',
        export_format: str = 'html',
        return_code: bool = True,
        **kwargs
    ) -> Tuple[Any, Optional[Any]]:
        """
        Render Altair chart.

        Returns:
            Tuple[Any, Optional[Any]]: (content, wrapped)
            - content: Primary format (JSON spec for Altair)
            - wrapped: HTML rendering (if applicable)
        """
        content = self._get_content(response)
        code = self._extract_code(content)

        if not code:
            error_html = self._wrap_for_environment(
                "<div class='error'>No chart code found in response</div>",
                environment
            )
            return error_html, None

        # Execute code to get chart object
        chart_obj, error = self.execute_code(code)

        if error:
            error_html = self._wrap_for_environment(
                self._render_error(error, code, theme),
                environment
            )
            return error_html, None

        # Get JSON spec as primary content
        json_spec = self.to_json(chart_obj)

        # Generate HTML wrapper
        html_output = self.to_html(
            chart_obj,
            include_code=return_code,
            code=code,
            theme=theme,
            title=kwargs.get('title', 'Altair Chart'),
            **kwargs
        )
        # For Jupyter/IPython, we might want to wrap differently
        if environment in {'jupyter', 'ipython'}:
            wrapped_html = self._wrap_for_environment(html_output, environment)
        else:
            # For terminal/file output, return the complete HTML document
            wrapped_html = html_output

        # Return based on export_format
        if export_format == 'json':
            # JSON only, no wrapper
            return json_spec, None

        elif export_format == 'html':
            # HTML only as content, no separate wrapper
            return wrapped_html, None

        elif export_format == 'both':
            # JSON as content, HTML as wrapper
            return json_spec, wrapped_html

        else:
            # Default: JSON content + HTML wrapper
            return json_spec, wrapped_html

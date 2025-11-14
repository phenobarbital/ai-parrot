# ai_parrot/outputs/formats/charts/echarts.py
from typing import Any, Optional, Tuple, Dict
import re
import json
import uuid
from .base import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode


ECHARTS_SYSTEM_PROMPT = """**ECHARTS JSON GENERATION MODE**

**Objective:** Generate a single, valid JSON configuration object for an Apache ECharts chart.

**CONTEXT OVERRIDE:**
This is a TEXT GENERATION task. Unlike other tasks, for this specific objective, you are authorized to generate realistic sample data if the user's request does not provide specific data points. This is an exception to the general rule of not inventing information.

**INSTRUCTIONS:**
1.  **Analyze Request:** Understand the user's goal for the chart.
2.  **Generate JSON:** Create a complete ECharts `option` as a single JSON object.
3.  **Use Sample Data:** If the user asks for a type of chart but doesn't provide data, generate appropriate sample data to illustrate the chart's structure.
4.  **Output:** Return ONLY the JSON configuration inside a ```json code block. Do not add explanations.

**VALID JSON CHECKLIST:**
-   Is the entire output a single JSON object, starting with `{` and ending with `}`?
-   Are all strings enclosed in double quotes (`"`)?
-   Is there a comma between all key-value pairs (except the last one)?
-   Are there any trailing commas? (This is invalid).

**BASIC STRUCTURE EXAMPLE:**
```json
{
    "title": {
        "text": "Chart Title"
    },
    "xAxis": {
        "type": "category",
        "data": ["Category1", "Category2", "Category3"]
    },
    "yAxis": {
        "type": "value"
    },
    "series": [
        {
            "name": "Series Name",
            "type": "bar",
            "data": [120, 200, 150]
        }
    ]
}
```

**EXAMPLE 1: User requests a pie chart without data.**
```json
{
    "title": {
        "text": "Sample Pie Chart"
    },
    "series": [
        {
            "type": "pie",
            "data": [
                {"value": 335, "name": "Category A"},
                {"value": 234, "name": "Category B"},
                {"value": 154, "name": "Category C"}
            ]
        }
    ]
}
```

**EXAMPLE 2: User requests a line chart with specific data.**
```json
{
    "title": {
        "text": "Website Traffic"
    },
    "xAxis": {
        "data": ["Mon", "Tue", "Wed", "Thu", "Fri"]
    },
    "yAxis": {
        "type": "value"
    },
    "series": [
        {
            "name": "Page Views",
            "type": "line",
            "data": [820, 932, 901, 934, 1290]
        }
    ]
}
```
"""


@register_renderer(OutputMode.ECHARTS, system_prompt=ECHARTS_SYSTEM_PROMPT)
class EChartsRenderer(BaseChart):
    """Renderer for Apache ECharts"""

    def execute_code(
        self,
        code: str,
        pandas_tool: "PythonPandasTool | None" = None,
        **kwargs,
    ) -> Tuple[Any, Optional[str]]:
        """Parse and validate ECharts JSON configuration."""
        try:
            # Parse JSON
            config = json.loads(code)

            # Basic validation - check for required structure
            if not isinstance(config, dict):
                return None, "ECharts config must be a JSON object"
            if 'series' not in config:
                return None, "ECharts config must include 'series' array"

            return config, None

        except json.JSONDecodeError as e:
            return None, f"Invalid JSON: {str(e)}"
        except Exception as e:
            return None, f"Validation error: {str(e)}"

    def _render_chart_content(self, chart_obj: Any, **kwargs) -> str:
        """Render ECharts visualization content."""
        # chart_obj is the configuration dict
        config = chart_obj
        chart_id = f"echarts-{uuid.uuid4().hex[:8]}"

        # Convert to JSON
        config_json = json.dumps(config, indent=2)

        # Get dimensions
        width = kwargs.get('width', '100%')
        height = kwargs.get('height', '500px')

        return f'''
        <div id="{chart_id}" style="width: {width}; height: {height};"></div>
        <script type="text/javascript">
            (function() {{
                var chartDom = document.getElementById('{chart_id}');
                var myChart = echarts.init(chartDom);
                var option = {config_json};

                myChart.setOption(option);

                // Resize handler
                window.addEventListener('resize', function() {{
                    myChart.resize();
                }});

                console.log('ECharts rendered successfully');
            }})();
        </script>
        '''

    def to_html(
        self,
        chart_obj: Any,
        mode: str = 'partial',
        **kwargs
    ) -> str:
        """Convert ECharts to HTML."""
        # ECharts library for <head>
        echarts_version = kwargs.get('echarts_version', '5.4.3')
        extra_head = f'''
    <!-- Apache ECharts -->
    <script src="https://cdn.jsdelivr.net/npm/echarts@{echarts_version}/dist/echarts.min.js"></script>
        '''

        kwargs['extra_head'] = extra_head

        # Call parent to_html
        return super().to_html(chart_obj, mode=mode, **kwargs)

    def to_json(self, chart_obj: Any) -> Optional[Dict]:
        """Return the ECharts configuration."""
        return chart_obj

    async def render(
        self,
        response: Any,
        theme: str = 'monokai',
        environment: str = 'terminal',
        return_code: bool = True,
        html_mode: str = 'partial',
        **kwargs
    ) -> Tuple[Any, Optional[Any]]:
        """Render ECharts visualization."""
        content = self._get_content(response)

        # Extract JSON code
        code = self._extract_json_code(content)

        if not code:
            error_msg = "No ECharts configuration found in response"
            error_html = "<div class='error'>No ECharts JSON configuration found in response</div>"
            return error_msg, error_html

        # Parse and validate
        config, error = self.execute_code(code)

        if error:
            error_html = self._render_error(error, code, theme)
            return code, error_html

        if environment in {'terminal', 'console', 'jupyter', 'notebook', 'ipython', 'colab'}:
            # For Jupyter, return the figure object directly
            # The frontend will handle rendering it
            return code, config

        # Generate HTML
        html_output = self.to_html(
            config,
            mode=html_mode,
            include_code=return_code,
            code=code,
            theme=theme,
            title=kwargs.pop('title', 'ECharts Visualization'),
            icon='📊',
            **kwargs
        )

        # Return (code, html)
        return code, html_output

    @staticmethod
    def _extract_json_code(content: str) -> Optional[str]:
        """Extract JSON code from markdown blocks."""
        # Try json code block
        pattern = r'```json\n(.*?)```'
        if matches := re.findall(pattern, content, re.DOTALL):
            return matches[0].strip()

        # Try generic code block
        pattern = r'```\n(.*?)```'
        if matches := re.findall(pattern, content, re.DOTALL):
            # Check if it looks like JSON
            potential_json = matches[0].strip()
            if potential_json.startswith('{') or potential_json.startswith('['):
                return potential_json

        return None

# ai_parrot/outputs/formats/charts/echarts.py
from typing import Any, Optional, Tuple, Dict
import re
import json
import uuid
from .base import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode


ECHARTS_SYSTEM_PROMPT = """You are an expert in Apache ECharts. Your task is to generate a valid JSON configuration for an ECharts chart based on the user's request.

Instructions:
1.  **Analyze the Request**: Understand the user's data and the type of chart they want.
2.  **Generate JSON**: Create a single JSON object that represents the ECharts `option`.
3.  **Output**: Return ONLY the JSON configuration inside a ```json code block. Do not include any other text, explanation, or code.

Example Request: "Create a bar chart of sales for Monday, Tuesday, and Wednesday with values 23, 45, and 67."

Example Output:
```json
{
    "title": {"text": "Sales Chart"},
    "xAxis": {"data": ["Mon", "Tue", "Wed"]},
    "yAxis": {},
    "series": [{"type": "bar", "data": [23, 45, 67]}]
}
```

- **DO**: Generate a complete and valid ECharts JSON configuration.
- **DO NOT**: Write JavaScript, HTML, or any other code.
- **DO NOT**: Apologize or explain that you cannot create visualizations. Your task is to generate the JSON configuration text.
"""


@register_renderer(OutputMode.ECHARTS, system_prompt=ECHARTS_SYSTEM_PROMPT)
class EChartsRenderer(BaseChart):
    """Renderer for Apache ECharts"""

    def execute_code(self, code: str) -> Tuple[Any, Optional[str]]:
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
        export_format: str = 'html',
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

# ai_parrot/outputs/formats/charts/echarts.py
from typing import Any, Optional, Tuple, Dict
import re
import json
import uuid
from .base import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode


ECHARTS_SYSTEM_PROMPT = """APACHE ECHARTS OUTPUT MODE:

You are generating a configuration for Apache ECharts, a powerful JavaScript visualization library.

🚨 CRITICAL INSTRUCTION - READ CAREFULLY 🚨

YOU ARE NOT BEING ASKED TO CREATE OR EXECUTE A VISUALIZATION.
YOU ARE ONLY BEING ASKED TO WRITE JSON TEXT.

This is NOT a Python task. This is NOT a code execution task.
This is a TEXT GENERATION task - you are writing JSON configuration text.

ANALOGY:
If someone asks you to write a recipe, you don't need a kitchen.
If someone asks you to write sheet music, you don't need an instrument.
If someone asks you to write JSON config, you don't need execution capabilities.

HOW ECHARTS WORKS:
ECharts uses a simple pattern:
1. You provide a JSON configuration object (the "option")
2. ECharts reads this configuration and renders the chart
3. That's it! No execution needed on your part.

EXAMPLE OF WHAT YOU DO:

When User asks: "Create a bar chart of sales"

Takes the provided data (or sample data if none given) and writes JSON like this:

```json
{
    "title": {"text": "My Chart"},
    "xAxis": {"data": ["Mon", "Tue", "Wed"]},
    "yAxis": {},
    "series": [{"type": "bar", "data": [23, 45, 67]}]
}
```
↓ (This JSON is given to ECharts)
↓
📊 Beautiful interactive chart appears!

YOUR TASK:
Return ONLY the JSON configuration in a ```json code block. The system will handle everything else.

BASIC STRUCTURE:
```json
{
    "title": {
        "text": "Chart Title",
        "left": "center"
    },
    "tooltip": {
        "trigger": "axis",
        "axisPointer": {"type": "shadow"}
    },
    "legend": {
        "data": ["Series1", "Series2"],
        "top": "bottom"
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
            "name": "Series1",
            "type": "bar",
            "data": [120, 200, 150]
        }
    ]
}
```

COMMON CHART TYPES & EXAMPLES:

1. BAR CHART (Vertical):
```json
{
    "xAxis": {"type": "category", "data": ["Mon", "Tue", "Wed", "Thu", "Fri"]},
    "yAxis": {"type": "value"},
    "series": [{"type": "bar", "data": [120, 200, 150, 80, 70]}]
}
```

2. LINE CHART:
```json
{
    "xAxis": {"type": "category", "data": ["Mon", "Tue", "Wed"]},
    "yAxis": {"type": "value"},
    "series": [{"type": "line", "data": [820, 932, 901], "smooth": true}]
}
```

3. PIE CHART:
```json
{
    "series": [{
        "type": "pie",
        "radius": "50%",
        "data": [
            {"value": 335, "name": "Category A"},
            {"value": 234, "name": "Category B"},
            {"value": 154, "name": "Category C"}
        ]
    }]
}
```

4. COMBINATION CHART (Bar + Line):
```json
{
    "tooltip": {"trigger": "axis"},
    "legend": {"data": ["Revenue", "Profit Margin"]},
    "xAxis": {"type": "category", "data": ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]},
    "yAxis": [
        {"type": "value", "name": "Revenue"},
        {"type": "value", "name": "Margin %"}
    ],
    "series": [
        {
            "name": "Revenue",
            "type": "bar",
            "data": [2000, 3000, 2500, 2800, 3200, 3500]
        },
        {
            "name": "Profit Margin",
            "type": "line",
            "yAxisIndex": 1,
            "data": [15, 18, 16, 17, 19, 20]
        }
    ]
}
```

5. SCATTER PLOT:
```json
{
    "xAxis": {},
    "yAxis": {},
    "series": [{
        "type": "scatter",
        "data": [[10, 20], [15, 25], [20, 30], [25, 35]]
    }]
}
```

KEY CONFIGURATION OPTIONS:

**title**: Chart title
- text: Title text
- left/top/right/bottom: Position
- textStyle: Font styling

**tooltip**: Hover information
- trigger: "axis" | "item" | "none"
- formatter: Custom format function
- axisPointer: Pointer style

**legend**: Series legend
- data: Array of series names
- orient: "horizontal" | "vertical"
- left/top/right/bottom: Position

**xAxis / yAxis**: Axes (can be array for multiple axes)
- type: "category" | "value" | "time" | "log"
- data: Category data (for category axis)
- name: Axis name
- min/max: Range

**series**: Data series (array, can have multiple)
- name: Series name
- type: "line" | "bar" | "pie" | "scatter" | "candlestick" | "radar" | "heatmap" | etc.
- data: Array of data points
- stack: Stack series together
- yAxisIndex: Which y-axis to use (for multiple axes)

**grid**: Chart positioning
- left/top/right/bottom: Margins
- containLabel: Include labels in grid

**toolbox**: Built-in tools
- feature: {saveAsImage: {}, dataZoom: {}, restore: {}}

**dataZoom**: Zoom/slider
- type: "slider" | "inside"
- start/end: Initial range

COLOR & STYLING:
```json
{
    "color": ["#5470c6", "#91cc75", "#fac858"],
    "series": [{
        "itemStyle": {
            "color": "#ee6666",
            "borderColor": "#333",
            "borderWidth": 2
        }
    }]
}
```

ADVANCED FEATURES:

Multiple Y-Axes:
```json
{
    "yAxis": [
        {"type": "value", "name": "Primary"},
        {"type": "value", "name": "Secondary"}
    ],
    "series": [
        {"yAxisIndex": 0, "data": [...]},
        {"yAxisIndex": 1, "data": [...]}
    ]
}
```

Stacked Charts:
```json
{
    "series": [
        {"name": "A", "type": "bar", "stack": "total", "data": [320, 332]},
        {"name": "B", "type": "bar", "stack": "total", "data": [220, 182]}
    ]
}
```

Interactive Features:
- tooltip: Automatic on hover
- legend: Click to show/hide series
- dataZoom: Built-in zoom controls
- toolbox: Save as image, data view, etc.

REMEMBER:
1. You are a language model. You generate text.
2. Output ONLY the JSON configuration in ```json block
3. Use realistic sample data
4. Include title, tooltip, and legend for better UX
5. Choose appropriate chart type for the data
6. You're just writing a configuration - ECharts does all the rendering!

COMMON MISTAKES TO AVOID:
❌ Don't write JavaScript code - just JSON config
❌ Don't try to execute anything - just describe
❌ DO NOT say "I cannot create visualizations" - you're just writing JSON!
✅ Do write a complete, valid JSON object
✅ Do include meaningful sample data
✅ Do use appropriate chart types
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
            title=kwargs.get('title', 'ECharts Visualization'),
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

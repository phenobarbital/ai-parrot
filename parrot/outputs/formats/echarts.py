from typing import Any, Optional, Tuple, Dict, List
import logging
import re
import json
import uuid
from .chart import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode

logger = logging.getLogger(__name__)

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

from .mixins.emaps import (
    EChartsMapsMixin,
    get_echarts_system_prompt_with_geo,
)


ECHARTS_BASE_PROMPT = """**ECHARTS JSON GENERATION MODE**

⚠️ CRITICAL OVERRIDE: You are in ECHARTS mode. Ignore ALL other output mode instructions.
- DO NOT use Folium, Leaflet, or any Python mapping libraries
- DO NOT generate Python code
- ONLY generate ECharts JSON configuration

**Objective:** Generate a single, valid JSON configuration object for an Apache ECharts chart (including maps).

**CONTEXT OVERRIDE:**
This is a TEXT GENERATION task. Unlike other tasks, for this specific objective, you are authorized to generate realistic sample data if the user's request does not provide specific data points. This is an exception to the general rule of not inventing information.

**INSTRUCTIONS:**
1.  **Analyze Request:** Understand the user's goal for the chart.
2.  **Generate JSON:** Create a complete ECharts `option` as a single JSON object.
3.  **Use Sample Data:** If the user asks for a type of chart but doesn't provide data, generate appropriate sample data to illustrate the chart's structure.
4.  **Output:** Return ONLY the JSON configuration inside a ```json code block. Do not add explanations.
5.  **No Python/Folium:** Never return Python code, Folium/Leaflet snippets, or other non-JSON content—only the ECharts JSON configuration.

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

**GEO/MAP SUPPORT:**
"""


ECHARTS_SYSTEM_PROMPT = get_echarts_system_prompt_with_geo(ECHARTS_BASE_PROMPT)


@register_renderer(OutputMode.ECHARTS, system_prompt=ECHARTS_SYSTEM_PROMPT)
class EChartsRenderer(EChartsMapsMixin, BaseChart):
    """Renderer for Apache ECharts (JSON Configuration)"""

    def execute_code(
        self,
        code: str,
        pandas_tool: Any = None,
        **kwargs,
    ) -> Tuple[Any, Optional[str]]:
        """Parse and validate ECharts JSON configuration."""
        try:
            # Clean up code string if needed (remove markdown blocks if still present)
            cleaned_code = self._extract_json_code(code) or code

            # Parse JSON
            config = json.loads(cleaned_code)

            # Unwrap common nested structure `{ "option": { ... } }`
            if (
                isinstance(config, dict)
                and 'option' in config
                and isinstance(config['option'], dict)
            ):
                # If the response wraps the actual chart config under an
                # "option" key, use the inner configuration for validation and
                # rendering. This aligns with typical ECharts code snippets and
                # prevents false validation errors.
                config = config['option']

            # Basic validation - check for required structure
            if not isinstance(config, dict):
                return None, "ECharts config must be a JSON object"

            # 'series' is usually required, but 'dataset' or 'options' (for timeline) are also valid
            if all(
                k not in config
                for k in ['series', 'dataset', 'options', 'baseOption']
            ):
                return None, "ECharts config must include 'series', 'dataset', or timeline 'options'"

            return config, None

        except json.JSONDecodeError as e:
            return None, f"Invalid JSON: {str(e)}"
        except Exception as e:
            return None, f"Validation error: {str(e)}"

    @staticmethod
    def _extract_chart_data(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract the underlying data from an ECharts configuration.

        Returns a dictionary with 'columns' and 'rows' keys for consistent
        data representation across chart types.

        Args:
            config: ECharts configuration dictionary

        Returns:
            Dictionary with 'columns' (list of column names) and 'rows' (list of row data),
            or None if data cannot be extracted.
        """
        try:
            if not isinstance(config, dict):
                return None

            all_data: List[Dict[str, Any]] = []

            # Method 1: Extract from 'dataset' (newer ECharts approach)
            if 'dataset' in config:
                dataset = config['dataset']
                datasets = dataset if isinstance(dataset, list) else [dataset]

                for ds in datasets:
                    if 'source' in ds:
                        source = ds['source']
                        if isinstance(source, list) and source:
                            # Check if first row is headers
                            if isinstance(source[0], list):
                                # Array format: first row might be headers
                                headers = source[0] if all(isinstance(h, str) for h in source[0]) else None
                                data_rows = source[1:] if headers else source

                                if headers:
                                    for row in data_rows:
                                        if isinstance(row, list):
                                            all_data.append(dict(zip(headers, row)))
                                else:
                                    for row in data_rows:
                                        if isinstance(row, list):
                                            all_data.append({f'col{i}': v for i, v in enumerate(row)})
                            elif isinstance(source[0], dict):
                                # Object format: each row is a dict
                                all_data.extend(source)

            # Method 2: Extract from 'series' data
            if 'series' in config:
                series_list = config['series']
                series_list = series_list if isinstance(series_list, list) else [series_list]

                for series in series_list:
                    if not isinstance(series, dict):
                        continue

                    series_name = series.get('name', 'series')
                    series_type = series.get('type', '')

                    # Handle 'data' in series
                    if 'data' in series:
                        data = series['data']
                        if isinstance(data, list):
                            for item in data:
                                if isinstance(item, dict):
                                    # Pie chart style: {name: 'X', value: 123}
                                    row = {'series': series_name, **item}
                                    all_data.append(row)
                                elif isinstance(item, (list, tuple)):
                                    # Array style: [x, y] or [x, y, z]
                                    row = {'series': series_name}
                                    for i, val in enumerate(item):
                                        row[f'dim{i}'] = val
                                    all_data.append(row)
                                else:
                                    # Scalar value - combine with xAxis if available
                                    pass  # Will handle via xAxis/yAxis data

            # Method 3: If xAxis/yAxis have data arrays
            x_data = None
            y_data = None

            if 'xAxis' in config:
                x_axis = config['xAxis']
                x_axis = x_axis if isinstance(x_axis, list) else [x_axis]
                for ax in x_axis:
                    if isinstance(ax, dict) and 'data' in ax:
                        x_data = ax['data']
                        break

            if 'yAxis' in config:
                y_axis = config['yAxis']
                y_axis = y_axis if isinstance(y_axis, list) else [y_axis]
                for ax in y_axis:
                    if isinstance(ax, dict) and 'data' in ax:
                        y_data = ax['data']
                        break

            # Combine axis data with series data if needed
            if x_data and not all_data:
                series_list = config.get('series', [])
                series_list = series_list if isinstance(series_list, list) else [series_list]

                for series in series_list:
                    if isinstance(series, dict) and 'data' in series:
                        s_data = series['data']
                        s_name = series.get('name', 'value')
                        if isinstance(s_data, list):
                            for i, (x_val, y_val) in enumerate(zip(x_data, s_data)):
                                # Handle y_val which could be dict, number, or list
                                if isinstance(y_val, dict):
                                    row = {'x': x_val, **y_val}
                                else:
                                    row = {'x': x_val, s_name: y_val}
                                all_data.append(row)

            if all_data:
                # Get columns from first row
                columns = list(all_data[0].keys()) if all_data else []
                return {
                    'columns': columns,
                    'rows': all_data
                }

        except Exception:
            # If we can't extract data, return None
            pass

        return None

    def _render_chart_content(self, chart_obj: Any, **kwargs) -> str:
        """Render ECharts visualization content (HTML/JS)."""
        # chart_obj is the configuration dict
        config = chart_obj
        chart_id = f"echarts-{uuid.uuid4().hex[:8]}"

        # Convert to JSON
        # config_json = json.dumps(config, indent=2)
        # Get dimensions
        width = kwargs.get('width', '100%')
        height = kwargs.get('height', '500px')
        # return f'''
        # <div id="{chart_id}" style="width: {width}; height: {height};"></div>
        # <script type="text/javascript">
        #     (function() {{
        #         var chartDom = document.getElementById('{chart_id}');
        #         if (!chartDom) return;

        #         var myChart = echarts.init(chartDom);
        #         var option = {config_json};

        #         option && myChart.setOption(option);

        #         // Resize handler
        #         window.addEventListener('resize', function() {{
        #             myChart.resize();
        #         }});

        #         console.log('ECharts {chart_id} rendered successfully');
        #     }})();
        # </script>
        # '''
        # Use mixin method for enhanced geo rendering
        return self._render_chart_content_geo(config, chart_id, width, height)

    def to_html(
        self,
        chart_obj: Any,
        mode: str = 'partial',
        **kwargs
    ) -> str:
        """Convert ECharts to HTML."""
        # ECharts library for <head>
        echarts_version = kwargs.get('echarts_version', '5.4.3')

        # Proper CDN URL (no markdown syntax)
        extra_head = kwargs.get('extra_head', '') + f"""
    <!-- Apache ECharts -->
    <script src="https://cdn.jsdelivr.net/npm/echarts@{echarts_version}/dist/echarts.min.js"></script>
        """

        kwargs['extra_head'] = extra_head

        # Call parent to_html
        return super().to_html(chart_obj, mode=mode, **kwargs)

    async def render(
        self,
        response: Any,
        theme: str = 'monokai',
        environment: str = 'html',
        include_code: bool = False,
        html_mode: str = 'partial',
        **kwargs
    ) -> Tuple[Any, Optional[Any], Optional[Dict[str, Any]]]:
        """
        Render ECharts visualization.

        Returns:
            Tuple[Any, Optional[Any], Optional[Dict[str, Any]]]: (code, output, data)
            - code goes to response.output
            - output goes to response.response
            - data contains the underlying chart data with 'columns' and 'rows'
        """

        # 1. Extract Code
        code = getattr(response, 'code', None)
        output_format = kwargs.get('output_format', environment)

        # Fallback: Extract from text if not in structured output
        if not code:
            content = self._get_content(response)
            code = self._extract_json_code(content)

        if not code:
            error_msg = "No ECharts configuration found in response"
            if output_format == 'terminal':
                return error_msg, None, None
            error_html = self._wrap_for_environment(
                f"<div class='error'>{error_msg}</div>",
                output_format
            )
            if output_format == 'html':
                return None, error_html, None
            return error_html, None, None

        # 2. Parse/Execute (Validation)
        config, error = self.execute_code(code)

        if error:
            logger.error("Failed to parse ECharts JSON: %s", error)
            if output_format == 'terminal':
                return f"Error parsing JSON: {error}\n\n{code}", None, None
            error_html = self._wrap_for_environment(
                self._render_error(error, code, theme),
                output_format
            )
            if output_format == 'html':
                return code, error_html, None
            return code, error_html, None

        # 3. Extract the underlying data from the config
        chart_data = self._extract_chart_data(config)

        # 4. Handle Terminal Environment (Show JSON)
        if output_format == 'terminal':
            if RICH_AVAILABLE:
                json_syntax = Syntax(
                    json.dumps(config, indent=2), "json", theme=theme, line_numbers=True
                )
                return Panel(json_syntax, title="📊 ECharts Configuration (JSON)", border_style="blue"), None, chart_data
            return json.dumps(config, indent=2), None, chart_data

        # 5. Generate HTML for Web/Jupyter
        html_output = self.to_html(
            config,
            mode=html_mode,
            include_code=include_code,
            code=code,
            theme=theme,
            title=kwargs.pop('title', 'ECharts Visualization'),
            icon='📊',
            **kwargs
        )

        # 6. Wrap for Environment
        if output_format in {'jupyter', 'notebook', 'ipython', 'colab'}:
            wrapped_html = self._wrap_for_environment(html_output, output_format)
        else:
            wrapped_html = html_output

        # 7. Return based on output format
        if output_format == 'html':
            # Return the generated code along with the wrapped HTML
            return code, wrapped_html, chart_data

        # Default: Return Code + Wrapped Output
        return code, wrapped_html, chart_data

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

        # Maybe the content IS just the JSON string?
        content = content.strip()
        return content if content.startswith('{') and content.endswith('}') else None


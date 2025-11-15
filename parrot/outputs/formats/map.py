from typing import Any, Optional, Tuple, Dict, Union
import re
import uuid
from io import StringIO, BytesIO
from pathlib import Path
import folium
import pandas as pd
from .base import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode

try:
    import geopandas as gpd
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    gpd = None


FOLIUM_SYSTEM_PROMPT = """FOLIUM MAP OUTPUT MODE:
Generate an interactive map using Folium.

REQUIREMENTS:
1. Return Python code in a markdown code block (```python)
2. Use folium library (import folium)
3. Store the map in a variable named 'm', 'map', 'folium_map', or 'my_map'
4. Include markers, popups, and other features as needed
5. Set appropriate zoom level and center coordinates
6. Add layers, controls, or plugins if requested
7. DO NOT call map.save() or display - return code only
8. IMPORTANT: If using custom tile layers, ALWAYS include attribution parameter

EXAMPLE:
```python
import folium

# Create base map
m = folium.Map(
    location=[40.7128, -74.0060],  # NYC coordinates
    zoom_start=12,
    tiles='OpenStreetMap'
)

# Add marker with popup
folium.Marker(
    location=[40.7128, -74.0060],
    popup='New York City',
    tooltip='Click for info',
    icon=folium.Icon(color='red', icon='info-sign')
).add_to(m)
```

DATA MODE (when DataFrame is provided):
If a DataFrame is provided with geographic data, return it as-is or with minimal processing.
The system will automatically combine it with GeoJSON to create choropleth maps.
Ensure the DataFrame has columns that can join with GeoJSON properties.

ADVANCED FEATURES:
- For heatmaps: use folium.plugins.HeatMap
- For polylines: use folium.PolyLine
- For custom tiles: ALWAYS include attribution parameter
  Example: folium.TileLayer('Stamen Terrain', attr='Map tiles by Stamen Design').add_to(m)
"""

FOLIUM_DATA_PROMPT = """FOLIUM DATA MODE:
You are generating data for a choropleth map.

REQUIREMENTS:
1. Return a pandas DataFrame with geographic data
2. Include a column that matches GeoJSON property keys (e.g., 'state', 'country', 'region_id')
3. Include numeric columns for visualization (e.g., 'population', 'value', 'score')
4. Data should be clean and ready for visualization

EXAMPLE OUTPUT (as Python code that creates DataFrame):
```python
import pandas as pd

data = pd.DataFrame({
    'state': ['California', 'Texas', 'Florida', 'New York'],
    'population': [39538223, 29145505, 21538187, 20201249],
    'gdp': [3.4, 2.1, 1.2, 1.9]
})
```
"""


@register_renderer(OutputMode.MAP, system_prompt=FOLIUM_SYSTEM_PROMPT)
class FoliumRenderer(BaseChart):
    """Renderer for Folium maps with support for DataFrames and GeoJSON"""

    @classmethod
    def get_expected_content_type(cls) -> type:
        """
        This renderer can work with both string (code) and DataFrame (data).
        We'll handle both in the render method.
        """
        return Union[str, pd.DataFrame] if GEOPANDAS_AVAILABLE else str

    def execute_code(
        self,
        code: str,
        pandas_tool: "PythonPandasTool | None" = None,
        execution_state: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Tuple[Any, Optional[str]]:
        """Execute Folium map code and return map object."""
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

        map_obj = next(
            (
                context[var_name]
                for var_name in ['m', 'map', 'folium_map', 'my_map', 'data', 'df']
                if var_name in context
            ),
            None,
        )

        if map_obj is None:
            return None, "Code must define a map variable (m, map, folium_map, my_map)"

        return map_obj, None

    def _create_choropleth_map(
        self,
        data: pd.DataFrame,
        geojson_path: str,
        key_on: str,
        columns: Tuple[str, str],
        **kwargs
    ) -> Any:
        """Create a choropleth map from DataFrame and GeoJSON."""
        if not GEOPANDAS_AVAILABLE:
            raise ImportError("geopandas is required for choropleth maps")

        if isinstance(geojson_path, (str, Path)):
            gdf = gpd.read_file(geojson_path)
        else:
            gdf = geojson_path

        center = kwargs.get('center')
        if center is None:
            bounds = gdf.total_bounds
            center = [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2]

        m = folium.Map(
            location=center,
            zoom_start=kwargs.get('zoom_start', 6),
            tiles=kwargs.get('tiles', 'OpenStreetMap')
        )

        folium.Choropleth(
            geo_data=gdf,
            name='choropleth',
            data=data,
            columns=columns,
            key_on=key_on,
            fill_color=kwargs.get('fill_color', 'YlOrRd'),
            fill_opacity=kwargs.get('fill_opacity', 0.7),
            line_opacity=kwargs.get('line_opacity', 0.2),
            legend_name=kwargs.get('legend_name', columns[1]),
            highlight=kwargs.get('highlight', True)
        ).add_to(m)

        if kwargs.get('layer_control', True):
            folium.LayerControl().add_to(m)

        if kwargs.get('add_tooltips', True):
            self._add_choropleth_tooltips(m, gdf, data, columns, key_on)

        return m

    def _add_choropleth_tooltips(
        self,
        map_obj: Any,
        gdf: gpd.GeoDataFrame,
        data: pd.DataFrame,
        columns: Tuple[str, str],
        key_on: str
    ):
        """Add interactive tooltips to choropleth map."""
        property_name = key_on.split('.')[-1]

        gdf_with_data = gdf.merge(
            data,
            left_on=property_name,
            right_on=columns[0],
            how='left'
        )

        folium.GeoJson(
            gdf_with_data,
            style_function=lambda x: {
                'fillColor': 'transparent',
                'color': 'transparent',
                'weight': 0
            },
            tooltip=folium.GeoJsonTooltip(
                fields=[property_name, columns[1]],
                aliases=[property_name.capitalize(), columns[1].capitalize()],
                localize=True
            )
        ).add_to(map_obj)

    def _render_chart_content(self, chart_obj: Any, **kwargs) -> str:
        """Render Folium map content."""
        map_id = f"folium-map-{uuid.uuid4().hex[:8]}"
        # Get the full HTML from Folium
        output = BytesIO()
        chart_obj.save(output, close_file=False)
        full_html = output.getvalue().decode('utf-8')
        output.close()

        # Extract the essential parts for embedding
        return self._extract_map_content(full_html, map_id)

    def to_html(
        self,
        chart_obj: Any,
        mode: str = 'partial',
        **kwargs
    ) -> str:
        """Convert Folium map to HTML - completely overridden."""
        # Pop kwargs to avoid duplicates
        include_code = kwargs.pop('include_code', False)
        code = kwargs.pop('code', None)
        theme = kwargs.pop('theme', 'monokai')
        title = kwargs.pop('title', 'Folium Map')
        icon = kwargs.pop('icon', '🗺️')

        # Get the complete Folium HTML
        full_html = chart_obj.get_root().render()

        if mode == 'complete':
            # Build code section if requested
            code_section = ''
            if include_code and code:
                code_section = self._build_code_section(code, theme, icon)

            # Return complete standalone HTML
            return self._build_folium_complete_html(
                full_html,
                title=title,
                code_section=code_section
            )

        else:  # partial mode
            # Extract components for embedding
            map_id = f"folium-map-{uuid.uuid4().hex[:8]}"
            partial_html = self._extract_map_content(full_html, map_id)

            # Add code section if requested
            if include_code and code:
                partial_html += '\n' + self._build_code_section(code, theme, icon)

            return partial_html

    @staticmethod
    def _build_folium_complete_html(
        folium_html: str,
        title: str = 'Folium Map',
        code_section: str = ''
    ) -> str:
        """
        Build complete HTML document wrapping Folium map.
        Extract scripts properly to ensure map renders.
        """
        # Extract everything between <head> tags
        head_match = re.search(r'<head[^>]*>(.*?)</head>', folium_html, re.DOTALL)
        head_content = head_match.group(1) if head_match else ''

        # Extract everything between <body> tags including ALL scripts
        body_match = re.search(r'<body[^>]*>(.*?)</body>', folium_html, re.DOTALL)

        if body_match:
            body_content = body_match.group(1)
        else:
            # Fallback: extract from </head> to </html>
            parts = folium_html.split('</head>')
            if len(parts) > 1:
                body_part = parts[1].replace('</html>', '').replace('</body>', '').strip()
                body_content = body_part
            else:
                body_content = folium_html

        # Ensure we have content
        if not body_content or len(body_content.strip()) < 100:
            # Last resort: use everything after the first div
            div_start = folium_html.find('<div')
            if div_start > 0:
                body_content = folium_html[div_start:]

        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>

    {head_content}

    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                         'Helvetica Neue', Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f7fa;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        .map-container {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.07), 0 2px 4px rgba(0,0,0,0.05);
            padding: 20px;
            margin-bottom: 20px;
        }}

        /* Override Folium's absolute positioning */
        .folium-map {{
            position: relative !important;
            width: 100% !important;
            height: 600px !important;
            border-radius: 8px;
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
            font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
            font-size: 14px;
            line-height: 1.6;
        }}

        @media (max-width: 768px) {{
            body {{
                padding: 10px;
            }}
            .map-container {{
                padding: 10px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="map-container">
            {body_content}
        </div>
        {code_section}
    </div>
</body>
</html>'''

    @staticmethod
    def _extract_map_content(full_html: str, map_id: str) -> str:
        """Extract map content from full Folium HTML for embedding."""
        # Extract ALL styles
        styles = []
        for style_match in re.finditer(r'<style[^>]*>(.*?)</style>', full_html, re.DOTALL):
            styles.append(style_match.group(0))

        # Extract external script tags
        script_pattern = r'<script[^>]*src=[^>]*></script>'
        external_scripts = re.findall(script_pattern, full_html)

        # Find the map div
        div_pattern = r'<div[^>]*id="(map_[^"]*)"[^>]*>.*?</div>'
        div_match = re.search(div_pattern, full_html, re.DOTALL)

        if div_match:
            original_id = div_match.group(1)
            map_div = div_match.group(0).replace(f'id="{original_id}"', f'id="{map_id}"')

            # Extract ALL inline scripts
            inline_scripts = []
            for script_match in re.finditer(r'<script[^>]*>(.*?)</script>', full_html, re.DOTALL):
                opening_tag = script_match.group(0)
                script_content = script_match.group(1)

                # Only process inline scripts (not external ones)
                if 'src=' not in opening_tag and script_content.strip():
                    # Replace map ID references
                    updated_script = script_content.replace(f'"{original_id}"', f'"{map_id}"')
                    updated_script = updated_script.replace(f"'{original_id}'", f"'{map_id}'")
                    inline_scripts.append(updated_script)
        else:
            map_div = f'<div id="{map_id}" style="width: 100%; height: 600px;"></div>'
            inline_scripts = []

        # Combine all parts
        parts = styles + external_scripts + [map_div]

        if inline_scripts:
            parts.append('<script>')
            parts.extend(inline_scripts)
            parts.append('</script>')

        return '\n'.join(parts)

    def to_json(self, chart_obj: Any) -> Optional[Dict]:
        """Export map metadata as JSON."""
        try:
            return {
                'center': chart_obj.location,
                'zoom': chart_obj.options.get('zoom_start', chart_obj.options.get('zoom', 10)),
                'tiles': chart_obj.tiles if hasattr(chart_obj, 'tiles') else 'OpenStreetMap',
                'type': 'folium_map'
            }
        except Exception as e:
            return {'error': str(e)}

    async def render(
        self,
        response: Any,
        theme: str = 'monokai',
        environment: str = 'terminal',
        return_code: bool = True,
        html_mode: str = 'partial',
        **kwargs
    ) -> Tuple[Any, Optional[Any]]:
        """
        Render Folium map.

        CRITICAL: Always returns (code, html) tuple
        - code goes to response.output
        - html goes to response.response
        """
        content = self._get_content(response)
        geojson_path = kwargs.get('geojson_path') or kwargs.get('geojson')

        # DATA MODE: DataFrame + GeoJSON = Choropleth
        if GEOPANDAS_AVAILABLE and isinstance(content, pd.DataFrame) and geojson_path:
            try:
                key_on = kwargs.get('key_on', 'feature.properties.name')
                join_column = kwargs.get('join_column', content.columns[0])
                value_column = kwargs.get('value_column', content.columns[1])

                map_obj = self._create_choropleth_map(
                    data=content,
                    geojson_path=geojson_path,
                    key_on=key_on,
                    columns=(join_column, value_column),
                    **kwargs
                )

                html_output = self.to_html(
                    map_obj,
                    mode=html_mode,
                    include_code=False,
                    title=kwargs.pop('title', 'Choropleth Map'),
                    **kwargs
                )

                data_info = f"Choropleth map with {len(content)} regions"
                # Return (code/description, html)
                return data_info, html_output

            except Exception as e:
                error_msg = f"Error creating choropleth: {str(e)}"
                error_html = f"<div class='error'>{error_msg}</div>"
                return error_msg, error_html

        # CODE MODE
        if isinstance(content, pd.DataFrame):
            code = self._extract_code(str(response.content or response.response))
        else:
            code = self._extract_code(content)

        if not code:
            error_msg = "No map code found in response"
            error_html = f"<div class='error'>{error_msg}</div>"
            return error_msg, error_html

        # Execute code
        result_obj, error = self.execute_code(
            code,
            pandas_tool=kwargs.pop('pandas_tool'),
            execution_state=kwargs.get('execution_state'),
            **kwargs,
        )

        if error:
            error_html = self._render_error(error, code, theme)
            # Return (code, error_html)
            return code, error_html

        if isinstance(result_obj, pd.DataFrame):
            # Return DataFrame as code, no HTML yet
            return result_obj, None

        # Result is a Folium map object
        map_obj = result_obj

        if environment in {'terminal', 'console', 'jupyter', 'notebook', 'ipython', 'colab'}:
            # For Jupyter, return the figure object directly
            # The frontend will handle rendering it
            return code, map_obj

        # Generate HTML
        html_output = self.to_html(
            map_obj,
            mode=html_mode,
            include_code=return_code,
            code=code,
            theme=theme,
            title=kwargs.pop('title', 'Folium Map'),
            **kwargs
        )

        # - response.output = code
        # - response.response = html
        return code, html_output

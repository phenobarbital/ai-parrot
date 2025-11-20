from typing import Any, Optional, Tuple, Dict, Union
import re
import uuid
from io import BytesIO
from pathlib import Path
import folium
import pandas as pd
from .chart import BaseChart
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
        pandas_tool: Any = None,
        execution_state: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Tuple[Any, Optional[str]]:
        """Execute Folium map code and return map object."""
        extra_namespace = None
        if pandas_tool is None:
            try:
                import folium
                extra_namespace = {'folium': folium}
            except ImportError:
                return None, "folium library not available"

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

        # Debug: print all variables in context
        print(f"CONTEXT KEYS: {list(context.keys())}")

        # Try to find map object
        map_obj = None
        for var_name in ['m', 'map', 'folium_map', 'my_map']:
            if var_name in context:
                obj = context[var_name]
                print(f"Found variable '{var_name}': {type(obj)}")
                # Check if it's a folium Map
                if hasattr(obj, '_name') and hasattr(obj, 'location'):
                    map_obj = obj
                    break

        # If still None, try to find any folium.Map object
        if map_obj is None:
            for var_name, obj in context.items():
                if var_name.startswith('_'):
                    continue
                # Check if it's a folium Map by class name
                if obj.__class__.__name__ == 'Map' and 'folium' in obj.__class__.__module__:
                    print(f"Found folium Map in variable '{var_name}'")
                    map_obj = obj
                    break

        # Handle DataFrame case (for data mode)
        if map_obj is None:
            for var_name in ['data', 'df']:
                if var_name in context and isinstance(context[var_name], pd.DataFrame):
                    return context[var_name], None

        if map_obj is None:
            # Provide helpful error message
            available_vars = [k for k in context.keys() if not k.startswith('_')]
            return None, (
                f"Code must define a folium Map variable (m, map, folium_map, or my_map). "
                f"Available variables: {', '.join(available_vars)}"
            )

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

    def _extract_head_resources(self, full_html: str) -> str:
        """
        Extracts scripts and styles from the <head> of the Folium HTML.
        This allows us to pass them to BaseChart to include in the header.
        """
        head_match = re.search(r'<head[^>]*>(.*?)</head>', full_html, re.DOTALL)
        if not head_match:
            return ""

        content = head_match[1]

        # Filter out standard meta tags to avoid duplication, keep scripts/styles
        resources = []
        resources.extend(
            line
            for line in content.split('\n')
            if '<script' in line or '<link' in line or '<style' in line
        )

        return '\n'.join(resources)

    def _render_chart_content(self, chart_obj: Any, **kwargs) -> str:
        """
        Render Folium map content (Body + Inline Scripts).
        This implements the abstract method from BaseChart.
        """
        map_id = f"folium-map-{uuid.uuid4().hex[:8]}"

        # Render the map to a complete HTML string
        full_html = chart_obj.get_root().render()

        # Extract the body content (divs and inline scripts)
        # We use the same logic as before, but now strictly for the body
        return self._extract_map_content(full_html, map_id)

    def to_html(
        self,
        chart_obj: Any,
        mode: str = 'partial',
        **kwargs
    ) -> str:
        """
        Convert Folium map to HTML using BaseChart's standard pipeline.
        """
        # 1. Generate the full Folium HTML internally to get resources
        full_html = chart_obj.get_root().render()

        # 2. Extract the CDN links and CSS from the head
        extra_head = self._extract_head_resources(full_html)

        # 3. Pass to parent to use standard template
        # Note: parent calls self._render_chart_content internally
        return super().to_html(
            chart_obj,
            mode=mode,
            extra_head=extra_head,  # Inject Folium JS/CSS here
            icon='🗺️',
            **kwargs
        )

    @staticmethod
    def _extract_map_content(full_html: str, map_id: str) -> str:
        """
        Extract map content (Divs + Script) from full Folium HTML.
        Renames IDs to prevent collisions in notebooks/web interfaces.
        """
        # 1. Extract Custom Styles (defined inside body/head usually)
        styles = []
        for style_match in re.finditer(r'<style[^>]*>(.*?)</style>', full_html, re.DOTALL):
            styles.append(style_match.group(0))

        # 2. Find the map div
        div_pattern = r'<div[^>]*id="(map_[^"]*)"[^>]*>.*?</div>'
        div_match = re.search(div_pattern, full_html, re.DOTALL)

        if div_match:
            original_id = div_match[1]
            # Replace ID
            map_div = div_match[0].replace(f'id="{original_id}"', f'id="{map_id}"')

            # 3. Extract Inline Scripts
            inline_scripts = []
            for script_match in re.finditer(r'<script[^>]*>(.*?)</script>', full_html, re.DOTALL):
                opening_tag = script_match.group(0)
                script_content = script_match.group(1)

                # Only process inline scripts (exclude src=...)
                if 'src=' not in opening_tag and script_content.strip():
                    # Update ID references in the JS
                    updated_script = script_content.replace(f'"{original_id}"', f'"{map_id}"')
                    updated_script = updated_script.replace(f"'{original_id}'", f"'{map_id}'")
                    inline_scripts.append(updated_script)
        else:
            # Fallback
            map_div = f'<div id="{map_id}" style="width: 100%; height: 600px;">Map Rendering Error</div>'
            inline_scripts = []

        # 4. Combine (Div first, then Scripts)
        parts = styles + [map_div]
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
        environment: str = 'html',
        include_code: bool = False,
        html_mode: str = 'partial',
        **kwargs
    ) -> Tuple[Any, Optional[Any]]:
        """
        Render Folium map.

        CRITICAL: Always returns (code, html) tuple
        - First return (code): Python code string for response.output
        - Second return (html): HTML content for response.response
        """
        # 1. Extract Code - Try response.code first, fallback to content extraction
        code = None
        try:
            code = getattr(response, 'code', None)
        except Exception:
            pass

        # Fallback: extract from content if code is not available
        if not code:
            try:
                content = self._get_content(response)
                code = self._extract_code(content)
            except Exception:
                pass

        # 2. Extract DataFrame - Try response.data first, then check content
        dataframe = None
        try:
            dataframe = getattr(response, 'data', None)
            if dataframe is not None and not isinstance(dataframe, pd.DataFrame):
                dataframe = None
        except Exception:
            pass

        # Fallback: check if content is a DataFrame
        if dataframe is None:
            try:
                content = self._get_content(response)
                if isinstance(content, pd.DataFrame):
                    dataframe = content
            except Exception:
                pass

        output_format = kwargs.get('output_format', environment)
        geojson_path = kwargs.get('geojson_path') or kwargs.get('geojson')

        # --- DATA MODE (DataFrame + GeoJSON) ---
        if GEOPANDAS_AVAILABLE and dataframe is not None and geojson_path:
            try:
                key_on = kwargs.get('key_on', 'feature.properties.name')
                join_column = kwargs.get('join_column', dataframe.columns[0])
                value_column = kwargs.get('value_column', dataframe.columns[1])

                map_obj = self._create_choropleth_map(
                    data=dataframe,
                    geojson_path=geojson_path,
                    key_on=key_on,
                    columns=(join_column, value_column),
                    **kwargs
                )

                # Use to_html (which now uses super().to_html)
                html_output = self.to_html(
                    map_obj,
                    mode=html_mode,
                    include_code=False,
                    title=kwargs.get('title', 'Choropleth Map'),
                    **kwargs
                )

                # CRITICAL: Always return (code_string, html)
                data_info = f"# Choropleth map with {len(dataframe)} regions"
                return data_info, html_output

            except Exception as e:
                error_msg = f"Error creating choropleth: {str(e)}"
                error_html = self._render_error(error_msg, code or "", theme)
                # CRITICAL: Return code first, then error HTML
                return code or f"# {error_msg}", error_html

        # --- CODE MODE ---
        if not code:
            error_msg = "No map code found in response"
            error_html = f"<div class='error'>{error_msg}</div>"
            # CRITICAL: Return error message as code, error HTML as second value
            return f"# {error_msg}", error_html

        # Validate code completeness - check if it actually creates a map
        if 'folium.Map' not in code and 'folium_map' not in code and 'm = ' not in code and 'map = ' not in code:
            warning_msg = "Warning: Code appears incomplete - no map creation detected"
            print(f"⚠️  {warning_msg}")
            print(f"CODE PREVIEW: {code[:200]}...")
            # Continue execution anyway - maybe the map is created differently

        # Execute code
        result_obj, error = self.execute_code(
            code,
            pandas_tool=kwargs.pop('pandas_tool', None),
            execution_state=kwargs.pop('execution_state', None),
            **kwargs,
        )

        if error:
            error_html = self._render_error(error, code, theme)
            # CRITICAL: Always return original code first, error HTML second
            return code, error_html

        # Handle if result is a DataFrame (data mode without GeoJSON)
        if isinstance(result_obj, pd.DataFrame):
            # Return code and DataFrame info
            df_info = f"<div>DataFrame with {len(result_obj)} rows and {len(result_obj.columns)} columns</div>"
            return code, df_info

        # Result is a Folium map object
        map_obj = result_obj

        # Handle Jupyter/Notebook Environment
        if output_format in {'jupyter', 'notebook', 'ipython', 'colab'}:
            # For Jupyter, return code and map object
            return code, map_obj

        # Generate HTML for Web/Terminal
        html_output = self.to_html(
            map_obj,
            mode=html_mode,
            include_code=include_code,
            code=code,
            theme=theme,
            title=kwargs.get('title', 'Folium Map'),
            **kwargs
        )

        print(f'CODE LENGTH: {len(code)}')
        print(f'HTML LENGTH: {len(html_output)}')
        print(f'HTML MODE: {html_mode}')

        # Return based on output format
        if output_format == 'json':
            return code, self.to_json(map_obj)

        # Default: Always return (code_string, html_string)
        return code, html_output

from typing import Any, Optional, Tuple, Dict, Union, List
import re
import uuid
from io import BytesIO
from pathlib import Path
import html
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
When user request a MAP, generate an interactive map using Folium by extracting and using geographic information from the available data.

MAP GENERATION STRATEGY:
1. First, create a filtered dataframe with the data you need (e.g., `map_data = df[...]`).
2. The tool will confirm the variable creation.
3. THEN, in the same or next turn, generate the Folium code referencing `map_data`.
4. DO NOT print the content of `map_data`.
5. ALWAYS return the map as Python code in a markdown block (```python).

🚨 CRITICAL REQUIREMENTS: 🚨

1. **ALWAYS analyze the available data for geographic information**:
   - Look for columns with: latitude, longitude, lat, lon, coordinates
   - Look for location columns: city, state, country, address, location, place
   - Look for postal codes or zip codes that can be geocoded

2. **Extract coordinates**:
   - If you have lat/lon columns, use them directly
   - If you have addresses/cities, you MUST extract or infer coordinates
   - For well-known cities, use their standard coordinates
   - Example: "Miami, Florida" → [25.7617, -80.1918]

3. **Validate coordinates before using them**:
   - NEVER use coordinates (0.0, 0.0) - these are invalid placeholders
   - For invalid/missing coordinates:
     * If you have an address, try to infer approximate location
     * If location is in same city as other valid points, estimate nearby
     * If no inference possible, SKIP the marker entirely
   - Coordinate sanity checks:
     * Latitude must be between -90 and 90
     * Longitude must be between -180 and 180
     * For US locations: lat ~25-50, lon ~-125 to -65

4. **Return Python code in markdown block** (```python):
   - Import folium at the top
   - Store map in variable: 'm', 'map', 'folium_map', or 'my_map'
   - Add ALL relevant data points as markers (except invalid ones)
   - Include popups with useful information
   - DO NOT call map.save() or display methods

5. **Map configuration**:
   - Center map on the average/median of all VALID locations
   - Set appropriate zoom level (10-14 for cities, 5-8 for regions)
   - Use descriptive popups and tooltips


BASIC EXAMPLE:
```python
import folium

# Create base map with correct coordinate order
m = folium.Map(
    location=[40.7128, -74.0060],  # [latitude, longitude]
    zoom_start=12,
    tiles='OpenStreetMap'
)

# Add marker with correct coordinate order
folium.Marker(
    location=[40.7128, -74.0060],  # [latitude, longitude]
    popup='New York City',
    tooltip='Click for info',
    icon=folium.Icon(color='red', icon='info-sign')
).add_to(m)
```

MULTIPLE MARKERS EXAMPLE:
```python
import folium
import pandas as pd

# Sample data with lat/lon columns
stores = pd.DataFrame({
    'name': ['Store A', 'Store B', 'Store C'],
    'latitude': [40.7128, 34.0522, 41.8781],   # lat column
    'longitude': [-74.0060, -118.2437, -87.6298]  # lon column
})

# Calculate center from data
center_lat = stores['latitude'].median()
center_lon = stores['longitude'].median()

# Create map centered on data
m = folium.Map(
    location=[center_lat, center_lon],  # ALWAYS [lat, lon]
    zoom_start=5
)

# Add markers - iterate with correct order
for idx, row in stores.iterrows():
    folium.Marker(
        location=[row['latitude'], row['longitude']],  # [lat, lon]
        popup=f"Store: {row['name']}",
        tooltip=row['name']
    ).add_to(m)
```

COORDINATE VALIDATION FUNCTION (OPTIONAL):
```python
def validate_coords(lat, lon, name=""):
    \"\"\"Validate lat/lon are in correct ranges.\"\"\"
    if not (-90 <= lat <= 90):
        print(f"⚠️ Invalid latitude for {name}: {lat}")
        return False
    if not (-180 <= lon <= 180):
        print(f"⚠️ Invalid longitude for {name}: {lon}")
        return False
    return True

# Use before adding markers:
if validate_coords(lat, lon, store_name):
    folium.Marker(location=[lat, lon], ...).add_to(m)
```

DATA MODE (when DataFrame is provided):
If a DataFrame is provided with geographic data, return it as-is or with minimal processing.
The system will automatically combine it with GeoJSON to create choropleth maps.
Ensure the DataFrame has columns that can join with GeoJSON properties.

ADVANCED FEATURES:
- For heatmaps: use folium.plugins.HeatMap
- For polylines: use folium.PolyLine (coordinates in [lat, lon] order!)
- For circles: folium.Circle(location=[lat, lon], radius=...)
- For custom tiles: ALWAYS include attribution parameter
    Example: folium.TileLayer('Stamen Terrain', attr='Map tiles by Stamen Design').add_to(m)
- Use clear, informative popups and tooltips

COMMON MISTAKES TO AVOID:
❌ Using [lon, lat] order instead of [lat, lon]
❌ Forgetting to calculate map center from data
❌ Using fixed zoom level that doesn't fit the data
❌ Not validating coordinate ranges
❌ Swapping latitude and longitude column references

FINAL CHECKLIST BEFORE RETURNING CODE:
1. ✓ All folium.Map() calls use [latitude, longitude] order
2. ✓ All folium.Marker() calls use [latitude, longitude] order
3. ✓ All coordinate arrays/lists use [latitude, longitude] order
4. ✓ Map center is calculated from actual marker positions
5. ✓ Zoom level is appropriate for geographic spread
6. ✓ No longitude values in the latitude position
7. ✓ No latitude values in the longitude position

Remember: LATITUDE FIRST, LONGITUDE SECOND. Always [lat, lon], never [lon, lat]!
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

    def _is_valid_latitude(self, value: Any) -> bool:
        """Check if value is a valid latitude (-90 to 90)."""
        return isinstance(value, (int, float)) and -90 <= value <= 90


    def _is_valid_longitude(self, value: Any) -> bool:
        """Check if value is a valid longitude (-180 to 180)."""
        return isinstance(value, (int, float)) and -180 <= value <= 180


    def _detect_coordinate_swap(self, lat: float, lon: float) -> bool:
        """
        Detect if coordinates are likely swapped using multiple heuristics.

        Returns True if coordinates appear to be swapped.
        """
        # Basic validation - both must be numeric
        if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
            return False

        # Check 1: Basic range check
        lat_in_lat_range = -90 <= lat <= 90
        lon_in_lon_range = -180 <= lon <= 180
        lat_in_lon_range = -180 <= lat <= 180
        lon_in_lat_range = -90 <= lon <= 90

        # If current order is invalid but swapped would be valid
        if not (lat_in_lat_range and lon_in_lon_range):
            if lat_in_lon_range and lon_in_lat_range:
                return True  # Definitely swapped

        # Check 2: Magnitude heuristic for common locations
        # Most inhabited locations: lat magnitude < 70, lon can be larger
        if abs(lat) > 90:
            return True  # Invalid latitude, must be swapped

        # Check 3: Sign heuristic for Western Hemisphere (Americas, especially US)
        # For US/Americas: latitude should be positive (20-50), longitude negative (-60 to -180)
        if lat < 0 and lon > 0:
            # Negative latitude, positive longitude = likely Southern Hemisphere or swapped
            # Check if swapping would make sense for US/Americas
            if -130 <= lat <= -60 and 20 <= lon <= 50:
                print(f"  📍 Detected likely swap (US coordinates): [{lat}, {lon}] → [{lon}, {lat}]")
                return True

        # Check 4: Extreme latitude with moderate longitude
        # If latitude is very high/low (near poles) but longitude is moderate, might be swapped
        if abs(lat) > 75 and abs(lon) < 75:
            # Check if swapping makes more sense
            if abs(lon) > 10 and abs(lat) > abs(lon):
                # Probably swapped (unless actually near poles)
                if not (85 <= abs(lat) <= 90):  # Not actually at poles
                    return True

        # Check 5: Florida-specific heuristic
        # Florida: lat 24.5-31 (positive), lon -80 to -87 (negative)
        if -90 <= lat <= -75 and 20 <= lon <= 35:
            print(f"  🌴 Detected Florida coordinates swap: [{lat}, {lon}] → [{lon}, {lat}]")
            return True

        return False


    def _normalize_location(self, location: Any) -> Tuple[Any, bool]:
        """
        Ensure coordinates are in [lat, lon] order and within valid ranges.

        Returns:
            (normalized_location, was_swapped)
        """
        if not isinstance(location, (list, tuple)) or len(location) < 2:
            return location, False

        lat, lon = location[0], location[1]

        # Skip if not numeric
        if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
            return location, False

        # Check if coordinates appear to be swapped
        if self._detect_coordinate_swap(lat, lon):
            # Swap coordinates
            fixed_location = [lon, lat, *location[2:]]
            return fixed_location, True

        # Check if coordinates are valid as-is
        if self._is_valid_latitude(lat) and self._is_valid_longitude(lon):
            return list(location), False

        # Invalid coordinates but swapping doesn't help
        print(f"  ⚠️ Invalid coordinates (can't auto-fix): [{lat}, {lon}]")
        return list(location), False


    def _prepare_map_coordinates(self, map_obj: Any) -> None:
        """
        Normalize marker coordinates and recenter the map.

        Improvements:
        - Better coordinate validation
        - More detailed logging
        - Robust center calculation
        """
        coordinates: List[Tuple[float, float]] = []
        swaps = 0
        invalid = 0
        total_markers = 0

        print("\n📍 Validating map coordinates...")

        for child in getattr(map_obj, '_children', {}).values():
            location = getattr(child, 'location', None)
            if location is None:
                continue

            total_markers += 1
            original_location = location.copy() if isinstance(location, list) else list(location)

            fixed_location, was_swapped = self._normalize_location(location)

            if was_swapped:
                setattr(child, 'location', fixed_location)
                swaps += 1
                print(f"  ✓ Fixed: {original_location} → {fixed_location}")

            # Collect valid coordinates for centering
            if isinstance(fixed_location, (list, tuple)) and len(fixed_location) >= 2:
                first, second = fixed_location[0], fixed_location[1]
                if self._is_valid_latitude(first) and self._is_valid_longitude(second):
                    coordinates.append((first, second))
                else:
                    invalid += 1
                    print(f"  ⚠️ Invalid coordinates (skipping): {fixed_location}")

        # Update map center based on valid coordinates
        if coordinates:
            lats = pd.Series([lat for lat, _ in coordinates])
            lons = pd.Series([lon for _, lon in coordinates])

            new_center = [float(lats.median()), float(lons.median())]
            old_center = map_obj.location

            map_obj.location = new_center

            print(f"\n📊 Coordinate validation summary:")
            print(f"  Total markers: {total_markers}")
            print(f"  Valid coordinates: {len(coordinates)}")
            print(f"  Swapped and fixed: {swaps}")
            print(f"  Invalid (skipped): {invalid}")
            print(f"  Map center: {old_center} → {new_center}")

            # Suggest appropriate zoom level based on coordinate spread
            lat_range = float(lats.max() - lats.min())
            lon_range = float(lons.max() - lons.min())
            max_range = max(lat_range, lon_range)

            if max_range < 0.1:
                suggested_zoom = 13  # Very tight cluster
            elif max_range < 1:
                suggested_zoom = 10  # City level
            elif max_range < 5:
                suggested_zoom = 7   # Regional
            elif max_range < 20:
                suggested_zoom = 5   # Multi-state
            else:
                suggested_zoom = 3   # Continental

            # Update zoom if it seems wrong
            current_zoom = map_obj.options.get('zoom', map_obj.options.get('zoom_start', 10))
            if abs(current_zoom - suggested_zoom) > 3:
                print(f"  💡 Suggested zoom: {suggested_zoom} (current: {current_zoom})")

        else:
            print(f"  ⚠️ No valid coordinates found among {total_markers} markers")

        print()  # Empty line for readability

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
        # print(f"CONTEXT KEYS: {list(context.keys())}")

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

        # Capture full script/style/link tags to avoid malformed HTML fragments
        resources: List[str] = []
        for pattern in [
            r'<script[^>]*>.*?</script>',
            r'<style[^>]*>.*?</style>',
            r'<link[^>]*?>',
        ]:
            resources.extend(re.findall(pattern, content, re.DOTALL))

        return '\n'.join(resources)

    def _render_chart_content(self, chart_obj: Any, **kwargs) -> str:
        """
        Render Folium map content (Body + Inline Scripts).
        This implements the abstract method from BaseChart.

        Note: we keep the original Folium-generated map ID to ensure all
        associated styles and scripts continue to reference the same element.
        This prevents broken layouts where the map container ends up with no
        height because the IDs in the head and body fall out of sync.
        """
        # Render the map to a complete HTML string
        full_html = chart_obj.get_root().render()

        # Extract the body content (divs and inline scripts)
        # We use the same logic as before, but now strictly for the body
        explanation = kwargs.get('explanation')
        explanation_block = self._build_explanation_section(explanation)
        return f"{explanation_block}{self._extract_map_content(full_html)}"

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
    def _extract_map_content(full_html: str, map_id: Optional[str] = None) -> str:
        """
        Extract map content (Divs + Script) from full Folium HTML.

        We intentionally keep the original Folium-generated map ID unless a
        custom ID is provided. This avoids mismatches between IDs referenced in
        <head> resources (styles/scripts) and the body content that would
        otherwise leave the map container with no height.
        """
        # 1. Extract Custom Styles
        styles = []
        for style_match in re.finditer(r'<style[^>]*>(.*?)</style>', full_html, re.DOTALL):
            styles.append(style_match.group(0))

        # 2. Find the map div
        div_pattern = r'<div[^>]*id="(map_[^"]*)"[^>]*>.*?</div>'
        div_match = re.search(div_pattern, full_html, re.DOTALL)

        if div_match:
            original_id = div_match[1]
            map_id = map_id or original_id

            # Obtenemos el HTML crudo del div
            map_div = div_match[0]

            # --- PASO 1: Actualizar el ID ---
            map_div = map_div.replace(f'id="{original_id}"', f'id="{map_id}"')

            # --- PASO 2: Inyectar Altura Fija (La solución al problema) ---
            # Definimos la altura deseada
            fixed_height_style = "height: 600px; min-height: 600px;"

            # Intentamos reemplazar la altura porcentual que genera Folium (ej: height: 100.0%;)
            # Usamos Regex para ser flexibles con espacios o decimales
            map_div, num_subs = re.subn(
                r'height:\s*100(\.0)?%;',
                fixed_height_style,
                map_div
            )

            # Si el regex no encontró nada (ej: Folium cambió formato), inyectamos el estilo a la fuerza
            if num_subs == 0:
                if 'style="' in map_div:
                    # Agregamos al principio del estilo existente con !important por si acaso
                    map_div = map_div.replace('style="', f'style="{fixed_height_style} ')
                else:
                    # Si no hay estilo, creamos uno
                    map_div = map_div.replace('<div', f'<div style="{fixed_height_style}"')

            # 3. Extract Inline Scripts
            inline_scripts = []
            for script_match in re.finditer(r'<script[^>]*>(.*?)</script>', full_html, re.DOTALL):
                opening_tag = script_match.group(0)
                script_content = script_match.group(1)

                if 'src=' not in opening_tag and script_content.strip():
                    updated_script = script_content.replace(f'"{original_id}"', f'"{map_id}"')
                    updated_script = updated_script.replace(f"'{original_id}'", f"'{map_id}'")
                    inline_scripts.append(updated_script)
        else:
            map_id = map_id or f'folium-map-{uuid.uuid4().hex[:8]}'
            # Fallback en caso de error de regex general
            map_div = f'<div id="{map_id}" style="width: 100%; height: 600px;">Map Rendering Error</div>'
            inline_scripts = []

        # 4. Combine with proper newlines
        parts = []

        # Add styles with separation
        if styles:
            parts.extend(styles)
            parts.append('')  # Extra newline after styles

        # Add map div
        parts.append(map_div)
        parts.append('')  # Extra newline after div

        # Add scripts with proper formatting
        if inline_scripts:
            parts.append('<script>')
            parts.append('')  # Newline after opening tag
            parts.extend(inline_scripts)
            parts.append('')  # Newline before closing tag
            parts.append('</script>')

        # Join with double newlines for readability
        return '\n\n'.join(parts)

    @staticmethod
    def _build_explanation_section(explanation: Optional[str]) -> str:
        """Build a collapsible explanation section to show above the map."""
        if not explanation:
            return ""

        escaped_explanation = html.escape(str(explanation))

        return '''
        <style>
            .ap-map-explanation {margin-bottom: 16px;}
            .ap-map-explanation details {border: 1px solid #e0e0e0; border-radius: 6px; overflow: hidden; background: #ffffff;}
            .ap-map-explanation summary {background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); color: #fff; padding: 12px 16px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; font-weight: 600; user-select: none;}
            .ap-map-explanation .ap-toggle-icon {transition: transform 0.3s ease;}
            .ap-map-explanation details[open] .ap-toggle-icon {transform: rotate(90deg);}
            .ap-map-explanation .ap-explanation-content {padding: 12px 16px; background: #f8fafc; color: #1f2937;}
            .ap-map-explanation p {margin: 0; line-height: 1.6;}
        </style>
        <div class="ap-map-explanation">
            <details>
                <summary>
                    <span>📝 Explicación del mapa</span>
                    <span class="ap-toggle-icon">▶</span>
                </summary>
                <div class="ap-explanation-content">
                    <p>{escaped_explanation}</p>
                </div>
            </details>
        </div>
        '''.format(escaped_explanation=escaped_explanation)

    @staticmethod
    def _is_latitude(value: Any) -> bool:
        return isinstance(value, (int, float)) and -90 <= value <= 90

    @staticmethod
    def _is_longitude(value: Any) -> bool:
        return isinstance(value, (int, float)) and -180 <= value <= 180

    def _normalize_location(self, location: Any) -> Tuple[Any, bool]:
        """Ensure coordinates are in [lat, lon] order and within valid ranges."""
        if not isinstance(location, (list, tuple)) or len(location) < 2:
            return location, False

        lat, lon = location[0], location[1]
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return location, False

        lat_first_valid = self._is_latitude(lat) and self._is_longitude(lon)
        lon_first_valid = self._is_latitude(lon) and self._is_longitude(lat)

        # Detect clear reversals or polar misplacements
        if not lat_first_valid and lon_first_valid:
            return [lon, lat, *location[2:]], True

        # Heuristic: if latitude magnitude is extreme while longitude is moderate, swap
        if lat_first_valid and abs(lat) > 75 and abs(lon) < 75 and lon_first_valid:
            return [lon, lat, *location[2:]], True

        return list(location), False

    def _prepare_map_coordinates(self, map_obj: Any) -> None:
        """Normalize marker coordinates and recenter the map."""
        coordinates: List[Tuple[float, float]] = []
        swaps = 0

        for child in getattr(map_obj, '_children', {}).values():
            location = getattr(child, 'location', None)
            fixed_location, swapped = self._normalize_location(location)
            if swapped:
                setattr(child, 'location', fixed_location)
                swaps += 1
            if isinstance(fixed_location, (list, tuple)) and len(fixed_location) >= 2:
                first, second = fixed_location[0], fixed_location[1]
                if self._is_latitude(first) and self._is_longitude(second):
                    coordinates.append((first, second))

        if coordinates:
            lats = pd.Series([lat for lat, _ in coordinates])
            lons = pd.Series([lon for _, lon in coordinates])
            map_obj.location = [float(lats.median()), float(lons.median())]
            if swaps:
                print(f"Corrected {swaps} marker coordinate pairs to [lat, lon] order.")

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
        explanation = getattr(response, 'explanation', None)

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
                    explanation=explanation,
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

        # Normalize coordinates and center based on available markers
        self._prepare_map_coordinates(map_obj)

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
            explanation=explanation,
            **kwargs
        )

        # Return based on output format
        if output_format == 'json':
            return code, self.to_json(map_obj)

        # Default: Always return (code_string, html_string)
        return code, html_output

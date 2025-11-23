"""
ECharts Geo Extension for AI-Parrot
Adds geographic visualization capabilities to EChartsRenderer
"""
from typing import Any, Optional, Dict, List, Tuple, Union
import json
import logging
import uuid

logger = logging.getLogger(__name__)


# Extended system prompt with geo support
ECHARTS_GEO_EXTENSION = """
**GEO/MAP SUPPORT:**

ECharts supports powerful geographic visualizations using the `geo` component and map series types.

**COORDINATE SYSTEM:**
⚠️ IMPORTANT: ECharts uses [longitude, latitude] order (opposite of Leaflet/Folium)
- Correct: [-80.1918, 25.7617] (Miami, FL)
- Wrong: [25.7617, -80.1918]

**BASIC MAP STRUCTURE:**
```json
{
    "title": {"text": "Map Title"},
    "tooltip": {"trigger": "item"},
    "geo": {
        "map": "USA",
        "roam": true,
        "center": [-95, 38],
        "zoom": 1.2,
        "itemStyle": {
            "areaColor": "#f3f3f3",
            "borderColor": "#999"
        },
        "emphasis": {
            "itemStyle": {
                "areaColor": "#e0e0e0"
            }
        }
    },
    "series": [{
        "type": "scatter",
        "coordinateSystem": "geo",
        "data": [
            {"name": "Location 1", "value": [-80.19, 25.76, 100]},
            {"name": "Location 2", "value": [-118.24, 34.05, 200]}
        ],
        "symbolSize": function(val) { return val[2] / 10; },
        "itemStyle": {"color": "#c23531"}
    }]
}
```

**MAP TYPES:**

1. **Scatter Map** (Point locations):
```json
{
    "geo": {"map": "USA", "roam": true},
    "series": [{
        "type": "scatter",
        "coordinateSystem": "geo",
        "data": [
            {"name": "Store A", "value": [-80.19, 25.76, 50]},
            {"name": "Store B", "value": [-118.24, 34.05, 100]}
        ],
        "symbolSize": 10
    }]
}
```

2. **Lines Map** (Routes/Connections):
```json
{
    "geo": {"map": "world", "roam": true},
    "series": [{
        "type": "lines",
        "coordinateSystem": "geo",
        "data": [
            {
                "coords": [[-118.24, 34.05], [-74.01, 40.71]]
            }
        ],
        "lineStyle": {"color": "#c23531", "width": 2}
    }]
}
```

3. **Heatmap** (Density visualization):
```json
{
    "geo": {"map": "USA", "roam": true},
    "visualMap": {
        "min": 0,
        "max": 100,
        "calculable": true,
        "inRange": {"color": ["#50a3ba", "#eac736", "#d94e5d"]}
    },
    "series": [{
        "type": "heatmap",
        "coordinateSystem": "geo",
        "data": [
            [-80.19, 25.76, 75],
            [-118.24, 34.05, 90]
        ]
    }]
}
```

4. **Choropleth** (Colored regions):
```json
{
    "visualMap": {
        "min": 0,
        "max": 1000,
        "text": ["High", "Low"],
        "calculable": true
    },
    "series": [{
        "type": "map",
        "map": "USA",
        "roam": true,
        "data": [
            {"name": "California", "value": 1000},
            {"name": "Texas", "value": 800},
            {"name": "Florida", "value": 600}
        ]
    }]
}
```

**AVAILABLE BASE MAPS:**
- "USA" - United States map
- "world" - World map (default)
- Custom GeoJSON can be registered dynamically

**DATA VALIDATION FOR MAPS:**
1. Extract geographic information from available data
2. Validate coordinates are in [lon, lat] order
3. Filter invalid coordinates (0, 0) or out-of-range values
4. For US locations: lon ~-125 to -65, lat ~25 to 50
5. Center map on average of valid coordinates

**GEOCODING REFERENCE (US Cities):**
Remember: [longitude, latitude] order!
- Miami, FL: [-80.1918, 25.7617]
- New York, NY: [-74.0060, 40.7128]
- Los Angeles, CA: [-118.2437, 34.0522]
- Chicago, IL: [-87.6298, 41.8781]
- Houston, TX: [-95.3698, 29.7604]
- Phoenix, AZ: [-112.0740, 33.4484]
- Philadelphia, PA: [-75.1652, 39.9526]
- San Antonio, TX: [-98.4936, 29.4241]
- San Diego, CA: [-117.1611, 32.7157]
- Dallas, TX: [-96.7970, 32.7767]

**EXAMPLE - Complete Map with Data:**
```json
{
    "title": {
        "text": "Retail Locations in Miami Area",
        "left": "center"
    },
    "tooltip": {
        "trigger": "item",
        "formatter": "{b}: {c}"
    },
    "geo": {
        "map": "USA",
        "roam": true,
        "center": [-80.19, 25.76],
        "zoom": 8,
        "itemStyle": {
            "areaColor": "#f3f3f3",
            "borderColor": "#999"
        }
    },
    "series": [{
        "name": "Stores",
        "type": "scatter",
        "coordinateSystem": "geo",
        "data": [
            {"name": "Best Buy 1502", "value": [-80.37, 25.79, 1]},
            {"name": "Costco 1023", "value": [-80.41, 25.65, 1]},
            {"name": "Target 968", "value": [-80.32, 25.74, 1]}
        ],
        "symbolSize": 12,
        "itemStyle": {
            "color": "#c23531"
        },
        "label": {
            "show": false,
            "formatter": "{b}"
        },
        "emphasis": {
            "label": {
                "show": true
            }
        }
    }]
}
```
"""


# US State coordinate reference
US_STATE_CENTERS = {
    'Alabama': [-86.9023, 32.3182],
    'Alaska': [-152.4044, 61.3707],
    'Arizona': [-111.4312, 34.0489],
    'Arkansas': [-92.3731, 34.7465],
    'California': [-119.4179, 36.7783],
    'Colorado': [-105.7821, 39.5501],
    'Connecticut': [-72.7554, 41.6032],
    'Delaware': [-75.5071, 39.3185],
    'Florida': [-81.5158, 27.6648],
    'Georgia': [-83.5007, 33.2490],
    'Hawaii': [-155.5828, 19.8968],
    'Idaho': [-114.7420, 44.0682],
    'Illinois': [-89.3985, 40.6331],
    'Indiana': [-86.1349, 40.2672],
    'Iowa': [-93.0977, 41.8780],
    'Kansas': [-98.4842, 39.0119],
    'Kentucky': [-84.2700, 37.8393],
    'Louisiana': [-91.9623, 30.9843],
    'Maine': [-69.4455, 45.2538],
    'Maryland': [-76.6413, 39.0458],
    'Massachusetts': [-71.3824, 42.4072],
    'Michigan': [-85.6024, 44.3148],
    'Minnesota': [-94.6859, 46.7296],
    'Mississippi': [-89.3985, 32.3547],
    'Missouri': [-92.6038, 37.9643],
    'Montana': [-110.3626, 46.8797],
    'Nebraska': [-99.9018, 41.4925],
    'Nevada': [-116.4194, 38.8026],
    'New Hampshire': [-71.5724, 43.1939],
    'New Jersey': [-74.4057, 40.0583],
    'New Mexico': [-105.8701, 34.5199],
    'New York': [-75.5268, 43.2994],
    'North Carolina': [-79.0193, 35.7596],
    'North Dakota': [-101.0020, 47.5515],
    'Ohio': [-82.9071, 40.4173],
    'Oklahoma': [-97.0929, 35.4676],
    'Oregon': [-120.5542, 43.8041],
    'Pennsylvania': [-77.1945, 41.2033],
    'Rhode Island': [-71.4774, 41.5801],
    'South Carolina': [-81.1637, 33.8361],
    'South Dakota': [-99.9018, 43.9695],
    'Tennessee': [-86.5804, 35.5175],
    'Texas': [-99.9018, 31.9686],
    'Utah': [-111.0937, 39.3200],
    'Vermont': [-72.5778, 44.5588],
    'Virginia': [-78.6569, 37.4316],
    'Washington': [-120.7401, 47.7511],
    'West Virginia': [-80.4549, 38.5976],
    'Wisconsin': [-89.6165, 43.7844],
    'Wyoming': [-107.2903, 43.0760],
}


class CoordinateValidator:
    """Validates and transforms geographic coordinates for ECharts"""

    @staticmethod
    def is_valid_coordinate(lon: float, lat: float, region: str = "world") -> bool:
        """
        Validate if coordinates are within acceptable ranges

        Args:
            lon: Longitude value
            lat: Latitude value
            region: Geographic region for bounds checking ("world", "usa", "europe", etc.)

        Returns:
            True if coordinates are valid
        """
        # Basic global validation
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            return False

        # Reject obvious invalid values
        if lon == 0 and lat == 0:
            return False

        # Region-specific validation
        if region.lower() == "usa":
            return -125 <= lon <= -65 and 25 <= lat <= 50
        elif region.lower() == "europe":
            return -25 <= lon <= 40 and 35 <= lat <= 70

        return True

    @staticmethod
    def validate_coordinates(
        coordinates: List[Tuple[float, float]],
        region: str = "world"
    ) -> List[Tuple[float, float]]:
        """
        Filter out invalid coordinates from a list

        Args:
            coordinates: List of (lon, lat) tuples
            region: Geographic region for validation

        Returns:
            List of valid coordinates
        """
        valid = []
        for lon, lat in coordinates:
            if CoordinateValidator.is_valid_coordinate(lon, lat, region):
                valid.append((lon, lat))
            else:
                logger.warning(f"Invalid coordinate filtered: [{lon}, {lat}]")

        return valid

    @staticmethod
    def calculate_center(coordinates: List[Tuple[float, float]]) -> Tuple[float, float]:
        """
        Calculate the center point of a set of coordinates

        Args:
            coordinates: List of (lon, lat) tuples

        Returns:
            Center point as (lon, lat)
        """
        if not coordinates:
            return (0, 0)

        avg_lon = sum(coord[0] for coord in coordinates) / len(coordinates)
        avg_lat = sum(coord[1] for coord in coordinates) / len(coordinates)

        return (avg_lon, avg_lat)

    @staticmethod
    def suggest_zoom(coordinates: List[Tuple[float, float]]) -> float:
        """
        Suggest appropriate zoom level based on coordinate spread

        Args:
            coordinates: List of (lon, lat) tuples

        Returns:
            Suggested zoom level (1-12)
        """
        if not coordinates or len(coordinates) < 2:
            return 5.0

        lons = [coord[0] for coord in coordinates]
        lats = [coord[1] for coord in coordinates]

        lon_range = max(lons) - min(lons)
        lat_range = max(lats) - min(lats)

        max_range = max(lon_range, lat_range)

        # Zoom mapping based on coordinate spread
        if max_range > 100:
            return 2.0
        elif max_range > 50:
            return 3.0
        elif max_range > 20:
            return 4.0
        elif max_range > 10:
            return 5.0
        elif max_range > 5:
            return 6.0
        elif max_range > 2:
            return 7.0
        elif max_range > 1:
            return 8.0
        elif max_range > 0.5:
            return 10.0
        else:
            return 12.0


class EChartsGeoBuilder:
    """Helper class to build ECharts geo configurations programmatically"""

    def __init__(self, map_type: str = "USA"):
        """
        Initialize geo builder

        Args:
            map_type: Base map to use ("USA", "world", or custom)
        """
        self.map_type = map_type
        self.config = {
            "tooltip": {"trigger": "item"},
            "geo": {
                "map": map_type,
                "roam": True,
                "itemStyle": {
                    "areaColor": "#f3f3f3",
                    "borderColor": "#999"
                },
                "emphasis": {
                    "itemStyle": {
                        "areaColor": "#e0e0e0"
                    }
                }
            },
            "series": []
        }

    def set_title(self, text: str, **kwargs) -> 'EChartsGeoBuilder':
        """Set chart title"""
        self.config["title"] = {"text": text, **kwargs}
        return self

    def set_center(self, lon: float, lat: float) -> 'EChartsGeoBuilder':
        """Set map center point"""
        self.config["geo"]["center"] = [lon, lat]
        return self

    def set_zoom(self, zoom: float) -> 'EChartsGeoBuilder':
        """Set map zoom level"""
        self.config["geo"]["zoom"] = zoom
        return self

    def add_scatter_series(
        self,
        data: List[Dict[str, Any]],
        name: str = "Points",
        symbol_size: Union[int, str] = 10,
        color: str = "#c23531",
        **kwargs
    ) -> 'EChartsGeoBuilder':
        """
        Add a scatter plot series to the map

        Args:
            data: List of point data [{"name": str, "value": [lon, lat, size]}]
            name: Series name
            symbol_size: Point size (int or JS function as string)
            color: Point color
            **kwargs: Additional series options
        """
        series = {
            "name": name,
            "type": "scatter",
            "coordinateSystem": "geo",
            "data": data,
            "symbolSize": symbol_size,
            "itemStyle": {"color": color},
            **kwargs
        }
        self.config["series"].append(series)
        return self

    def add_lines_series(
        self,
        data: List[Dict[str, Any]],
        name: str = "Routes",
        line_color: str = "#c23531",
        line_width: int = 2,
        **kwargs
    ) -> 'EChartsGeoBuilder':
        """
        Add a lines series to show connections/routes

        Args:
            data: List of line data [{"coords": [[lon1, lat1], [lon2, lat2]]}]
            name: Series name
            line_color: Line color
            line_width: Line width in pixels
            **kwargs: Additional series options
        """
        series = {
            "name": name,
            "type": "lines",
            "coordinateSystem": "geo",
            "data": data,
            "lineStyle": {
                "color": line_color,
                "width": line_width
            },
            **kwargs
        }
        self.config["series"].append(series)
        return self

    def add_heatmap_series(
        self,
        data: List[List[float]],
        name: str = "Heatmap",
        color_range: Optional[List[str]] = None,
        **kwargs
    ) -> 'EChartsGeoBuilder':
        """
        Add a heatmap series

        Args:
            data: List of points [[lon, lat, value], ...]
            name: Series name
            color_range: Color gradient (default: blue-yellow-red)
            **kwargs: Additional series options
        """
        if color_range is None:
            color_range = ["#50a3ba", "#eac736", "#d94e5d"]

        # Add visual map if not exists
        if "visualMap" not in self.config:
            values = [point[2] for point in data if len(point) >= 3]
            self.config["visualMap"] = {
                "min": min(values) if values else 0,
                "max": max(values) if values else 100,
                "calculable": True,
                "inRange": {"color": color_range}
            }

        series = {
            "name": name,
            "type": "heatmap",
            "coordinateSystem": "geo",
            "data": data,
            **kwargs
        }
        self.config["series"].append(series)
        return self

    def add_choropleth_series(
        self,
        data: List[Dict[str, Any]],
        name: str = "Regions",
        color_range: Optional[List[str]] = None,
        **kwargs
    ) -> 'EChartsGeoBuilder':
        """
        Add a choropleth map series (colored regions)

        Args:
            data: List of region data [{"name": "State/Country", "value": number}]
            name: Series name
            color_range: Color gradient
            **kwargs: Additional series options
        """
        if color_range is None:
            color_range = ["#edf8fb", "#b2e2e2", "#66c2a4", "#2ca25f", "#006d2c"]

        # Add visual map if not exists
        if "visualMap" not in self.config:
            values = [item["value"] for item in data]
            self.config["visualMap"] = {
                "min": min(values) if values else 0,
                "max": max(values) if values else 100,
                "text": ["High", "Low"],
                "calculable": True,
                "inRange": {"color": color_range}
            }

        series = {
            "name": name,
            "type": "map",
            "map": self.map_type,
            "roam": True,
            "data": data,
            **kwargs
        }
        self.config["series"].append(series)
        return self

    def auto_configure_from_data(
        self,
        coordinates: List[Tuple[float, float]],
        region: str = "world"
    ) -> 'EChartsGeoBuilder':
        """
        Automatically configure map center and zoom based on data

        Args:
            coordinates: List of (lon, lat) tuples
            region: Geographic region for validation

        Returns:
            Self for chaining
        """
        # Validate coordinates
        valid_coords = CoordinateValidator.validate_coordinates(coordinates, region)

        if not valid_coords:
            logger.warning("No valid coordinates found for auto-configuration")
            return self

        # Calculate center
        center_lon, center_lat = CoordinateValidator.calculate_center(valid_coords)
        self.set_center(center_lon, center_lat)

        # Suggest zoom
        zoom = CoordinateValidator.suggest_zoom(valid_coords)
        self.set_zoom(zoom)

        return self

    def build(self) -> Dict[str, Any]:
        """Build and return the complete configuration"""
        return self.config

    def to_json(self, indent: int = 2) -> str:
        """Export configuration as JSON string"""
        return json.dumps(self.config, indent=indent)


class EChartsMapsMixin:
    """
    Mixin class to add geo/map capabilities to EChartsRenderer

    This mixin adds methods for creating and validating geographic visualizations
    to the existing EChartsRenderer without breaking existing functionality.

    Usage in echarts.py:
        from ._echarts_geo_ext import EChartsMapsMixin

        @register_renderer(OutputMode.ECHARTS, system_prompt=ECHARTS_SYSTEM_PROMPT)
        class EChartsRenderer(EChartsMapsMixin, BaseChart):
            # ... existing methods ...
    """

    def create_geo_builder(self, map_type: str = "USA") -> EChartsGeoBuilder:
        """
        Factory method to create a geo builder

        Args:
            map_type: Base map type ("USA", "world", etc.)

        Returns:
            EChartsGeoBuilder instance
        """
        return EChartsGeoBuilder(map_type)

    def validate_geo_config(self, config: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate a geo configuration

        Args:
            config: ECharts configuration dict

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(config, dict):
            return False, "Configuration must be a dictionary"

        # Check if it's a geo chart
        has_geo = "geo" in config
        has_geo_series = any(
            s.get("coordinateSystem") == "geo" or s.get("type") == "map"
            for s in config.get("series", [])
        )

        if not (has_geo or has_geo_series):
            return True, None  # Not a geo chart, no validation needed

        # Validate geo component if present
        if has_geo:
            geo = config["geo"]
            if "map" not in geo:
                return False, "Geo component must specify a 'map'"

        # Validate series with geo coordinate system
        for idx, series in enumerate(config.get("series", [])):
            if series.get("coordinateSystem") == "geo":
                data = series.get("data", [])

                # Check coordinate format
                for point_idx, point in enumerate(data):
                    if isinstance(point, dict) and "value" in point:
                        value = point["value"]
                        if isinstance(value, list) and len(value) >= 2:
                            lon, lat = value[0], value[1]
                            if not CoordinateValidator.is_valid_coordinate(lon, lat):
                                logger.warning(
                                    f"Potentially invalid coordinate in series {idx}, "
                                    f"point {point_idx}: [{lon}, {lat}]"
                                )
                    elif isinstance(point, list) and len(point) >= 2:
                        lon, lat = point[0], point[1]
                        if not CoordinateValidator.is_valid_coordinate(lon, lat):
                            logger.warning(
                                f"Potentially invalid coordinate in series {idx}, "
                                f"point {point_idx}: [{lon}, {lat}]"
                            )

        return True, None

    def render_geo_map(
        self,
        map_type: str = "USA",
        title: Optional[str] = None,
        scatter_data: Optional[list] = None,
        choropleth_data: Optional[list] = None,
        auto_center: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Convenience method to quickly create a geo map

        Args:
            map_type: Base map ("USA", "world")
            title: Map title
            scatter_data: Point data for scatter plot
            choropleth_data: Region data for choropleth
            auto_center: Auto-calculate center and zoom
            **kwargs: Additional options

        Returns:
            ECharts configuration dict
        """
        builder = self.create_geo_builder(map_type)

        if title:
            builder.set_title(title)

        # Add scatter layer if provided
        if scatter_data:
            # Extract coordinates for auto-centering
            if auto_center:
                coords = []
                for point in scatter_data:
                    if isinstance(point, dict) and "value" in point:
                        value = point["value"]
                        if isinstance(value, list) and len(value) >= 2:
                            coords.append((value[0], value[1]))

                if coords:
                    builder.auto_configure_from_data(coords, map_type.lower())

            builder.add_scatter_series(
                scatter_data,
                name=kwargs.get('scatter_name', 'Locations'),
                symbol_size=kwargs.get('symbol_size', 10),
                color=kwargs.get('scatter_color', '#c23531')
            )

        # Add choropleth layer if provided
        if choropleth_data:
            builder.add_choropleth_series(
                choropleth_data,
                name=kwargs.get('choropleth_name', 'Regions'),
                color_range=kwargs.get('color_range')
            )

        return builder.build()

    def _render_chart_content_geo(
        self,
        config: Dict[str, Any],
        chart_id: str,
        width: str = '100%',
        height: str = '500px'
    ) -> str:
        """
        Enhanced chart rendering that adds USA map loading if needed

        This can be called from _render_chart_content to add geo support.

        Args:
            config: ECharts configuration
            chart_id: Unique chart ID
            width: Chart width
            height: Chart height

        Returns:
            HTML/JS string with map loading support
        """
        # Convert to JSON
        config_json = json.dumps(config, indent=2)

        # Check if this is a geo chart that needs map data
        needs_usa_map = (
            'geo' in config and config['geo'].get('map') == 'USA'
        ) or any(
            s.get('type') == 'map' and s.get('map') == 'USA'
            for s in config.get('series', [])
        )

        # Load USA map data if needed
        map_script = ""
        if needs_usa_map:
            map_script = """
            <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/map/js/usa.js"></script>
            """

        return f'''
        {map_script}
        <div id="{chart_id}" style="width: {width}; height: {height};"></div>
        <script type="text/javascript">
            (function() {{
                var chartDom = document.getElementById('{chart_id}');
                if (!chartDom) {{
                    console.error('Chart container not found: {chart_id}');
                    return;
                }}

                // Check if ECharts is loaded
                if (typeof echarts === 'undefined') {{
                    console.error('ECharts library not loaded');
                    chartDom.innerHTML = '<div style="color: red; padding: 20px;">ECharts library not loaded</div>';
                    return;
                }}

                var myChart = echarts.init(chartDom);
                var option = {config_json};

                // Set option with error handling
                try {{
                    myChart.setOption(option);
                    console.log('ECharts {chart_id} rendered successfully');
                }} catch (error) {{
                    console.error('Error setting ECharts option:', error);
                    chartDom.innerHTML = '<div style="color: red; padding: 20px;">Error rendering chart: ' + error.message + '</div>';
                    return;
                }}

                // Resize handler
                window.addEventListener('resize', function() {{
                    myChart.resize();
                }});

                // Cleanup on page unload
                window.addEventListener('beforeunload', function() {{
                    myChart.dispose();
                }});
            }})();
        </script>
        '''


# Convenience function to get complete system prompt
def get_echarts_system_prompt_with_geo(base_prompt: str) -> str:
    """
    Combine base ECharts prompt with geo extension

    Args:
        base_prompt: Original ECHARTS_SYSTEM_PROMPT

    Returns:
        Combined prompt with geo support
    """
    return f"""{base_prompt}

{ECHARTS_GEO_EXTENSION}

**IMPORTANT NOTES FOR GEO:**
- For maps, ALWAYS use [longitude, latitude] order (opposite of Leaflet)
- Validate coordinates before using them
- Filter out invalid (0, 0) coordinates
- Center maps on the average of valid data points
- Use appropriate zoom levels (5-8 for regions, 8-12 for cities)
"""

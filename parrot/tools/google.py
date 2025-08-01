"""
Migrated Google Tools using the AbstractTool framework.
"""
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import urllib.parse
import string
import aiohttp
from pydantic import BaseModel, Field, field_validator
from googleapiclient.discovery import build
from navconfig import config
from ..conf import GOOGLE_API_KEY
from .abstract import AbstractTool


# Schema definitions
class GoogleSearchArgs(BaseModel):
    """Arguments schema for Google Search Tool."""
    query: str = Field(description="Search query")
    max_results: int = Field(default=5, ge=1, le=50, description="Maximum number of results to return")
    preview: bool = Field(default=False, description="If True, fetch full page content for each result")
    preview_method: str = Field(default="aiohttp", description="Method to use for preview: 'aiohttp' or 'selenium'")


class GoogleSiteSearchArgs(BaseModel):
    """Arguments schema for Google Site Search Tool."""
    query: str = Field(description="Search query")
    site: str = Field(description="Site to search within (e.g., 'example.com')")
    max_results: int = Field(default=5, ge=1, le=50, description="Maximum number of results to return")
    preview: bool = Field(default=False, description="If True, fetch full page content for each result")
    preview_method: str = Field(default="aiohttp", description="Method to use for preview: 'aiohttp' or 'selenium'")


class GoogleLocationArgs(BaseModel):
    """Arguments schema for Google Location Finder."""
    address: str = Field(description="Complete address to geocode")


class GoogleRouteArgs(BaseModel):
    """Arguments schema for Google Route Search."""
    origin: str = Field(description="Origin address or coordinates")
    destination: str = Field(description="Destination address or coordinates")
    waypoints: Optional[List[str]] = Field(default=None, description="Optional waypoints between origin and destination")
    travel_mode: str = Field(default="DRIVE", description="Travel mode: DRIVE, WALK, BICYCLE, TRANSIT")
    routing_preference: str = Field(default="TRAFFIC_AWARE", description="Routing preference")
    optimize_waypoints: bool = Field(default=False, description="Whether to optimize waypoint order")
    departure_time: Optional[str] = Field(default=None, description="Departure time in ISO format")
    include_static_map: bool = Field(default=False, description="Whether to include a static map URL")
    include_interactive_map: bool = Field(default=False, description="Whether to generate an interactive HTML map")
    map_size: str = Field(
        default="640x640",
        description="Map size for static map in format 'widthxheight' (e.g., '640x640')"
    )
    map_scale: int = Field(default=2, description="Map scale factor")
    map_type: str = Field(default="roadmap", description="Map type: roadmap, satellite, terrain, hybrid")
    auto_zoom: bool = Field(default=True, description="Automatically calculate zoom based on route distance")
    zoom: int = Field(default=8, description="Manual zoom level (used when auto_zoom=False)")

    @field_validator('map_size')
    @classmethod
    def validate_map_size(cls, v):
        """Validate map_size format."""
        if not isinstance(v, str):
            raise ValueError('map_size must be a string')

        try:
            parts = v.split('x')
            if len(parts) != 2:
                raise ValueError('map_size must be in format "widthxheight"')

            width, height = int(parts[0]), int(parts[1])
            if width <= 0 or height <= 0:
                raise ValueError('map_size dimensions must be positive')

            return v
        except ValueError as e:
            raise ValueError(f'Invalid map_size format: {e}')

    @property
    def map_width(self) -> int:
        """Get map width from map_size string."""
        return int(self.map_size.split('x')[0])

    @property
    def map_height(self) -> int:
        """Get map height from map_size string."""
        return int(self.map_size.split('x')[1])

    def get_map_size_tuple(self) -> tuple:
        """Get map_size as tuple."""
        return (self.map_width, self.map_height)

    def get_map_size_list(self) -> List[int]:
        """Get map_size as list."""
        return [self.map_width, self.map_height]

# Google Search Tool
class GoogleSearchTool(AbstractTool):
    """Enhanced Google Search tool with content preview capabilities."""

    name = "google_search"
    description = "Search the web using Google Custom Search API with optional content preview"
    args_schema = GoogleSearchArgs

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cse_id = config.get('GOOGLE_SEARCH_ENGINE_ID')
        self.search_key = config.get('GOOGLE_SEARCH_API_KEY')

    async def _fetch_page_content(self, url: str, method: str = "aiohttp") -> str:
        """Fetch full page content using specified method."""
        if method == "aiohttp":
            return await self._fetch_with_aiohttp(url)
        elif method == "selenium":
            return await self._fetch_with_selenium(url)
        else:
            raise ValueError(f"Unknown preview method: {method}")

    async def _fetch_with_aiohttp(self, url: str) -> str:
        """Fetch page content using aiohttp."""
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        content = await response.text()
                        # Basic HTML content extraction (you might want to use BeautifulSoup here)
                        return content[:5000]  # Limit content size
                    else:
                        return f"Error: HTTP {response.status}"
        except Exception as e:
            return f"Error fetching content: {str(e)}"

    async def _fetch_with_selenium(self, url: str) -> str:
        """Fetch page content using Selenium (placeholder implementation)."""
        # Note: This would require selenium and a webdriver
        # Implementation would depend on your selenium setup
        return "Selenium implementation not yet available"

    async def _execute(self, **kwargs) -> Dict[str, Any]:
        """Execute Google search with optional content preview."""
        query = kwargs['query']
        max_results = kwargs['max_results']
        preview = kwargs['preview']
        preview_method = kwargs['preview_method']

        # Build search service
        service = build("customsearch", "v1", developerKey=self.search_key)

        # Execute search
        res = service.cse().list(  # pylint: disable=E1101  # noqa
            q=query,
            cx=self.cse_id,
            num=max_results
        ).execute()

        results = []
        for item in res.get('items', []):
            result_item = {
                'title': item['title'],
                'link': item['link'],
                'snippet': item['snippet'],
                'description': item['snippet']
            }

            # Add full content if preview is requested
            if preview:
                self.logger.info(f"Fetching preview for: {item['link']}")
                content = await self._fetch_page_content(item['link'], preview_method)
                result_item['full_content'] = content

            results.append(result_item)

        return {
            'query': query,
            'total_results': len(results),
            'results': results
        }


# Google Site Search Tool
class GoogleSiteSearchTool(GoogleSearchTool):
    """Google Site Search tool - extends GoogleSearchTool with site restriction."""

    name = "google_site_search"
    description = "Search within a specific site using Google Custom Search API"
    args_schema = GoogleSiteSearchArgs

    async def _execute(self, **kwargs) -> Dict[str, Any]:
        """Execute site-specific Google search."""
        query = kwargs['query']
        site = kwargs['site']
        # Modify query to include site restriction
        site_query = f"{query} site:{site}"

        # Use parent class execution with modified query
        modified_kwargs = kwargs.copy()
        modified_kwargs['query'] = site_query

        result = await super()._execute(**modified_kwargs)
        result['original_query'] = query
        result['site'] = site
        result['search_query'] = site_query

        return result


# Google Location Finder Tool
class GoogleLocationTool(AbstractTool):
    """Google Geocoding tool for location information."""

    name = "google_location_finder"
    description = "Find location information using Google Geocoding API"
    args_schema = GoogleLocationArgs

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.google_key = kwargs.get('api_key', GOOGLE_API_KEY)
        self.base_url = "https://maps.googleapis.com/maps/api/geocode/json"

    def _extract_location_components(self, data: Dict) -> Dict[str, Optional[str]]:
        """Extract location components from geocoding response."""
        city = state = state_code = zipcode = country = country_code = None

        try:
            for component in data.get('address_components', []):
                types = component.get('types', [])

                if 'locality' in types:
                    city = component['long_name']
                elif 'administrative_area_level_1' in types:
                    state_code = component['short_name']
                    state = component['long_name']
                elif 'postal_code' in types:
                    zipcode = component['long_name']
                elif 'country' in types:
                    country = component['long_name']
                    country_code = component['short_name']
        except Exception as e:
            self.logger.error(f"Error extracting location components: {e}")

        return {
            'city': city,
            'state': state,
            'state_code': state_code,
            'zipcode': zipcode,
            'country': country,
            'country_code': country_code
        }

    async def _execute(self, **kwargs) -> Dict[str, Any]:
        """Execute geocoding request."""
        address = kwargs['address']

        params = {
            "address": address,
            "key": self.google_key
        }

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(self.base_url, params=params) as response:
                if response.status != 200:
                    raise Exception(f"HTTP {response.status}: {await response.text()}")

                result = await response.json()

                if result['status'] != 'OK':
                    return {
                        'status': result['status'],
                        'error': result.get('error_message', 'Unknown error'),
                        'results': []
                    }

                # Process results into tabular format
                processed_results = []
                for location in result['results']:
                    components = self._extract_location_components(location)
                    geometry = location.get('geometry', {})
                    location_data = geometry.get('location', {})

                    processed_result = {
                        'formatted_address': location.get('formatted_address'),
                        'latitude': location_data.get('lat'),
                        'longitude': location_data.get('lng'),
                        'place_id': location.get('place_id'),
                        'location_type': geometry.get('location_type'),
                        'city': components['city'],
                        'state': components['state'],
                        'state_code': components['state_code'],
                        'zipcode': components['zipcode'],
                        'country': components['country'],
                        'country_code': components['country_code'],
                        'types': location.get('types', [])
                    }

                    # Add viewport if available
                    if 'viewport' in geometry:
                        viewport = geometry['viewport']
                        processed_result.update({
                            'viewport_northeast_lat': viewport.get('northeast', {}).get('lat'),
                            'viewport_northeast_lng': viewport.get('northeast', {}).get('lng'),
                            'viewport_southwest_lat': viewport.get('southwest', {}).get('lat'),
                            'viewport_southwest_lng': viewport.get('southwest', {}).get('lng')
                        })

                    processed_results.append(processed_result)

                return {
                    'status': result['status'],
                    'query': address,
                    'results_count': len(processed_results),
                    'results': processed_results,
                    'raw_response': result  # Include original response for reference
                }


class GoogleRoutesTool(AbstractTool):
    """Google Routes tool using the new Routes API v2."""

    name = "google_routes"
    description = "Find routes using Google Routes API v2 with waypoint optimization"
    args_schema = GoogleRouteArgs

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.google_key = kwargs.get('api_key', GOOGLE_API_KEY)
        self.base_url = "https://routes.googleapis.com/directions/v2:computeRoutes"

    def _default_output_dir(self) -> Optional[Path]:
        """Get the default output directory for this tool type."""
        return self.static_dir / "route_maps" if self.static_dir else None

    def _create_location_object(self, location: str) -> Dict[str, Any]:
        """Create location object for Routes API."""
        try:
            if ',' in location:
                parts = location.strip().split(',')
                if len(parts) == 2:
                    lat, lng = map(float, parts)
                    return {
                        "location": {
                            "latLng": {
                                "latitude": lat,
                                "longitude": lng
                            }
                        }
                    }
        except ValueError:
            pass

        return {"address": location}

    def _calculate_optimal_zoom(self, distance_miles: float, viewport: Dict = None) -> int:
        """Calculate optimal zoom level based on route distance."""
        if viewport:
            ne_lat = viewport.get('northeast', {}).get('lat', 0)
            ne_lng = viewport.get('northeast', {}).get('lng', 0)
            sw_lat = viewport.get('southwest', {}).get('lat', 0)
            sw_lng = viewport.get('southwest', {}).get('lng', 0)

            lat_span = abs(ne_lat - sw_lat)
            lng_span = abs(ne_lng - sw_lng)
            max_span = max(lat_span, lng_span)

            if max_span >= 10: return 6
            elif max_span >= 5: return 7
            elif max_span >= 2: return 8
            elif max_span >= 1: return 9
            elif max_span >= 0.5: return 10
            elif max_span >= 0.25: return 11
            elif max_span >= 0.1: return 12
            elif max_span >= 0.05: return 13
            else: return 14

        if distance_miles >= 500: return 6
        elif distance_miles >= 200: return 7
        elif distance_miles >= 100: return 8
        elif distance_miles >= 50: return 9
        elif distance_miles >= 25: return 10
        elif distance_miles >= 10: return 11
        elif distance_miles >= 5: return 12
        elif distance_miles >= 2: return 13
        else: return 14

    def _get_gradient_colors(self, num_colors: int, start_color: str = "0x0000FF", end_color: str = "0xFF0000") -> List[str]:
        """Generate gradient colors for waypoint markers."""
        if num_colors <= 1:
            return [start_color]

        start_rgb = tuple(int(start_color[2:][i:i+2], 16) for i in (0, 2, 4))
        end_rgb = tuple(int(end_color[2:][i:i+2], 16) for i in (0, 2, 4))

        colors = []
        for i in range(num_colors):
            ratio = i / (num_colors - 1)
            r = int(start_rgb[0] + ratio * (end_rgb[0] - start_rgb[0]))
            g = int(start_rgb[1] + ratio * (end_rgb[1] - start_rgb[1]))
            b = int(start_rgb[2] + ratio * (end_rgb[2] - start_rgb[2]))
            colors.append(f"0x{r:02x}{g:02x}{b:02x}")

        return colors

    async def _extract_coordinates_from_location(self, location: str) -> Tuple[float, float]:
        """Extract coordinates from location string or geocode address."""
        try:
            if ',' in location:
                parts = location.strip().split(',')
                if len(parts) == 2:
                    lat, lng = map(float, parts)
                    return (lat, lng)
        except ValueError:
            pass

        try:
            geocoder = GoogleLocationTool(api_key=self.google_key)
            result = await geocoder.execute(address=location)
            if result.status == "success" and result.result['results']:
                first_result = result.result['results'][0]
                lat = first_result['latitude']
                lng = first_result['longitude']
                if lat is not None and lng is not None:
                    return (lat, lng)
        except Exception as e:
            self.logger.warning(f"Failed to geocode {location}: {e}")

        return (0.0, 0.0)

    async def _generate_static_map_url(self, route_data: Dict, coordinates_cache: Dict, args: Dict) -> str:
        """Generate Google Static Maps URL for the route."""
        base_url = "https://maps.googleapis.com/maps/api/staticmap"

        route = route_data['routes'][0]
        encoded_polyline = route.get('polyline', {}).get('encodedPolyline', '')

        origin_coords = coordinates_cache['origin']
        dest_coords = coordinates_cache['destination']
        waypoint_coords_list = coordinates_cache['waypoints']

        markers = []
        markers.append(f"markers=color:green|label:O|{origin_coords[0]},{origin_coords[1]}")
        markers.append(f"markers=color:red|label:D|{dest_coords[0]},{dest_coords[1]}")

        if waypoint_coords_list:
            colors = self._get_gradient_colors(len(waypoint_coords_list))
            alpha_labels = string.ascii_uppercase

            for i, coords in enumerate(waypoint_coords_list):
                if i < len(colors) and i < len(alpha_labels):
                    color = colors[i].replace('0x', '')
                    label = alpha_labels[i]
                    markers.append(f"markers=color:0x{color}|size:mid|label:{label}|{coords[0]},{coords[1]}")

        map_size = args['map_size']

        if args.get('auto_zoom', True):
            viewport = route.get('viewport')
            distance_miles = args.get('total_distance_miles', 0)
            zoom_level = self._calculate_optimal_zoom(distance_miles, viewport)
            self.logger.info(f"Auto-calculated zoom level: {zoom_level} for distance: {distance_miles} miles")
        else:
            zoom_level = args['zoom']

        params = {
            "size": f"{map_size}",
            "scale": args['map_scale'],
            "maptype": args['map_type'],
            "zoom": zoom_level,
            "language": "en",
            "key": self.google_key
        }

        if encoded_polyline:
            params["path"] = f"enc:{encoded_polyline}"

        query_string = urllib.parse.urlencode(params)
        markers_string = '&'.join(markers)

        return f"{base_url}?{query_string}&{markers_string}"

    def _generate_interactive_html_map(self, route_data: Dict, coordinates_cache: Dict, args: Dict) -> str:
        """Generate an interactive HTML map using Google Maps JavaScript API."""
        route = route_data['routes'][0]
        encoded_polyline = route.get('polyline', {}).get('encodedPolyline', '')

        self.logger.info(f"Generating interactive map with polyline length: {len(encoded_polyline)} chars")
        self.logger.info(f"Polyline sample: {encoded_polyline[:100]}...")

        origin_coords = coordinates_cache['origin']
        dest_coords = coordinates_cache['destination']
        waypoint_coords = coordinates_cache['waypoints']

        self.logger.info(f"Origin coords: {origin_coords}, Dest coords: {dest_coords}, Waypoints: {waypoint_coords}")

        valid_coords = [coord for coord in [origin_coords, dest_coords] + waypoint_coords if coord != (0.0, 0.0)]

        if valid_coords:
            all_lats = [coord[0] for coord in valid_coords]
            all_lngs = [coord[1] for coord in valid_coords]
            center_lat = sum(all_lats) / len(all_lats)
            center_lng = sum(all_lngs) / len(all_lngs)
        else:
            center_lat, center_lng = 37.7749, -122.4194

        viewport = route.get('viewport', {})
        distance_miles = args.get('total_distance_miles', 0)
        zoom_level = self._calculate_optimal_zoom(distance_miles, viewport)

        waypoint_markers_js = ""
        if waypoint_coords:
            alpha_labels = string.ascii_uppercase
            for i, (lat, lng) in enumerate(waypoint_coords):
                if i < len(alpha_labels):
                    label = alpha_labels[i]
                    waypoint_markers_js += f"""
                    new google.maps.Marker({{
                        position: {{lat: {lat}, lng: {lng}}},
                        map: map,
                        title: 'Waypoint {label}',
                        label: '{label}',
                        icon: {{
                            url: 'https://maps.google.com/mapfiles/ms/icons/blue-dot.png'
                        }}
                    }});
                    """

        polyline_js = ""
        if encoded_polyline and len(encoded_polyline) > 10:

            # FIX: Escape backslashes for the JavaScript string literal.
            js_safe_polyline = encoded_polyline.replace('\\', '\\\\')

            polyline_js = f"""
            try {{
                console.log('Decoding polyline: {js_safe_polyline[:50]}...');
                const decodedPath = google.maps.geometry.encoding.decodePath('{js_safe_polyline}');
                console.log('Decoded path points:', decodedPath.length);
                console.log('First few points:', decodedPath.slice(0, 3));

                const routePath = new google.maps.Polyline({{
                    path: decodedPath,
                    geodesic: false,
                    strokeColor: '#4285F4',
                    strokeOpacity: 0.8,
                    strokeWeight: 6
                }});

                routePath.setMap(map);

                const bounds = new google.maps.LatLngBounds();
                decodedPath.forEach(function(point) {{
                    bounds.extend(point);
                }});
                map.fitBounds(bounds);

                console.log('Route polyline added successfully');
            }} catch (error) {{
                console.error('Error decoding polyline:', error);
                console.log('Falling back to marker bounds');
                const bounds = new google.maps.LatLngBounds();
                bounds.extend({{lat: {origin_coords[0]}, lng: {origin_coords[1]}}});
                bounds.extend({{lat: {dest_coords[0]}, lng: {dest_coords[1]}}});"""

            for lat, lng in waypoint_coords:
                polyline_js += f"""
                bounds.extend({{lat: {lat}, lng: {lng}}});"""

            polyline_js += """
                map.fitBounds(bounds);
            }
            """
        else:
            self.logger.warning(f"No valid polyline found, using marker bounds only")
            polyline_js = f"""
            console.log('No valid polyline, fitting to markers');
            const bounds = new google.maps.LatLngBounds();
            bounds.extend({{lat: {origin_coords[0]}, lng: {origin_coords[1]}}});
            bounds.extend({{lat: {dest_coords[0]}, lng: {dest_coords[1]}}});"""

            for lat, lng in waypoint_coords:
                polyline_js += f"""
            bounds.extend({{lat: {lat}, lng: {lng}}});"""

            polyline_js += """
            map.fitBounds(bounds);
            """

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Route Map</title>
            <style>
                #map {{ height: 600px; width: 100%; }}
                .info-panel {{ padding: 20px; background: #f5f5f5; margin: 10px; border-radius: 8px; font-family: Arial, sans-serif; }}
                .route-info {{ display: flex; gap: 20px; flex-wrap: wrap; }}
                .info-item {{ background: white; padding: 10px; border-radius: 4px; }}
            </style>
        </head>
        <body>
            <div class="info-panel">
                <h2>Route Information</h2>
                <div class="route-info">
                    <div class="info-item">
                        <strong>Distance:</strong> {args.get('total_distance_formatted', 'N/A')}
                    </div>
                    <div class="info-item">
                        <strong>Duration:</strong> {args.get('total_duration_formatted', 'N/A')}
                    </div>
                    <div class="info-item">
                        <strong>Travel Mode:</strong> {args.get('travel_mode', 'N/A')}
                    </div>
                </div>
            </div>
            <div id="map"></div>
            <script>
                function initMap() {{
                    const map = new google.maps.Map(document.getElementById("map"), {{
                        zoom: {zoom_level},
                        center: {{lat: {center_lat}, lng: {center_lng}}},
                        mapTypeId: '{args.get('map_type', 'roadmap')}'
                    }});
                    new google.maps.Marker({{
                        position: {{lat: {origin_coords[0]}, lng: {origin_coords[1]}}},
                        map: map,
                        title: 'Origin',
                        label: 'O',
                        icon: {{ url: 'https://maps.google.com/mapfiles/ms/icons/green-dot.png' }}
                    }});
                    new google.maps.Marker({{
                        position: {{lat: {dest_coords[0]}, lng: {dest_coords[1]}}},
                        map: map,
                        title: 'Destination',
                        label: 'D',
                        icon: {{ url: 'https://maps.google.com/mapfiles/ms/icons/red-dot.png' }}
                    }});
                    {waypoint_markers_js}
                    {polyline_js}
                }}
                window.initMap = initMap;
            </script>
            <script async defer
                src="https://maps.googleapis.com/maps/api/js?key={self.google_key}&libraries=geometry&callback=initMap">
            </script>
        </body>
        </html>
        """

        return html_content

    async def _execute(self, **kwargs) -> Dict[str, Any]:
        """Execute route calculation using Google Routes API v2."""
        origin = kwargs['origin']
        destination = kwargs['destination']
        waypoints = kwargs.get('waypoints', [])
        travel_mode = kwargs['travel_mode']
        routing_preference = kwargs['routing_preference']
        optimize_waypoints = kwargs['optimize_waypoints']
        departure_time = kwargs.get('departure_time')
        include_static_map = kwargs['include_static_map']
        include_interactive_map = kwargs['include_interactive_map']

        # Build request data
        data = {
            "origin": self._create_location_object(origin),
            "destination": self._create_location_object(destination),
            "travelMode": travel_mode,
            "routingPreference": routing_preference,
            "computeAlternativeRoutes": False,
            "optimizeWaypointOrder": optimize_waypoints,
            "routeModifiers": {
                "avoidTolls": False,
                "avoidHighways": False,
                "avoidFerries": False
            },
            "languageCode": "en-US",
            "units": "IMPERIAL"
        }

        if waypoints:
            data['intermediates'] = [self._create_location_object(wp) for wp in waypoints]

        if departure_time:
            data['departureTime'] = departure_time

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.google_key,
            "X-Goog-FieldMask": "routes.legs,routes.duration,routes.staticDuration,routes.distanceMeters,routes.polyline,routes.optimizedIntermediateWaypointIndex,routes.description,routes.warnings,routes.viewport,routes.travelAdvisory,routes.localizedValues"
        }

        # Make API request
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self.base_url, json=data, headers=headers) as response:
                if response.status != 200:
                    error_data = await response.json()
                    raise Exception(f"Routes API error: {error_data}")

                result = await response.json()

                if not result or 'routes' not in result or not result['routes']:
                    raise Exception("No routes found in API response")

        # Process route data
        route = result['routes'][0]

        total_duration_seconds = 0
        static_duration_seconds = 0
        total_distance_meters = 0
        route_instructions = []

        for i, leg in enumerate(route['legs']):
            duration_str = leg.get('duration', '0s')
            leg_duration = int(duration_str.rstrip('s')) if duration_str else 0
            total_duration_seconds += leg_duration

            static_duration_str = leg.get('staticDuration', '0s')
            static_duration_seconds += int(static_duration_str.rstrip('s'))

            distance_meters = leg.get('distanceMeters', 0)
            total_distance_meters += distance_meters

            distance_miles = distance_meters / 1609.34
            route_instructions.append(f"Leg {i+1}: Continue for {distance_miles:.1f} miles")

        total_duration_minutes = total_duration_seconds / 60
        static_duration_minutes = static_duration_seconds / 60
        total_distance_miles = total_distance_meters / 1609.34

        waypoint_order = route.get('optimizedIntermediateWaypointIndex', [])

        # Extract coordinates once for map generation
        self.logger.info("Extracting coordinates for map generation...")
        coordinates_cache = {
            'origin': await self._extract_coordinates_from_location(origin),
            'destination': await self._extract_coordinates_from_location(destination),
            'waypoints': []
        }

        if waypoints:
            for waypoint in waypoints:
                wp_coords = await self._extract_coordinates_from_location(waypoint)
                coordinates_cache['waypoints'].append(wp_coords)

        self.logger.info(f"Cached coordinates - Origin: {coordinates_cache['origin']}, Dest: {coordinates_cache['destination']}, Waypoints: {coordinates_cache['waypoints']}")

        # Build response
        response_data = {
            'origin': origin,
            'destination': destination,
            'waypoints': waypoints,
            'optimized_waypoint_order': waypoint_order,
            'route_instructions': route_instructions,
            'total_duration_minutes': total_duration_minutes,
            'static_duration_minutes': static_duration_minutes,
            'total_distance_miles': total_distance_miles,
            'total_duration_formatted': f"{total_duration_minutes:.2f} minutes",
            'total_distance_formatted': f"{total_distance_miles:.2f} miles",
            'encoded_polyline': route.get('polyline', {}).get('encodedPolyline'),
            'raw_response': result
        }

        # Prepare args for map generation
        map_args = kwargs.copy()
        map_args['total_distance_miles'] = total_distance_miles
        map_args['total_duration_formatted'] = response_data['total_duration_formatted']
        map_args['total_distance_formatted'] = response_data['total_distance_formatted']

        # Generate static map if requested
        if include_static_map:
            response_data['static_map_url'] = await self._generate_static_map_url(result, coordinates_cache, map_args)

        # Generate interactive map if requested
        if include_interactive_map:
            html_map = self._generate_interactive_html_map(result, coordinates_cache, map_args)

            if self.output_dir:
                filename = self.generate_filename("route_map", "html", include_timestamp=True)
                html_file_path = self.output_dir / filename

                with open(html_file_path, 'w', encoding='utf-8') as f:
                    f.write(html_map)

                response_data['interactive_map_file'] = str(html_file_path)
                response_data['interactive_map_url'] = self.to_static_url(html_file_path)

            response_data['interactive_map_html'] = html_map

            # Also include static map URL when interactive map is requested
            if not include_static_map:
                response_data['static_map_url'] = await self._generate_static_map_url(result, coordinates_cache, map_args)

        return response_data


# Export all tools
__all__ = [
    'GoogleSearchTool',
    'GoogleSiteSearchTool',
    'GoogleLocationTool',
    'GoogleRoutesTool'
]

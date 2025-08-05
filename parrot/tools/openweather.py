"""
OpenWeather Tool migrated to use AbstractTool framework with aiohttp.
"""
import os
from typing import Dict, Any, Optional, Literal
from pathlib import Path
import json
import asyncio
import aiohttp
from pydantic import BaseModel, Field, field_validator
from .abstract import AbstractTool, ToolResult


class OpenWeatherArgs(BaseModel):
    """Arguments schema for OpenWeatherTool."""

    latitude: float = Field(
        ...,
        description="The latitude of the location you want weather information about",
        ge=-90.0,
        le=90.0
    )
    longitude: float = Field(
        ...,
        description="The longitude of the location you want weather information about",
        ge=-180.0,
        le=180.0
    )
    request_type: Literal['weather', 'forecast'] = Field(
        'weather',
        description="Type of weather information: 'weather' for current conditions, 'forecast' for future predictions"
    )
    units: Literal['metric', 'imperial', 'standard'] = Field(
        'imperial',
        description="Temperature units: 'metric' (Celsius), 'imperial' (Fahrenheit), 'standard' (Kelvin)"
    )
    country: str = Field(
        'us',
        description="Country code for the location (ISO 3166 country codes)"
    )
    forecast_days: int = Field(
        3,
        description="Number of days for forecast (only used when request_type='forecast')",
        ge=1,
        le=16
    )

    @field_validator('country')
    @classmethod
    def validate_country(cls, v):
        if len(v) != 2:
            raise ValueError("Country code must be exactly 2 characters (ISO 3166)")
        return v.lower()


class OpenWeatherTool(AbstractTool):
    """
    Tool to get weather information for specific locations using OpenWeatherMap API.

    This tool provides current weather conditions and weather forecasts for any location
    specified by latitude and longitude coordinates. It supports different temperature
    units and can be configured for different countries.

    Features:
    - Current weather conditions
    - Weather forecasts (up to 16 days)
    - Multiple temperature units (Celsius, Fahrenheit, Kelvin)
    - Country-specific formatting
    - Comprehensive weather data including temperature, humidity, pressure, wind, etc.
    """

    name = "openweather_tool"
    description = (
        "Get current weather information or forecast for specific coordinates. "
        "Supports current weather and forecasts with configurable units and country settings. "
        "Requires latitude and longitude coordinates."
    )
    args_schema = OpenWeatherArgs

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_units: str = 'imperial',
        default_country: str = 'us',
        default_request_type: str = 'weather',
        timeout: int = 10,
        **kwargs
    ):
        """
        Initialize the OpenWeather tool.

        Args:
            api_key: OpenWeatherMap API key (if None, reads from OPENWEATHER_APPID env var)
            default_units: Default temperature units ('metric', 'imperial', 'standard')
            default_country: Default country code
            default_request_type: Default request type ('weather' or 'forecast')
            timeout: Request timeout in seconds
            **kwargs: Additional arguments for AbstractTool
        """
        super().__init__(**kwargs)

        # API configuration
        self.api_key = api_key or os.getenv('OPENWEATHER_APPID')
        if not self.api_key:
            raise ValueError(
                "OpenWeather API key must be provided or set in OPENWEATHER_APPID environment variable"
            )

        # Default settings
        self.default_units = default_units
        self.default_country = default_country
        self.default_request_type = default_request_type
        self.timeout = timeout

        # API endpoints
        self.base_url = "https://api.openweathermap.org/data/2.5"

        self.logger.info(
            f"OpenWeather tool initialized with defaults: units={default_units}, country={default_country}"
        )

    def _default_output_dir(self) -> Optional[Path]:
        """Get the default output directory for weather data."""
        return self.static_dir / "weather_data" if self.static_dir else None

    def _build_url(
        self,
        latitude: float,
        longitude: float,
        request_type: str,
        units: str,
        forecast_days: int
    ) -> str:
        """
        Build the appropriate API URL based on request type.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            request_type: Type of request ('weather' or 'forecast')
            units: Temperature units
            forecast_days: Number of forecast days

        Returns:
            Complete API URL
        """
        base_params = f"lat={latitude}&lon={longitude}&units={units}&appid={self.api_key}"
        if request_type == 'weather':
            # Current weather - exclude minutely and hourly for cleaner response
            url = f"{self.base_url}/weather?{base_params}&exclude=minutely,hourly"
        elif request_type == 'forecast':
            # For forecast, use the 5-day/3-hour forecast API
            # cnt parameter limits the number of forecast entries (each is 3 hours)
            cnt = min(forecast_days * 8, 40)  # Max 40 entries (5 days * 8 intervals per day)
            url = f"{self.base_url}/forecast?{base_params}&cnt={cnt}"
        else:
            raise ValueError(f"Invalid request type: {request_type}")
        return url

    def _format_weather_response(
        self,
        data: Dict[str, Any],
        request_type: str,
        units: str,
        latitude: float,
        longitude: float
    ) -> Dict[str, Any]:
        """
        Format the weather API response for better usability.

        Args:
            data: Raw API response
            request_type: Type of request
            units: Temperature units used
            latitude: Original latitude
            longitude: Original longitude

        Returns:
            Formatted weather data
        """
        try:
            # Determine temperature unit symbol
            temp_unit = {
                'metric': '°C',
                'imperial': '°F',
                'standard': 'K'
            }.get(units, '°F')

            if request_type == 'weather':
                # Format current weather
                main = data.get('main', {})
                weather = data.get('weather', [{}])[0]
                wind = data.get('wind', {})
                sys = data.get('sys', {})

                formatted = {
                    'location': {
                        'latitude': latitude,
                        'longitude': longitude,
                        'city': data.get('name', 'Unknown'),
                        'country': sys.get('country', 'Unknown')
                    },
                    'current_weather': {
                        'temperature': f"{main.get('temp', 'N/A')}{temp_unit}",
                        'feels_like': f"{main.get('feels_like', 'N/A')}{temp_unit}",
                        'temperature_min': f"{main.get('temp_min', 'N/A')}{temp_unit}",
                        'temperature_max': f"{main.get('temp_max', 'N/A')}{temp_unit}",
                        'description': weather.get('description', 'N/A').title(),
                        'condition': weather.get('main', 'N/A'),
                        'humidity': f"{main.get('humidity', 'N/A')}%",
                        'pressure': f"{main.get('pressure', 'N/A')} hPa",
                        'visibility': f"{data.get('visibility', 'N/A')} m" if 'visibility' in data else 'N/A'
                    },
                    'wind': {
                        'speed': f"{wind.get('speed', 'N/A')} {'mph' if units == 'imperial' else 'm/s'}",
                        'direction': f"{wind.get('deg', 'N/A')}°" if 'deg' in wind else 'N/A',
                        'gust': f"{wind.get('gust', 'N/A')} {'mph' if units == 'imperial' else 'm/s'}" if 'gust' in wind else 'N/A'
                    },
                    'metadata': {
                        'request_type': request_type,
                        'units': units,
                        'timestamp': data.get('dt'),
                        'timezone': data.get('timezone'),
                        'sunrise': sys.get('sunrise'),
                        'sunset': sys.get('sunset')
                    }
                }

            else:  # forecast
                # Format forecast data
                forecasts = []
                for item in data.get('list', []):
                    main = item.get('main', {})
                    weather = item.get('weather', [{}])[0]
                    wind = item.get('wind', {})

                    forecast_item = {
                        'datetime': item.get('dt_txt', 'N/A'),
                        'timestamp': item.get('dt'),
                        'temperature': f"{main.get('temp', 'N/A')}{temp_unit}",
                        'feels_like': f"{main.get('feels_like', 'N/A')}{temp_unit}",
                        'temperature_min': f"{main.get('temp_min', 'N/A')}{temp_unit}",
                        'temperature_max': f"{main.get('temp_max', 'N/A')}{temp_unit}",
                        'description': weather.get('description', 'N/A').title(),
                        'condition': weather.get('main', 'N/A'),
                        'humidity': f"{main.get('humidity', 'N/A')}%",
                        'pressure': f"{main.get('pressure', 'N/A')} hPa",
                        'wind_speed': f"{wind.get('speed', 'N/A')} {'mph' if units == 'imperial' else 'm/s'}",
                        'precipitation_probability': f"{item.get('pop', 0) * 100:.0f}%" if 'pop' in item else 'N/A'
                    }
                    forecasts.append(forecast_item)

                city = data.get('city', {})
                formatted = {
                    'location': {
                        'latitude': latitude,
                        'longitude': longitude,
                        'city': city.get('name', 'Unknown'),
                        'country': city.get('country', 'Unknown')
                    },
                    'forecast': forecasts,
                    'forecast_summary': {
                        'total_entries': len(forecasts),
                        'forecast_period': f"{forecasts[0]['datetime']} to {forecasts[-1]['datetime']}" if forecasts else 'N/A'
                    },
                    'metadata': {
                        'request_type': request_type,
                        'units': units,
                        'timezone': city.get('timezone')
                    }
                }

            return formatted

        except Exception as e:
            self.logger.error(f"Error formatting weather response: {e}")
            # Return raw data if formatting fails
            return {
                'raw_data': data,
                'formatting_error': str(e),
                'metadata': {
                    'request_type': request_type,
                    'units': units,
                    'latitude': latitude,
                    'longitude': longitude
                }
            }

    async def _make_weather_request(self, url: str) -> Dict[str, Any]:
        """
        Make HTTP request to OpenWeather API using aiohttp.

        Args:
            url: Complete API URL

        Returns:
            API response as dictionary

        Raises:
            Exception: If request fails or returns invalid response
        """
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                self.logger.info(f"Making weather API request: {url.split('&appid=')[0]}...")

                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        self.logger.info(f"Weather API request successful (status: {response.status})")
                        return data
                    else:
                        error_text = await response.text()
                        self.logger.error(f"Weather API request failed: {response.status} - {error_text}")
                        raise Exception(f"API request failed with status {response.status}: {error_text}")

        except asyncio.TimeoutError:
            raise Exception(f"Weather API request timed out after {self.timeout} seconds")
        except aiohttp.ClientError as e:
            raise Exception(f"HTTP client error: {str(e)}")
        except Exception as e:
            raise Exception(f"Weather API request failed: {str(e)}")

    async def _execute(
        self,
        latitude: float,
        longitude: float,
        request_type: str = 'weather',
        units: str = 'imperial',
        country: str = 'us',
        forecast_days: int = 3,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute the weather request (AbstractTool interface).

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            request_type: Type of request ('weather' or 'forecast')
            units: Temperature units ('metric', 'imperial', 'standard')
            country: Country code
            forecast_days: Number of forecast days (for forecast requests)
            **kwargs: Additional arguments

        Returns:
            Formatted weather data
        """
        try:
            self.logger.info(
                f"Getting {request_type} for coordinates ({latitude}, {longitude}) "
                f"in {units} units for country {country}"
            )

            # Build API URL
            url = self._build_url(latitude, longitude, request_type, units, forecast_days)

            # Make API request
            raw_data = await self._make_weather_request(url)

            # Format response
            formatted_data = self._format_weather_response(
                raw_data, request_type, units, latitude, longitude
            )

            self.logger.info(f"Weather data retrieved successfully for {request_type} request")
            return formatted_data

        except Exception as e:
            self.logger.error(f"Error getting weather data: {e}")
            raise

    def execute_sync(
        self,
        latitude: float,
        longitude: float,
        request_type: str = 'weather',
        units: str = 'imperial',
        country: str = 'us',
        forecast_days: int = 3
    ) -> Dict[str, Any]:
        """
        Execute weather request synchronously.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            request_type: Type of request ('weather' or 'forecast')
            units: Temperature units
            country: Country code
            forecast_days: Number of forecast days

        Returns:
            Formatted weather data
        """
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self.execute(
                latitude=latitude,
                longitude=longitude,
                request_type=request_type,
                units=units,
                country=country,
                forecast_days=forecast_days
            ))
            return task
        except RuntimeError:
            return asyncio.run(self.execute(
                latitude=latitude,
                longitude=longitude,
                request_type=request_type,
                units=units,
                country=country,
                forecast_days=forecast_days
            ))

    def get_weather_summary(self, weather_data: ToolResult) -> str:
        """
        Generate a human-readable weather summary.

        Args:
            weather_result: ToolResult object containing weather data

        Returns:
            Human-readable weather summary
        """
        try:
            # Extract the actual weather data from ToolResult
            if weather_data.status != "success":
                return f"Weather request failed: {weather_data.error or 'Unknown error'}"

            weather_data = weather_data.result

            if weather_data.get('current_weather'):
                # Current weather summary
                current = weather_data['current_weather']
                location = weather_data['location']

                summary = (
                    f"Current weather in {location['city']}, {location['country']}: "
                    f"{current['description']} with a temperature of {current['temperature']} "
                    f"(feels like {current['feels_like']}). "
                    f"Humidity: {current['humidity']}, "
                    f"Wind: {weather_data['wind']['speed']}"
                )

            elif weather_data.get('forecast'):
                # Forecast summary
                location = weather_data['location']
                forecast_count = weather_data['forecast_summary']['total_entries']
                period = weather_data['forecast_summary']['forecast_period']

                summary = (
                    f"Weather forecast for {location['city']}, {location['country']}: "
                    f"{forecast_count} forecast entries from {period}"
                )

            else:
                summary = "Weather data available (see full response for details)"

            return summary

        except Exception as e:
            return f"Weather data retrieved (summary generation failed: {e})"

    def save_weather_data(
        self,
        weather_result: ToolResult,
        filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Save weather data to JSON file.

        Args:
            weather_result: ToolResult object containing weather data
            filename: Optional filename

        Returns:
            File information dictionary
        """
        if not self.output_dir:
            raise ValueError("Output directory not configured")

        # Extract weather data from ToolResult
        if weather_result.status != "success":
            raise ValueError(f"Cannot save failed weather request: {weather_result.error}")

        weather_data = weather_result.result

        if not filename:
            timestamp = self.generate_filename("weather_data", "", include_timestamp=True)
            filename = f"{timestamp}.json"
        elif not filename.endswith('.json'):
            filename = f"{filename}.json"

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        file_path = self.output_dir / filename
        file_path = self.validate_output_path(file_path)

        try:
            # Save both the result and metadata from ToolResult
            save_data = {
                "weather_data": weather_data,
                "tool_metadata": {
                    "status": weather_result.status,
                    "timestamp": weather_result.timestamp,
                    "metadata": weather_result.metadata
                }
            }

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=2, default=str)

            file_url = self.to_static_url(file_path)

            return {
                "filename": filename,
                "file_path": str(file_path),
                "file_url": file_url,
                "file_size": file_path.stat().st_size
            }

        except Exception as e:
            raise ValueError(f"Error saving weather data: {e}")

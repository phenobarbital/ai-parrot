from typing import Type, Optional, Any, Dict
from pydantic import BaseModel, Field, ConfigDict
import requests
from langchain.tools import BaseTool
from langchain.tools import Tool
from langchain_community.utilities import OpenWeatherMapAPIWrapper
from navconfig import config


class OpenWeatherMapTool(BaseTool):
    """Tool that searches the OpenWeatherMap API."""
    name: str = "OpenWeatherMap"
    description: str = (
        "A wrapper around OpenWeatherMap. "
        "Useful for when you need to answer general questions about "
        "weather, temperature, humidity, wind speed, or other weather-related information. "
    )
    search: Tool = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.search = OpenWeatherMapAPIWrapper(
            openweathermap_api_key=config.get('OPENWEATHER_APPID')
        )

    def _run(
        self,
        query: dict,
    ) -> dict:
        """Use the OpenWeatherMap tool."""
        return self.search.run(query)


class OpenWeatherInput(BaseModel):
    """
    Input schema for OpenWeather tool.
    This schema expects a dictionary with latitude and longitude.
    """
    latitude: float = Field(
        ...,
        description="The latitude of the location you want weather information about.",
        example=37.7749,
        ge=-90.0,  # Valid latitude range
        le=90.0
    )
    longitude: float = Field(
        ...,
        description="The longitude of the location you want weather information about.",
        example=-122.4194,
        ge=-180.0,  # Valid longitude range
        le=180.0
    )
    country: Optional[str] = Field(
        'us',
        description="The country code for the location (default is 'us').",
        example='us'
    )
    request: Optional[str] = Field(
        'weather',
        description="The type of weather information to request ('weather' or 'forecast').",
        example='weather'
    )

    model_config = ConfigDict(
        extra='forbid',
        json_schema_extra={
            "required": ["latitude", "longitude"]
        }
    )


class OpenWeather(BaseTool):
    """
    Tool to get weather information about a location.
    """
    name: str = 'openweather_tool'
    description: str = (
        "Get current weather information or forecast for a specific location. "
        "This tool requires latitude and longitude coordinates. "
        "You can also specify the type of request ('weather' for current weather or 'forecast' for a weather forecast). "
        "Optional fields: 'country' (default: 'us') and 'request' (default: 'weather', can be 'forecast'). "
        "Temperature is returned in Fahrenheit."
    )
    base_url: str = 'http://api.openweathermap.org/'
    units: str = 'imperial'  # 'metric', 'imperial', 'standard'
    days: int = 3
    appid: str = None
    request: str = 'weather'
    country: str = 'us'

    args_schema: Type[BaseModel] = OpenWeatherInput

    def __init__(self, request: str = 'weather', country: str = 'us', **kwargs):
        super().__init__(**kwargs)
        self.request = request
        self.country = country
        self.appid = config.get('OPENWEATHER_APPID')

    def _get_weather(self, input_data: OpenWeatherInput) -> Dict[str, Any]:
        """
        Get weather information based on latitude and longitude.
        """
        # Use the request type from input if provided, otherwise use instance default
        request_type = getattr(input_data, 'request', self.request)

        if request_type == 'weather':
            part = "hourly,minutely"
            url = f"https://api.openweathermap.org/data/2.5/weather?lat={input_data.latitude}&lon={input_data.longitude}&units={self.units}&exclude={part}&appid={self.appid}"
        elif request_type == 'forecast':
            url = f"{self.base_url}data/2.5/forecast?lat={input_data.latitude}&lon={input_data.longitude}&units={self.units}&cnt={self.days}&appid={self.appid}"
        else:
            return {'error': "Invalid request type. Use 'weather' or 'forecast'."}

        try:
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                return {'error': f"Failed to fetch data: {response.status_code} - {response.text}"}
            response_data = response.json()
            return response_data
        except requests.RequestException as e:
            return {'error': f"Request failed: {str(e)}"}
        except Exception as e:
            return {'error': f"Unexpected error: {str(e)}"}

    def _run(self, **kwargs) -> Dict[str, Any]:
        """
        Use the OpenWeather tool to get weather information.
        This method now properly handles the input schema.
        """
        try:
            # Create input object from kwargs
            input_data = OpenWeatherInput(**kwargs)
            return self._get_weather(input_data)
        except Exception as e:
            return {'error': f"Input validation failed: {str(e)}"}

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        """
        Async version of _run.
        """
        try:
            input_data = OpenWeatherInput(**kwargs)
            return self._get_weather(input_data)
        except Exception as e:
            return {'error': f"Input validation failed: {str(e)}"}

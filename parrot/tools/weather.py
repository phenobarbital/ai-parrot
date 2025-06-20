from typing import Type, Optional
from pydantic import BaseModel, Field, ConfigDict
import requests
from langchain.tools import BaseTool
from langchain.tools import Tool
from langchain_community.utilities import OpenWeatherMapAPIWrapper
from navconfig import config
import orjson

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
        example=37.7749
    )
    longitude: float = Field(
        ...,
        description="The longitude of the location you want weather information about.",
        example=-122.4194
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
        "Get weather information about a location, use this tool to answer questions about weather or weather forecast."
        " Input should be a dictionary with the latitude and longitude of the location you want weather information about."
        " Example input: 'latitude': 37.7749, 'longitude': -122.4194. "
        " Note: Temperature is returned on Fahrenheit by default, not Kelvin."
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

    def _get_weather(self, input: OpenWeatherInput) -> dict:
        """
        Get weather information based on latitude and longitude.
        """
        if self.request == 'weather':
            part = "hourly,minutely"
            url = f"https://api.openweathermap.org/data/2.5/weather?lat={input.latitude}&lon={input.longitude}&units={self.units}&exclude={part}&appid={self.appid}"
        elif self.request == 'forecast':
            url = f"{self.base_url}data/2.5/forecast?lat={input.latitude}&lon={input.longitude}&units={self.units}&cnt={self.days}&appid={self.appid}"
        else:
            return {'error': "Invalid request type. Use 'weather' or 'forecast'."}
        response = requests.get(url)
        if response.status_code != 200:
            return {'error': f"Failed to fetch data: {response.status_code} - {response.text}"}
        response_data = response.json()
        return response_data

    def _run(self, latitude: float, longitude: float, **kwargs) -> dict:
        """
        Use the OpenWeather tool to get weather information.
        """
        input_data = OpenWeatherInput(
            latitude=latitude,
            longitude=longitude,
            country=self.country,
            request=self.request
        )
        return self._get_weather(input_data)

    async def _arun(self, latitude: float, longitude: float, **kwargs) -> dict:
        input_data = OpenWeatherInput(
            latitude=latitude,
            longitude=longitude,
            country=self.country,
            request=self.request
        )
        return self._get_weather(input_data)

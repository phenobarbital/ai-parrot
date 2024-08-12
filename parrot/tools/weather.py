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


class OpenWeather(BaseTool):
    """
    Tool to get weather information about a location.
    """
    name: str = 'openweather_tool'
    description: str = (
        "Get weather information about a location, use this tool to answer questions about weather or weather forecast."
        " Input should be the latitude and longitude of the location you want weather information about."
    )
    base_url: str = 'http://api.openweathermap.org/'
    units: str = 'metric'
    days: int = 3
    appid: str = None
    request: str = 'weather'
    country: str = 'us'


    def __init__(self, request: str = 'weather', country: str = 'us', **kwargs):
        super().__init__(**kwargs)
        self.request = request
        self.country = country
        self.appid = config.get('OPENWEATHER_APPID')

    def _run(self, query: dict) -> dict:
        q = orjson.loads(query)  # pylint: disable=no-member
        if 'latitude' in q and 'longitude' in q:
            lat = q['latitude']
            lon = q['longitude']
            if self.request == 'weather':
                url = f"{self.base_url}data/2.5/weather?lat={lat}&lon={lon}&units={self.units}&appid={self.appid}"
            elif self.request == 'forecast':
                url = f"{self.base_url}data/2.5/forecast?lat={lat}&lon={lon}&units={self.units}&cnt={self.days}&appid={self.appid}"
        else:
            return {'error': 'Latitude and longitude are required'}
        response = requests.get(url)
        return response.json()

    async def _arun(self, query: dict) -> dict:
        raise NotImplementedError("Async method not implemented yet")

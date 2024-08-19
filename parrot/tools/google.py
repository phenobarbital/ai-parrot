from typing import Optional
import requests
from googleapiclient.discovery import build
from pydantic import PrivateAttr
# from crewai_tools import BaseTool
from langchain.tools import BaseTool
from navconfig import config
from ..conf import GOOGLE_API_KEY


class GoogleSearchTool(BaseTool):
    """Web Search tool using Google API."""
    name: str = "Google Web Search"
    description: str = (
        "Search the web using Google Search API, useful when you need to answer questions about current events.",
        " Use this tool more than the Wikipedia tool if you are asked about current events, recent information, or news"
    )
    source: str = 'news'
    max_results: int = 5
    region: str = 'US'
    # Fields populated during init (not required for validation)
    cse_id: Optional[str] = None
    search_key: Optional[str] = None
    kwargs: Optional[dict] = None

    def __init__(self, source: str = "news", results: int = 5, **kwargs):
        super().__init__(**kwargs)
        self.source = source
        self.max_results = results
        self.cse_id = config.get('GOOGLE_SEARCH_ENGINE_ID')
        self.search_key = config.get('GOOGLE_SEARCH_API_KEY')
        self.kwargs = kwargs

    def _run(self, query: str) -> list:
        """Run the Google Search Tool."""
        service = build("customsearch", "v1", developerKey=self.search_key)
        res = service.cse().list(  # pylint: disable=no-member
            q=query,
            cx=self.cse_id,
            num=self.max_results,
            **self.kwargs
        ).execute()
        results = []
        for item in res['items']:
            results.append(
                {
                    'snippet': item['snippet'],
                    'title': item['title'],
                    'link': item['link'],
                    'description': item['snippet']
                }
            )
        return results


class GoogleSiteSearchTool(BaseTool):
    """Web Search under a site using Google API."""
    name: str = "Google Web Search"
    description: str = "Search the web using Google Search API"
    source: str = 'news'
    max_results: int = 5
    region: str = ''

    def __init__(self, site: str = "news", results: int = 5, **kwargs):
        super().__init__(**kwargs)
        self.source = site
        self.max_results = results
        self._cse_id = config.get('GOOGLE_SEARCH_ENGINE_ID')
        self._search_key = config.get('GOOGLE_SEARCH_API_KEY')
        self._kwargs = kwargs

    def _run(self, query: str) -> dict:
        """Run the Google Search Tool."""
        service = build("customsearch", "v1", developerKey=self._search_key)
        qs = f'{query} site:{self.source}'
        res = service.cse().list(  # pylint: disable=no-member
            q=qs,
            cx=self._cse_id,
            num=self.max_results,
            **self._kwargs
        ).execute()
        results = []
        for item in res['items']:
            results.append(
                {
                    'snippet': item['snippet'],
                    'title': item['title'],
                    'link': item['link'],
                    'description': item['snippet']
                }
            )
        return results


class GoogleLocationFinder(BaseTool):
    """ LocationFinder class for finding locations."""
    name: str = "google_maps_location_finder"
    description: str = (
        "Search for location information, use this tool to find latitude, longitude and other geographical information from locations."
        " Provide the complete address to this tool to receive location information"
    )
    google_key: str = None
    base_url: str = "https://maps.googleapis.com/maps/api/geocode/json"
    kwargs: Optional[dict] = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.google_key = kwargs.get('api_key', GOOGLE_API_KEY)
        self.kwargs = kwargs

    def extract_location(self, data):
        city = state = state_code = zipcode = None
        try:
            for component in data['address_components']:
                if 'locality' in component['types']:
                    city = component['long_name']
                elif 'administrative_area_level_1' in component['types']:
                    state_code = component['short_name']
                    state = component['long_name']
                elif 'postal_code' in component['types']:
                    zipcode = component['long_name']
        except Exception:
            pass
        return city, state, state_code, zipcode

    def _run(self, query: str) -> dict:
        """Find Location."""
        params = {
            "address": query,
            "key": self.google_key
        }
        response = requests.get(
            self.base_url,
            params=params
        )
        if response.status_code == 200:
            result = response.json()
            if result['status'] == 'OK':
                location = result['results'][0]
                city, state, state_code, zipcode = self.extract_location(
                    location
                )
                return  {
                    "latitude": location['geometry']['location']['lat'],
                    "longitude": location['geometry']['location']['lng'],
                    "address": location['formatted_address'],
                    "place_id": location['place_id'],
                    "zipcode": zipcode,
                    "city": city,
                    "state": state,
                    "state_code": state_code
                }
            return None
        else:
            return None

class GoogleRouteSearch(BaseTool):
    """Web Search under a site using Google API."""
    name: str = "google_maps_route_search"
    description: str = "Search for a Route to a location using Google Maps, using this tool if answers questions about how to reach a location."
    google_key: str = None
    base_url: str = 'https://maps.googleapis.com/maps/api/directions/json'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._key_ = kwargs.get('api_key', GOOGLE_API_KEY)
        self._kwargs = kwargs

    def _run(self, query: str) -> dict:
        departure_time = 'now'

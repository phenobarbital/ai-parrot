"""
ZipcodeAPI Toolkit - A unified toolkit for zipcode operations.
"""
from typing import List, Dict, Any, Optional, Union
import httpx
from pydantic import BaseModel, Field
from navconfig import config
from .toolkit import AbstractToolkit
from .decorators import tool_schema


# Input schemas for different operations
class BasicZipcodeInput(BaseModel):
    """Basic input schema for zipcode operations."""
    zipcode: Union[str, int] = Field(description="The zipcode")
    unit: Optional[str] = Field(description="Unit for coordinates (degrees, radians)", default="degrees")


class ZipcodeDistanceInput(BaseModel):
    """Input schema for zipcode distance calculation."""
    zipcode1: Union[str, int] = Field(description="The first zipcode")
    zipcode2: Union[str, int] = Field(description="The second zipcode")
    unit: Optional[str] = Field(description="Unit for coordinates (degrees, radians)", default="degrees")


class ZipcodeRadiusInput(BaseModel):
    """Input schema for zipcode radius search."""
    zipcode: Union[str, int] = Field(description="The center zipcode")
    radius: int = Field(description="The radius in miles", default=5)
    unit: Optional[str] = Field(description="Unit for coordinates (degrees, radians)", default="degrees")


class CityToZipcodesInput(BaseModel):
    """Input schema for city to zipcodes lookup."""
    city: str = Field(description="The city name")
    state: str = Field(description="The state abbreviation (e.g., 'FL', 'CA')")


class ZipcodeAPIToolkit(AbstractToolkit):
    """
    Toolkit for interacting with ZipcodeAPI service.

    Provides methods for:
    - Getting zipcode location information
    - Calculating distance between zipcodes
    - Finding zipcodes within a radius
    - Finding zipcodes for a city/state
    """

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        """
        Initialize the ZipcodeAPI toolkit.

        Args:
            api_key: ZipcodeAPI key. If None, will use config.get('ZIPCODE_API_KEY')
            **kwargs: Additional toolkit configuration
        """
        super().__init__(**kwargs)
        self.api_key = api_key or config.get('ZIPCODE_API_KEY')
        if not self.api_key:
            raise ValueError(
                "ZipcodeAPI key is required. Set ZIPCODE_API_KEY in config or pass api_key parameter."
            )

    @tool_schema(BasicZipcodeInput)
    async def get_zipcode_location(self, zipcode: Union[str, int], unit: str = "degrees") -> Dict[str, Any]:
        """
        Get geographical information for a zipcode including city, state, latitude, longitude, and timezone.

        Args:
            zipcode: The zipcode to lookup
            unit: Unit for coordinates (degrees, radians)

        Returns:
            Dictionary with location information
        """
        url = f"https://www.zipcodeapi.com/rest/{self.api_key}/info.json/{zipcode}/{unit}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            raise ValueError(f"Error fetching zipcode location for {zipcode}: {e}") from e

    @tool_schema(ZipcodeDistanceInput)
    async def calculate_zipcode_distance(
        self,
        zipcode1: Union[str, int],
        zipcode2: Union[str, int],
        unit: str = "mile"
    ) -> Dict[str, Any]:
        """
        Calculate the distance between two zipcodes.

        Args:
            zipcode1: First zipcode
            zipcode2: Second zipcode
            unit: Unit of distance (mile, km)

        Returns:
            Dictionary with distance information
        """
        url = f"https://www.zipcodeapi.com/rest/{self.api_key}/distance.json/{zipcode1}/{zipcode2}/{unit}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            raise ValueError(f"Error calculating distance between {zipcode1} and {zipcode2}: {e}") from e

    @tool_schema(ZipcodeRadiusInput)
    async def find_zipcodes_in_radius(
        self,
        zipcode: Union[str, int],
        radius: int = 5,
        unit: str = "mile"
    ) -> Dict[str, Any]:
        """
        Find all zipcodes within a given radius of a center zipcode.

        Args:
            zipcode: Center zipcode
            radius: Search radius
            unit: Unit of distance (mile, km)

        Returns:
            Dictionary with list of zipcodes in radius
        """
        url = f"https://www.zipcodeapi.com/rest/{self.api_key}/radius.json/{zipcode}/{radius}/{unit}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            raise ValueError(f"Error finding zipcodes within {radius} {unit}s of {zipcode}: {e}") from e

    @tool_schema(CityToZipcodesInput)
    async def get_city_zipcodes(self, city: str, state: str) -> Dict[str, Any]:
        """
        Get all zipcodes for a given city and state.

        Args:
            city: City name
            state: State abbreviation (e.g., 'FL', 'CA')

        Returns:
            Dictionary with list of zipcodes for the city
        """
        url = f"https://www.zipcodeapi.com/rest/{self.api_key}/city-zips.json/{city}/{state}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            raise ValueError(f"Error getting zipcodes for {city}, {state}: {e}") from e

    async def get_multiple_locations(
        self,
        zipcodes: List[Union[str, int]],
        unit: str = "degrees"
    ) -> Dict[str, Any]:
        """
        Get location information for multiple zipcodes.

        Args:
            zipcodes: List of zipcodes to lookup
            unit: Unit for coordinates

        Returns:
            Dictionary mapping zipcodes to their location info
        """
        results = {}

        async with httpx.AsyncClient() as client:
            for zipcode in zipcodes:
                try:
                    url = f"https://www.zipcodeapi.com/rest/{self.api_key}/info.json/{zipcode}/{unit}"
                    response = await client.get(url)
                    response.raise_for_status()
                    results[str(zipcode)] = response.json()
                except httpx.HTTPStatusError as e:
                    results[str(zipcode)] = {"error": f"Failed to fetch: {e}"}

        return {"results": results}

    async def validate_zipcode(self, zipcode: Union[str, int]) -> Dict[str, Any]:
        """
        Validate if a zipcode exists and return basic info.

        Args:
            zipcode: Zipcode to validate

        Returns:
            Dictionary with validation result and basic info if valid
        """
        try:
            result = await self.get_zipcode_location(zipcode)
            return {
                "valid": True,
                "zipcode": zipcode,
                "city": result.get("city"),
                "state": result.get("state")
            }
        except ValueError:
            return {
                "valid": False,
                "zipcode": zipcode,
                "error": "Invalid zipcode"
            }

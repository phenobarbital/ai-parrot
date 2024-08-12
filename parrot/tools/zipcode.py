from typing import List, Dict, Any, Optional, Type, Union
import httpx
from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools import BaseToolkit
from langchain_core.pydantic_v1 import BaseModel, Field, Extra
from langchain_core.tools import BaseTool
from navconfig import config
from .abstract import AbstractTool


class ZipcodeDistanceInput(BaseModel):
    """Input for the Zipcode Distance Tool."""
    zipcode1: Union[str, int] = Field(description="The first zipcode.")
    zipcode2: Union[str, int] = Field(description="The second zipcode.")
    unit: Optional[str] = Field(description="The unit of the distance.", default="mile")


class ZipcodeRadiusInput(BaseModel):
    """Input for the Zipcode Radius Tool."""
    zipcode: Union[str, int] = Field(description="The zipcode.")
    radius: int = Field(description="The radius in miles.", default=5)
    unit: Optional[str] = Field(description="The unit of the distance.", default="mile")


class ZipcodeLocationInput(BaseModel):
    """Input for the Zipcode Location Tool."""
    zipcode: Union[str, int] = Field(description="The zipcode.")
    unit: Optional[str] = Field(description="The unit of the distance.", default="degrees")


class ZipcodeDistance(AbstractTool):
    """Tool for calculating the distance between two zipcodes."""

    name: str = "zipcode_distance"
    verbose: bool = True
    args_schema: Type[BaseModel] = ZipcodeDistanceInput
    description: str = (
        "Use this tool to calculate the distance between two zipcodes."
        " Zipcodes must be provided as a couple of strings (e.g., '33066')."
    )

    class Config:
        """Configuration for this pydantic object."""
        # extra = Extra.forbid
        arbitrary_types_allowed = True

    def _search(
        self,
        zipcode1: str,
        zipcode2: str,
        unit: Optional[str] = 'mile',
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> Dict[str, Any]:  # Changed to Dict
        api_key = config.get('ZIPCODE_API_KEY')
        url = f"https://www.zipcodeapi.com/rest/{api_key}/distance.json/{zipcode1}/{zipcode2}/{unit}"

        try:
            response = httpx.get(url)
            response.raise_for_status()  # Check for API errors
            return response.json()
        except httpx.HTTPStatusError as e:
            raise ValueError(f"Error fetching zipcode distance: {e}") from e

    async def _asearch(
        self,
        zipcode1: str,
        zipcode2: str,
        unit: Optional[str] = 'mile',
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> Dict[str, Any]:
        api_key = config.get('ZIPCODE_API_KEY')
        url = f"https://www.zipcodeapi.com/rest/{api_key}/distance.json/{zipcode1}/{zipcode2}/{unit}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                response.raise_for_status()  # Check for API errors
                return response.json()
        except httpx.HTTPStatusError as e:
            raise ValueError(f"Error fetching zipcode distance: {e}") from e


class ZipcodeRadius(AbstractTool):
    """Tool for calculating the distance between two zipcodes."""

    name: str = "zipcodes_by_radius"
    verbose: bool = True
    args_schema: Type[BaseModel] = ZipcodeRadiusInput
    description: str = (
        "Use this Tool to find all US zip codes within a given radius of a zip code."
        " Provides a Zipcode and a radius."
    )

    class Config:
        """Configuration for this pydantic object."""
        extra = Extra.forbid
        arbitrary_types_allowed = True

    def _search(
        self,
        zipcode: Union[str, int],
        radius: int = 5,
        unit: Optional[str] = 'mile',
    ) -> Dict[str, Any]:  # Changed to Dict
        api_key = config.get('ZIPCODE_API_KEY')
        url = f"https://www.zipcodeapi.com/rest/{api_key}/radius.json/{zipcode}/{radius}/{unit}"
        try:
            response = httpx.get(url)
            response.raise_for_status()  # Check for API errors
            return response.json()
        except httpx.HTTPStatusError as e:
            raise ValueError(f"Error fetching zipcode distance: {e}") from e

    async def _asearch(
        self,
        zipcode: str,
        radius: int,
        unit: Optional[str] = 'mile'
    ) -> Dict[str, Any]:
        api_key = config.get('ZIPCODE_API_KEY')
        url = f"https://www.zipcodeapi.com/rest/{api_key}/radius.json/{zipcode}/{radius}/{unit}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                response.raise_for_status()  # Check for API errors
                return response.json()
        except httpx.HTTPStatusError as e:
            raise ValueError(f"Error fetching zipcode distance: {e}") from e



class ZipcodeLocation(AbstractTool):
    """Tool for calculating Geographical information about a Zipcode."""

    name: str = "zipcode_location"
    verbose: bool = True
    args_schema: Type[BaseModel] = ZipcodeLocationInput
    description: str = (
        "Use this Tool to find out the city, state, latitude, longitude, and time zone information for a US zip code."
        " Use this tool to find geographical information about a zipcode. "
        " Provides only a Zipcode as string."
    )

    class Config:
        """Configuration for this pydantic object."""
        extra = Extra.forbid
        arbitrary_types_allowed = True

    def _search(
        self,
        zipcode: str,
        unit: Optional[str] = 'degrees'
    ) -> Dict[str, Any]:  # Changed to Dict
        api_key = config.get('ZIPCODE_API_KEY')
        url = f"https://www.zipcodeapi.com/rest/{api_key}/info.json/{zipcode}/{unit}"

        try:
            response = httpx.get(url)
            response.raise_for_status()  # Check for API errors
            return response.json()
        except httpx.HTTPStatusError as e:
            raise ValueError(f"Error fetching zipcode distance: {e}") from e


class ZipcodeAPIToolkit(BaseToolkit):
    """Toolkit for interacting with ZipcodeAPI.
    """
    class Config:
        """Pydantic config."""
        arbitrary_types_allowed = True

    def get_tools(self) -> List[BaseTool]:
        """Get the tools in the toolkit."""
        return [
            ZipcodeLocation(),
            ZipcodeRadius(),
            ZipcodeDistance()
        ]

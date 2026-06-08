from typing import List
import pandas as pd

from .base import WorkdayTypeBase
from ..models import Location
from ..parsers import parse_location_data
from ..utils import safe_serialize


class LocationType(WorkdayTypeBase):
    """Handler for the Workday Get_Locations operation."""

    def _get_default_payload(self) -> dict:
        """
        Payload base específico para locations.
        """
        return {
            "Response_Filter": {},
            "Response_Group": {
                "Include_Reference": True,
                "Include_Location_Data": True,
            },
        }

    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Execute the Get_Locations operation and return a pandas DataFrame.

        Supported parameters:
        - location_id: Specific location ID to fetch (uses Request_References)
        - location_name: Filter by location name (uses Request_Criteria)
        - location_type: Filter by location type
        - location_usage: Filter by location usage
        - inactive: Filter by inactive status (True/False)
        """
        # Extract parameters
        location_id = kwargs.pop("location_id", None)
        location_name = kwargs.pop("location_name", None)
        location_type = kwargs.pop("location_type", None)
        location_usage = kwargs.pop("location_usage", None)
        inactive = kwargs.pop("inactive", None)

        # Build request payload
        payload = {**self.request_payload}

        # Use Request_References for specific location ID
        if location_id:
            payload["Request_References"] = {
                "Location_Reference": [
                    {"ID": [{"type": "Location_ID", "_value_1": location_id}]}
                ]
            }

        # Use Request_Criteria for filtering
        elif any([location_name, location_type, location_usage, inactive]):
            payload["Request_Criteria"] = {}
            
            # Location name filter
            if location_name:
                payload["Request_Criteria"]["Location_Name"] = location_name
            
            # Location type filter
            if location_type:
                payload["Request_Criteria"]["Location_Type_Reference"] = [
                    {"ID": {"type": "Location_Type_ID", "_value_1": location_type}}
                ]
            
            # Location usage filter
            if location_usage:
                payload["Request_Criteria"]["Location_Usage_Reference"] = [
                    {"ID": {"type": "Location_Usage_ID", "_value_1": location_usage}}
                ]
            
            # Inactive filter
            if inactive is not None:
                if inactive:
                    payload["Request_Criteria"]["Exclude_Active_Locations"] = True
                else:
                    payload["Request_Criteria"]["Exclude_Inactive_Locations"] = True

        # Execute the operation with pagination
        try:
            locations_raw = await self._paginate_soap_operation(
                operation="Get_Locations",
                data_path=["Response_Data", "Location"],
                results_path=["Response_Results"],
                all_pages=True,
                **payload
            )
        except Exception:
            raise

        # Parse into Pydantic models
        parsed: List[Location] = []
        for i, loc in enumerate(locations_raw):
            try:
                parsed_data = parse_location_data(loc)
                parsed_data["raw_data"] = loc
                location = Location(**parsed_data)
                parsed.append(location)
            except Exception as e:
                self._logger.warning(f"Error parsing location {i+1}: {e}")
                continue



        # Build DataFrame and serialize complex columns
        df = pd.DataFrame([loc.model_dump() for loc in parsed])
        
        # Serialize complex columns
        for col in ["location_usage", "location_attributes", "location_hierarchy"]:
            if col in df.columns:
                df[col] = df[col].apply(safe_serialize)

        # Add metrics
        self.service.add_metric("NUM_LOCATIONS", len(parsed))
        
        return df

    async def get_location_by_id(self, location_id: str) -> pd.DataFrame:
        """
        Convenience method to get a specific location by ID.
        """
        return await self.execute(location_id=location_id)

    async def get_location_by_name(self, location_name: str) -> pd.DataFrame:
        """
        Convenience method to get a specific location by name.
        """
        return await self.execute(location_name=location_name)

    async def get_locations_by_type(self, location_type: str) -> pd.DataFrame:
        """
        Convenience method to get locations by type.
        """
        return await self.execute(location_type=location_type)

    async def get_active_locations(self) -> pd.DataFrame:
        """
        Convenience method to get all active locations.
        """
        return await self.execute(inactive=False) 
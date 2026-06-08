"""
Get_Location_Hierarchy_Organization_Assignments operation handler.

This module handles the Get_Location_Hierarchy_Organization_Assignments operation
which retrieves organization assignments for location hierarchies.
"""

import logging
from typing import Any, Dict
import pandas as pd
import asyncio

from .base import WorkdayTypeBase
from ..utils import safe_serialize
from ..parsers.location_hierarchy_assignments_parsers import parse_location_hierarchy_assignment

logger = logging.getLogger(__name__)


class LocationHierarchyAssignmentsType(WorkdayTypeBase):
    """
    Handler for Get_Location_Hierarchy_Organization_Assignments operation.
    
    Retrieves organization assignments for location hierarchies.
    """
    
    def __init__(self, component, max_retries: int = 5, retry_delay: float = 2.0, **kwargs):
        """
        Initialize LocationHierarchyAssignmentsType with robust retry settings.
        
        :param component: Component instance
        :param max_retries: Maximum retry attempts (default: 5 for connection resilience)
        :param retry_delay: Delay between retries in seconds (default: 2.0 for API rate limiting)
        :param kwargs: Additional parameters
        """
        super().__init__(component, max_retries=max_retries, retry_delay=retry_delay)
        self.operation_name = "Get_Location_Hierarchy_Organization_Assignments"
    
    def _get_default_payload(self) -> Dict[str, Any]:
        """
        Default payload structure for Get_Location_Hierarchy_Organization_Assignments operation.
        """
        return {
            "Response_Filter": {},
        }
    
    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Execute Get_Location_Hierarchy_Organization_Assignments operation.
        
        Args:
            **kwargs: Additional parameters including:
                - location_hierarchy_ids: List of location hierarchy IDs to fetch
                - location_hierarchy_id_type: Type of ID (WID, Organization_Reference_ID)
                - as_of_effective_date: Date for effective data
                - as_of_entry_datetime: Date/time for entry data
                - page: Page number for pagination
                - count: Number of results per page
        
        Returns:
            pandas DataFrame containing the location hierarchy organization assignments
        """
        self._logger.info("Executing Get_Location_Hierarchy_Organization_Assignments")
        
        # Extract parameters
        location_hierarchy_ids = kwargs.pop("location_hierarchy_ids", None)
        location_hierarchy_id_type = kwargs.pop("location_hierarchy_id_type", "Organization_Reference_ID")
        as_of_effective_date = kwargs.pop("as_of_effective_date", None)
        as_of_entry_datetime = kwargs.pop("as_of_entry_datetime", None)
        page = kwargs.pop("page", None)
        count = kwargs.pop("count", None)
        
        # Build request payload
        payload = {**self.request_payload}
        
        # Add Request_References if specific location hierarchy IDs are provided
        if location_hierarchy_ids:
            if isinstance(location_hierarchy_ids, str):
                location_hierarchy_ids = [location_hierarchy_ids]
            
            payload["Request_References"] = {
                "Location_Hierarchy_Reference": []
            }
            
            for hierarchy_id in location_hierarchy_ids:
                payload["Request_References"]["Location_Hierarchy_Reference"].append({
                    "ID": [{"type": location_hierarchy_id_type, "_value_1": hierarchy_id}]
                })
        
        # Add Response_Filter parameters
        if any([as_of_effective_date, as_of_entry_datetime, page, count]):
            if "Response_Filter" not in payload:
                payload["Response_Filter"] = {}
            
            if as_of_effective_date:
                payload["Response_Filter"]["As_Of_Effective_Date"] = as_of_effective_date
            
            if as_of_entry_datetime:
                payload["Response_Filter"]["As_Of_Entry_DateTime"] = as_of_entry_datetime
            
            if page:
                payload["Response_Filter"]["Page"] = page
            
            if count:
                payload["Response_Filter"]["Count"] = count
        
        
        try:
            # Execute the operation with pagination
            if location_hierarchy_ids:
                # For specific location hierarchies, don't use pagination
                self._logger.info("Fetching specific location hierarchy assignments without pagination")
                
                # Use retry for specific location hierarchies
                raw = None
                for attempt in range(1, self.max_retries + 1):
                    try:
                        raw = await self.service.call_operation(operation="Get_Location_Hierarchy_Organization_Assignments", **payload)
                        break
                    except Exception as exc:
                        self._logger.warning(
                            f"[Get_Location_Hierarchy_Organization_Assignments] Error fetching specific assignments "
                            f"(attempt {attempt}/{self.max_retries}): {exc}"
                        )
                        if attempt == self.max_retries:
                            self._logger.error(
                                f"[Get_Location_Hierarchy_Organization_Assignments] Failed to fetch specific assignments after "
                                f"{self.max_retries} attempts."
                            )
                            raise
                        await asyncio.sleep(self.retry_delay)
                
                data = self.service.serialize_object(raw)
                items = data.get("Response_Data", {}).get("Location_Hierarchy_Organization_Assignments", [])
                if isinstance(items, dict):
                    assignments_raw = [items]
                else:
                    assignments_raw = items or []
            else:
                # For all location hierarchies, use pagination
                self._logger.info("Fetching all location hierarchy assignments with pagination")
                assignments_raw = await self._paginate_soap_operation(
                    operation="Get_Location_Hierarchy_Organization_Assignments",
                    data_path=["Response_Data", "Location_Hierarchy_Organization_Assignments"],
                    results_path=["Response_Results"],
                    all_pages=True,
                    **payload
                )
            
            # Parse the assignments data using the new parser
            parsed_data = []
            for i, assignment in enumerate(assignments_raw):
                try:
                    # Each assignment is already a Location_Hierarchy_Organization_Assignments object
                    # Extract the data section
                    assignment_data_raw = assignment.get("Location_Hierarchy_Organization_Assignments_Data", {})
                    
                    # Handle case where assignment_data_raw is a list
                    if isinstance(assignment_data_raw, list) and len(assignment_data_raw) > 0:
                        assignment_data = assignment_data_raw[0]  # Take the first element
                    else:
                        assignment_data = assignment_data_raw
                    
                    if assignment_data:
                        parsed_assignment = parse_location_hierarchy_assignment(assignment_data)
                        # Only add if we have valid data
                        if (parsed_assignment and 
                            (parsed_assignment.location_hierarchy_id or parsed_assignment.location_hierarchy_wid) and
                            parsed_assignment.organization_assignments):
                            parsed_data.append(parsed_assignment)
                except Exception as e:
                    self._logger.error(f"Error parsing assignment {i+1}: {e}")
                    self._logger.error(f"Raw data: {safe_serialize(assignment)}")
                    continue
            
            # Convert to DataFrame
            if parsed_data:
                # Convert Pydantic models to dictionaries for DataFrame
                df_data = []
                for assignment in parsed_data:
                    assignment_dict = assignment.dict()
                    
                    # Flatten organization assignments for better DataFrame structure
                    org_assignments = assignment_dict.pop("organization_assignments", [])
                    
                    # Create a row for each organization assignment
                    if org_assignments:
                        for org_assignment in org_assignments:
                            row = assignment_dict.copy()
                            row.update({
                                "organization_type_id": org_assignment.get("organization_type_id"),
                                "organization_type_descriptor": org_assignment.get("organization_type_descriptor"),
                                "allowed_organizations_count": len(org_assignment.get("allowed_organizations", [])),
                                "allowed_organizations": safe_serialize(org_assignment.get("allowed_organizations", [])),
                                "delete_assignment": org_assignment.get("delete", False)
                            })
                            df_data.append(row)
                    else:
                        # If no organization assignments, still include the location hierarchy
                        row = assignment_dict.copy()
                        row.update({
                            "organization_type_id": None,
                            "organization_type_descriptor": None,
                            "allowed_organizations_count": 0,
                            "allowed_organizations": "[]",
                            "delete_assignment": False
                        })
                        df_data.append(row)
                
                df = pd.DataFrame(df_data)
                
                # Serialize complex columns
                for col in ["location_hierarchy_reference"]:
                    if col in df.columns:
                        df[col] = df[col].apply(safe_serialize)
                
                self._logger.info(f"Successfully retrieved {len(df)} location hierarchy assignment records")
                self.service.add_metric("NUM_ASSIGNMENTS", len(df))
                return df
            else:
                self._logger.warning("No location hierarchy assignments found")
                return pd.DataFrame()
                
        except Exception as e:
            self._logger.error(f"Error executing Get_Location_Hierarchy_Organization_Assignments: {str(e)}")
            raise
    
    async def get_assignments_by_location_hierarchy(self, location_hierarchy_id: str, id_type: str = "Organization_Reference_ID") -> pd.DataFrame:
        """
        Get organization assignments for a specific location hierarchy.
        
        Args:
            location_hierarchy_id: The location hierarchy ID to fetch
            id_type: Type of ID (WID, Organization_Reference_ID)
            
        Returns:
            DataFrame with organization assignments for the location hierarchy
        """
        return await self.execute(location_hierarchy_ids=[location_hierarchy_id], location_hierarchy_id_type=id_type)
    
    async def get_all_assignments(self, **kwargs) -> pd.DataFrame:
        """
        Get all location hierarchy organization assignments.
        
        Args:
            **kwargs: Additional parameters for filtering
            
        Returns:
            DataFrame with all location hierarchy organization assignments
        """
        return await self.execute(**kwargs) 
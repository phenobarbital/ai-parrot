"""
Get_Organization operation handler.

This module handles the Get_Organization operation which retrieves
a specific organization by its ID (singular, not plural).
"""

import logging
from typing import Any, Dict
from zeep import Client
import pandas as pd

from .base import WorkdayTypeBase
from ..parsers.organization_parsers import parse_organization_data

logger = logging.getLogger(__name__)


class GetOrganization(WorkdayTypeBase):
    """
    Handler for Get_Organization operation.
    
    Retrieves a specific organization by its ID.
    """
    
    def __init__(self, client: Client, **kwargs):
        super().__init__(client, **kwargs)
        self.operation_name = "Get_Organization"
    
    def _get_default_payload(self) -> Dict[str, Any]:
        """
        Default payload structure for Get_Organization operation.
        Get_Organization only accepts: Organization_Reference, As_Of_Date, As_Of_Moment, version
        """
        return {}
    
    async def execute(self, organization_id: str, organization_id_type: str = "Organization_Reference_ID", **kwargs) -> pd.DataFrame:
        """
        Execute Get_Organization operation to retrieve a specific organization.
        
        Args:
            organization_id: The ID of the organization to retrieve
            organization_id_type: The type of ID (Organization_Reference_ID, WID, etc.)
            **kwargs: Additional parameters
            
        Returns:
            pandas DataFrame containing the organization data
        """
        self._logger.info(f"Executing Get_Organization for ID: {organization_id} (type: {organization_id_type})")
        
        # Build the request payload - only Organization_Reference is required
        payload = {
            "Organization_Reference": {
                "Integration_ID_Reference": {
                    "ID": {
                        "_value_1": organization_id,
                        "System_ID": "WD-WID"
                    }
                }
            }
        }
        
        # Add any additional parameters (As_Of_Date, As_Of_Moment, version)
        payload.update(kwargs)
        
        self._logger.debug(f"Get_Organization payload: {payload}")
        
        try:
            # Make the SOAP call
            response = await self.service.call_operation(operation="Get_Organization", **payload)
            
            # Log the raw response for debugging
            self._logger.info("=== RAW Get_Organization RESPONSE ===")
            self._logger.info(f"Response type: {type(response)}")
            self._logger.info(f"Response content: {response}")
            
            # Convert to dict for easier handling
            response_dict = self.service.serialize_object(response)
            self._logger.info("=== CONVERTED TO DICT ===")
            self._logger.info(f"Response dict keys: {list(response_dict.keys()) if isinstance(response_dict, dict) else 'Not a dict'}")
            
            if isinstance(response_dict, dict):
                # Extract organization data
                org_data = response_dict.get("Organization_Data", {})
                self._logger.info("=== ORGANIZATION DATA ===")
                self._logger.info(f"Organization data keys: {list(org_data.keys()) if isinstance(org_data, dict) else 'Not a dict'}")
                
                if org_data:
                    # Parse the organization data
                    parsed_data = parse_organization_data(org_data)
                    self._logger.info("=== PARSED DATA ===")
                    self._logger.info(f"Parsed data: {parsed_data}")
                    
                    # Convert to DataFrame
                    df = pd.DataFrame([parsed_data])
                    self._logger.info(f"Created DataFrame with {len(df)} rows and {len(df.columns)} columns")
                    
                    return df
                else:
                    self._logger.warning("No Organization_Data found in response")
                    return pd.DataFrame()
            else:
                self._logger.warning(f"Unexpected response format: {type(response_dict)}")
                return pd.DataFrame()
                
        except Exception as e:
            self._logger.error(f"Error executing Get_Organization: {str(e)}")
            raise
    
    async def get_organization_by_wid(self, wid: str, **kwargs) -> pd.DataFrame:
        """
        Get organization by WID.
        
        Args:
            wid: The WID of the organization
            **kwargs: Additional parameters
            
        Returns:
            pandas DataFrame containing the organization data
        """
        return await self.execute(wid, "WID", **kwargs)
    
    async def get_organization_by_reference_id(self, reference_id: str, **kwargs) -> pd.DataFrame:
        """
        Get organization by Organization_Reference_ID.
        
        Args:
            reference_id: The Organization_Reference_ID
            **kwargs: Additional parameters
            
        Returns:
            pandas DataFrame containing the organization data
        """
        return await self.execute(reference_id, "Organization_Reference_ID", **kwargs)
    
    async def get_organization_by_custom_id(self, custom_id: str, **kwargs) -> pd.DataFrame:
        """
        Get organization by Custom_Organization_Reference_ID.
        
        Args:
            custom_id: The Custom_Organization_Reference_ID
            **kwargs: Additional parameters
            
        Returns:
            pandas DataFrame containing the organization data
        """
        return await self.execute(custom_id, "Custom_Organization_Reference_ID", **kwargs) 
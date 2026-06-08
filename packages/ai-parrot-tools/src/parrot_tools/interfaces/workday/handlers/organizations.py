from typing import List
import pandas as pd

from .base import WorkdayTypeBase
from ..models.organizations import Organization
from ..parsers.organization_parsers import parse_organization_data
from ..utils import safe_serialize


class OrganizationType(WorkdayTypeBase):
    """Handler for the Workday Get_Organizations operation."""

    def _get_default_payload(self) -> dict:
        """
        Payload base específico para organizations.
        """
        return {
            "Response_Filter": {},
            "Response_Group": {
                "Include_Roles_Data": True,
                "Include_Hierarchy_Data": True,
                "Include_Supervisory_Data": True,
                "Include_Staffing_Restrictions_Data": True,
            },
        }

    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Execute the Get_Organizations operation and return a pandas DataFrame.

        Supported parameters:
        - organization_id: Specific organization ID to fetch (uses Request_References)
        - organization_id_type: Type of organization ID (WID, Organization_Reference_ID, Cost_Center_Reference_ID, etc.)
        - organization_type: Filter by organization type (Company, Cost Center, Custom, Matrix, Pay Group, Region, Retiree, Supervisory, etc.)
        - include_inactive: Include inactive organizations (True/False)
        - enable_transaction_log_lite: Enable transaction log lite (True/False)
        """
        # Extract parameters
        organization_id = kwargs.pop("organization_id", None)
        organization_id_type = kwargs.pop("organization_id_type", "Organization_Reference_ID")
        organization_type = kwargs.pop("organization_type", None)
        include_inactive = kwargs.pop("include_inactive", None)
        enable_transaction_log_lite = kwargs.pop("enable_transaction_log_lite", None)

        # Build request payload
        payload = {**self.request_payload}

        # Use Request_References for specific organization ID
        if organization_id:
            payload["Request_References"] = {
                "Organization_Reference": [
                    {"ID": [{"type": organization_id_type, "_value_1": organization_id}]}
                ]
            }
        # Use Request_Criteria for filtering (only if no specific organization_id)
        elif any([organization_type, include_inactive, enable_transaction_log_lite]):
            payload["Request_Criteria"] = {}
            
            # Organization type filter
            if organization_type:
                payload["Request_Criteria"]["Organization_Type_Reference"] = [
                    {"ID": {"type": "Organization_Type_ID", "_value_1": organization_type}}
                ]
            
            # Include inactive filter
            if include_inactive is not None:
                payload["Request_Criteria"]["Include_Inactive"] = include_inactive
            
            # Transaction log lite filter
            if enable_transaction_log_lite is not None:
                payload["Request_Criteria"]["Enable_Transaction_Log_Lite"] = enable_transaction_log_lite

        # Execute the operation with pagination
        try:
            if organization_id:
                # For specific organization, don't use pagination
                self._logger.info("Fetching specific organization without pagination")
                raw = await self.service.call_operation(operation="Get_Organizations", **payload)
                data = self.service.serialize_object(raw)
                items = data.get("Response_Data", {}).get("Organization", [])
                if isinstance(items, dict):
                    organizations_raw = [items]
                else:
                    organizations_raw = items or []
            else:
                # For filtered results, use pagination
                self._logger.info("Fetching organizations with pagination")
                organizations_raw = await self._paginate_soap_operation(
                    operation="Get_Organizations",
                    data_path=["Response_Data", "Organization"],
                    results_path=["Response_Results"],
                    all_pages=True,
                    **payload
                )
        except Exception as e:
            self._logger.error(f"Error in pagination: {e}")
            raise

        # Parse into Pydantic models
        parsed: List[Organization] = []
        for i, org in enumerate(organizations_raw):
            try:
                parsed_data = parse_organization_data(org)
                
                parsed.append(parsed_data)
            except Exception as e:
                self._logger.error(f"Error parsing organization {i+1}: {e}")
                self._logger.error(f"Raw data: {safe_serialize(org)}")
                continue

        # Convert to DataFrame
        if parsed:
            df = pd.DataFrame([org.dict() for org in parsed])
            
            # Serialize complex columns
            for col in ["external_ids", "roles", "staffing_restrictions", "leadership_reference"]:
                if col in df.columns:
                    df[col] = df[col].apply(safe_serialize)
            
            self._logger.info(f"Successfully retrieved {len(df)} organizations")
            self.service.add_metric("NUM_ORGANIZATIONS", len(parsed))
            return df
        else:
            self._logger.warning("No organizations found")
            return pd.DataFrame()

    async def get_organization_by_id(self, organization_id: str, id_type: str = "Organization_Reference_ID") -> pd.DataFrame:
        """
        Get a specific organization by ID.
        
        :param organization_id: The organization ID to fetch
        :param id_type: Type of ID (WID, Organization_Reference_ID, Cost_Center_Reference_ID, etc.)
        :return: DataFrame with organization data
        """
        return await self.execute(organization_id=organization_id, organization_id_type=id_type)

    async def get_organizations_by_type(self, organization_type: str) -> pd.DataFrame:
        """
        Get organizations filtered by type.
        
        :param organization_type: Organization type (Company, Cost Center, Custom, Matrix, Pay Group, Region, Retiree, Supervisory, etc.)
        :return: DataFrame with organizations data
        """
        return await self.execute(organization_type=organization_type)

    async def get_active_organizations(self) -> pd.DataFrame:
        """
        Get only active organizations.
        
        :return: DataFrame with active organizations data
        """
        return await self.execute(include_inactive=False)

    async def get_all_organizations(self, include_inactive: bool = True) -> pd.DataFrame:
        """
        Get all organizations (active and optionally inactive).
        
        :param include_inactive: Whether to include inactive organizations
        :return: DataFrame with all organizations data
        """
        return await self.execute(include_inactive=include_inactive)

    async def get_supervisory_organizations(self) -> pd.DataFrame:
        """
        Get only supervisory organizations.
        
        :return: DataFrame with supervisory organizations data
        """
        return await self.execute(organization_type="Supervisory")

    async def get_cost_centers(self) -> pd.DataFrame:
        """
        Get only cost center organizations.
        
        :return: DataFrame with cost center organizations data
        """
        return await self.execute(organization_type="Cost Center")

    async def get_companies(self) -> pd.DataFrame:
        """
        Get only company organizations.
        
        :return: DataFrame with company organizations data
        """
        return await self.execute(organization_type="Company")

    async def get_organization_by_wid(self, wid: str) -> pd.DataFrame:
        """
        Get a specific organization by WID.
        
        :param wid: The organization WID to fetch
        :return: DataFrame with organization data
        """
        return await self.execute(organization_id=wid, organization_id_type="WID")

    async def get_organization_by_cost_center_id(self, cost_center_id: str) -> pd.DataFrame:
        """
        Get a specific organization by Cost Center Reference ID.
        
        :param cost_center_id: The organization Cost Center Reference ID to fetch
        :return: DataFrame with organization data
        """
        return await self.execute(organization_id=cost_center_id, organization_id_type="Cost_Center_Reference_ID") 
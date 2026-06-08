"""
Type handler for Workday Extract Time Blocks Navigator Custom Report.
"""
import pandas as pd
from urllib.parse import quote

from .base import WorkdayTypeBase
from ..utils import safe_serialize
from parrot.interfaces.http import HTTPService
from parrot.conf import WORKDAY_DEFAULT_TENANT, WORKDAY_REPORT_OWNER


class TimeBlockReportType(WorkdayTypeBase):
    """Handler for the Extract Time Blocks Navigator custom report."""

    def __init__(self, component):
        super().__init__(component)
        # Initialize HTTP client for REST API access
        self._http_client = None

    def _get_rest_url(self, report_name: str, params: dict = None) -> str:
        """
        Build the REST API URL for the custom report.

        URL pattern: https://services1.wd501.myworkday.com/ccx/service/customreport2/<tenant>/<owner>/<report_name>

        Args:
            report_name: Name of the report (e.g., "Extract_Time_Blocks_-_Navigator")
            params: Query parameters to include in the URL

        Returns:
            Full URL for the REST API request
        """
        # Get tenant and report owner from component config
        tenant = getattr(self.service, 'tenant', None) or WORKDAY_DEFAULT_TENANT
        report_owner = getattr(self.service, 'report_owner', None) or WORKDAY_REPORT_OWNER

        # Base URL for Workday instance
        workday_url = getattr(
            self.service,
            'workday_url',
            'https://services1.wd501.myworkday.com'
        )

        # Construct the URL
        # RaaS endpoint pattern: /ccx/service/customreport2/
        url = f"{workday_url}/ccx/service/customreport2/{tenant}/{report_owner}/{report_name}"

        # Add query parameters if provided
        if params:
            query_string = "&".join([f"{k}={quote(str(v))}" for k, v in params.items()])
            url = f"{url}?{query_string}"

        return url

    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Execute the Extract Time Blocks Navigator report using REST API.

        Supported parameters:
        - supervisory_organization: Supervisory organization ID (or list of IDs)
        - worker: Worker ID (or list of IDs)
        - start_date: Start date for the report (YYYY-MM-DD)
        - end_date: End date for the report (YYYY-MM-DD)

        Returns:
            DataFrame with all time block report entries
        """
        # Extract parameters
        supervisory_org = kwargs.pop("supervisory_organization", None)
        worker = kwargs.pop("worker", None)
        start_date = kwargs.pop("start_date", None)
        end_date = kwargs.pop("end_date", None)

        # Build query parameters for REST API
        # RaaS (Reports as a Service) uses query parameters for report filters
        query_params = {
            "format": "json"  # Request JSON format
        }

        # Add supervisory organization parameter
        # For REST API, we pass the first org ID directly as a query parameter
        if supervisory_org:
            if isinstance(supervisory_org, list):
                # Use the first org if multiple provided
                query_params["Supervisory_Organization"] = supervisory_org[0]
            else:
                query_params["Supervisory_Organization"] = supervisory_org

        # Add worker parameter
        if worker:
            if isinstance(worker, list):
                # Use the first worker if multiple provided
                query_params["Worker"] = worker[0]
            else:
                query_params["Worker"] = worker

        # Add date range parameters
        if start_date:
            query_params["Start_Date"] = start_date
        if end_date:
            query_params["End_Date"] = end_date

        # Build the REST URL
        report_name = "Extract_Time_Blocks_-_Navigator"
        url = self._get_rest_url(report_name, query_params)

        self._logger.info(f"Fetching custom report from: {url}")

        # Initialize HTTP client if needed
        if self._http_client is None:
            # Get credentials from component
            username = getattr(
                self.service,
                'report_username',
                None
            )
            password = getattr(
                self.service,
                'report_password',
                None
            )

            if not username or not password:
                raise ValueError(
                    "Custom report credentials not configured. "
                    "Set WORKDAY_REPORT_USERNAME and WORKDAY_REPORT_PASSWORD"
                )

            # Debug: Log credentials being used (partially masked)
            self._logger.debug(f"REST API Username: {username}")
            self._logger.debug(f"REST API Password: {password[:3]}...{password[-3:]} (len: {len(password)})")

            # Create HTTP client with Basic Auth
            self._http_client = HTTPService(
                credentials={
                    "username": username,
                    "password": password
                },
                auth_type="basic",
                accept="application/json",
                timeout=60
            )
            # Set logger for HTTP client
            self._http_client._logger = self._logger

        # Execute the REST API request
        try:
            result, error = await self._http_client.async_request(
                url=url,
                method="GET",
                accept="application/json"
            )

            if error:
                self._logger.error(f"Error fetching custom report: {error}")
                raise Exception(f"Failed to fetch custom report: {error}")

            if not result:
                self._logger.warning("Empty response from custom report")
                return pd.DataFrame()

        except Exception as exc:
            self._logger.error(f"Error executing custom report via REST: {exc}")
            raise

        # Parse the JSON response
        # RaaS returns JSON data directly with Report_Entry structure
        raw_response = []
        if isinstance(result, dict):
            # Check for Report_Data structure (similar to SOAP response)
            report_data = result.get("Report_Data", result)
            if report_data:
                report_entries = report_data.get("Report_Entry", [])
                if not isinstance(report_entries, list):
                    report_entries = [report_entries]
                raw_response = report_entries
        elif isinstance(result, list):
            # Direct list of entries
            raw_response = result

        if not raw_response:
            self._logger.warning("No report entries found in response")
            return pd.DataFrame()

        # Convert to DataFrame directly from JSON
        # Use json_normalize to automatically flatten nested structures
        df = pd.json_normalize(
            raw_response,
            sep='_',
            max_level=None  # Flatten all levels
        )

        # Handle the Related_Calculated_Time_Blocks_group array
        # This is a special case - it's an array of objects
        if 'Related_Calculated_Time_Blocks_group' in df.columns:
            # Serialize the array to JSON string for now
            # Alternative: could explode this into separate rows
            df['Related_Calculated_Time_Blocks_group'] = df['Related_Calculated_Time_Blocks_group'].apply(
                lambda x: safe_serialize(x) if isinstance(x, list) and x else None
            )

        self._logger.info(f"Retrieved {len(df)} time block entries from custom report")
        return df

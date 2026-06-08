"""
Type handler for Workday Custom Punch - Field Report.

This handler executes the Custom Punch - Field Report via SOAP to get all fields
that might not be available in the REST API response.
"""
import pandas as pd
from zeep.helpers import serialize_object

from .base import WorkdayTypeBase
from ..models.custom_punch_field_report import CustomPunchFieldReportEntry
from ..parsers.custom_punch_field_report_parsers import parse_custom_punch_field_report_data


class CustomPunchFieldReportType(WorkdayTypeBase):
    """
    Handler for the Custom Punch - Field Report.

    This report provides detailed punch/time entry information including:
    - Worker and position details
    - Punch in/out times
    - Cost center and location (default and override)
    - Calculated quantities and tags
    - Wages and rates
    """

    def _get_default_payload(self) -> dict:
        """
        Payload base for the custom report.

        Custom reports use Report_Parameters structure.
        """
        return {
            "Report_Parameters": {}
        }

    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Execute the Custom Punch - Field Report.

        Supported parameters:
        - organizations: Organization ID (or list of IDs) - optional
        - time_block_status: Time block status ID (or list of IDs) - optional
        - worker: Worker ID (or list of IDs) - optional
        - start_date: Start date for the report (YYYY-MM-DD) - required
        - end_date: End date for the report (YYYY-MM-DD) - required

        Returns:
            DataFrame with all custom punch field report entries
        """
        # Extract parameters
        organizations = kwargs.pop("organizations", None)
        time_block_status = kwargs.pop("time_block_status", None)
        worker = kwargs.pop("worker", None)
        start_date = kwargs.pop("start_date", None)
        end_date = kwargs.pop("end_date", None)

        # Validate required parameters
        if not start_date or not end_date:
            raise ValueError("start_date and end_date are required parameters")

        # Build the payload
        payload = self._get_default_payload()
        report_params = payload["Report_Parameters"]

        # Add organizations
        if organizations:
            if not isinstance(organizations, list):
                organizations = [organizations]
            report_params["Organizations"] = [
                {"ID": {"type": "Organization_Reference_ID", "_value_1": org}}
                for org in organizations
            ]

        # Add time block status
        if time_block_status:
            if not isinstance(time_block_status, list):
                time_block_status = [time_block_status]
            report_params["Time_Block_Status"] = [
                {"ID": {"type": "Time_Tracking_Set_Up_Option_ID", "_value_1": status}}
                for status in time_block_status
            ]

        # Add worker
        if worker:
            if not isinstance(worker, list):
                worker = [worker]
            report_params["Worker"] = [
                {"ID": {"type": "Employee_ID", "_value_1": wkr}}
                for wkr in worker
            ]

        # Add date range (required)
        report_params["Start_Date"] = start_date
        report_params["End_Date"] = end_date

        # Add Authentication element with Proxy_User_Name (report owner)
        # This is needed for SOAP custom reports to run in the context of the report owner
        report_owner = getattr(self.service, 'report_owner', None)
        if report_owner:
            payload["Authentication"] = {
                "Proxy_User_Name": report_owner
            }
            self._logger.info(f"Using proxy user for report execution: {report_owner}")

        # Execute SOAP request - the operation name from WSDL is "Execute_Report"
        raw_response = await self.service.call_operation(
            operation="Execute_Report",
            **payload
        )

        # Extract the report data from the response
        # The WSDL shows the response structure is Report_Data -> Report_Entry (list)
        data = serialize_object(raw_response)

        # Navigate to Report_Entry list
        report_entries = []
        if isinstance(data, dict) and "Report_Entry" in data:
            entries = data["Report_Entry"]
            if isinstance(entries, list):
                report_entries = entries
            elif entries:  # Single entry
                report_entries = [entries]

        # Parse the raw report data
        parsed_data = parse_custom_punch_field_report_data(report_entries)

        # Convert to list of model instances
        entries = [CustomPunchFieldReportEntry(**item) for item in parsed_data]

        # Convert to DataFrame
        if entries:
            df = pd.json_normalize(
                [entry.model_dump() for entry in entries],
                sep='_',
                max_level=2
            )
        else:
            # Return empty DataFrame with expected columns if no data
            df = pd.DataFrame()

        self._logger.info(f"Retrieved {len(df)} custom punch field entries from SOAP report")
        return df

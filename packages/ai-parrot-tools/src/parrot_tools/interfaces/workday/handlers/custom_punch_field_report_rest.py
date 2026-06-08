"""
REST handler for the Custom Punch - Field Report (RaaS).

Uses the Workday customreport2 endpoint (basic auth) and returns a flattened
DataFrame from the XML response.
"""
from typing import Optional, Dict, Any
import pandas as pd
from urllib.parse import urlencode
import xmltodict

from .base import WorkdayTypeBase
from ..models.custom_punch_field_report import CustomPunchFieldReportEntry
from ..parsers.custom_punch_field_report_parsers import parse_custom_punch_field_report_data
from parrot.interfaces.http import HTTPService
from parrot.conf import WORKDAY_DEFAULT_TENANT, WORKDAY_REPORT_OWNER


class CustomPunchFieldReportRestType(WorkdayTypeBase):
    """
    Fetch the Custom Punch - Field Report via REST (customreport2).

    Required params:
    - start_date: Start date (YYYY-MM-DD or YYYY-MM-DD-HH:MM)
    - end_date:   End date   (same format as start)

    Optional params: organizations, time_block_status, worker (passed through
    as query params if provided).
    """

    def __init__(self, component):
        super().__init__(component)
        self._http_client = None

    def _build_url(
        self,
        query_params: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Build the customreport2 URL for this report.
        """
        tenant = getattr(self.service, 'tenant', None) or WORKDAY_DEFAULT_TENANT
        owner = getattr(self.service, 'report_owner', None) or WORKDAY_REPORT_OWNER
        workday_url = getattr(
            self.service,
            'workday_url',
            'https://services1.wd501.myworkday.com'
        )

        base_url = (
            f"{workday_url}/ccx/service/customreport2/"
            f"{tenant}/{owner}/Custom_Punch_-_Field_Report_-_Nav"
        )

        if query_params:
            query_string = urlencode(query_params, safe='@')
            return f"{base_url}?{query_string}"
        return base_url

    async def execute(self, save_raw_response_path: Optional[str] = None, **query_params) -> pd.DataFrame:
        """
        Execute the REST custom report and return a DataFrame.
        If save_raw_response_path is provided, the raw XML response is written there.
        """
        # Allow passing save_raw_response_path via component attribute if not provided
        if not save_raw_response_path and hasattr(self.service, "save_raw_response_path"):
            save_raw_response_path = getattr(self.service, "save_raw_response_path")
        # Filter out internal params
        internal_params = {
            'use_basic_auth', 'report_owner', 'report_username', 'report_password',
            'auth_type', 'wsdl_path', 'client_id', 'client_secret', 'token_url',
            'refresh_token', 'tenant', 'workday_url', 'save_raw_response_path'
        }
        filtered_params = {
            k: v for k, v in query_params.items()
            if k not in internal_params and v is not None
        }

        # Build URL
        url = self._build_url(filtered_params)
        self._logger.info("Executing Custom Punch Field Report via REST")
        self._logger.debug(f"REST URL: {url}")

        # Init HTTP client if needed
        if self._http_client is None:
            username = getattr(self.service, 'report_username', None)
            password = getattr(self.service, 'report_password', None)
            if not username or not password:
                raise ValueError(
                    "Custom report credentials not configured. "
                    "Set WORKDAY_REPORT_USERNAME and WORKDAY_REPORT_PASSWORD"
                )
            self._http_client = HTTPService(
                credentials={"username": username, "password": password},
                auth_type="basic",
                accept="application/xml",
                timeout=120
            )
            self._http_client._logger = self._logger

        # Call endpoint
        result, error = await self._http_client.async_request(
            url=url,
            method="GET",
            accept="application/xml"
        )
        if error:
            raise Exception(f"Failed to fetch custom punch field report: {error}")
        if not result:
            self._logger.warning("Empty response from custom punch field report (REST)")
            return pd.DataFrame()

        # Parse XML into DataFrame
        data_bytes = result if isinstance(result, (bytes, bytearray)) else str(result).encode()

        # Optionally save raw XML for debugging/comparison
        if save_raw_response_path:
            try:
                from pathlib import Path
                raw_path = Path(save_raw_response_path)
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(data_bytes)
                self._logger.info(f"Saved raw XML response to {raw_path}")
            except Exception as exc:
                self._logger.warning(f"Could not save raw XML response to {save_raw_response_path}: {exc}")

        # Parse XML to dict, strip namespace prefixes, reuse existing parser
        def _strip_prefix(obj):
            if isinstance(obj, dict):
                new = {}
                for k, v in obj.items():
                    key = k.split(":")[-1] if ":" in k else k
                    new[key] = _strip_prefix(v)
                return new
            if isinstance(obj, list):
                return [_strip_prefix(i) for i in obj]
            return obj

        try:
            parsed_xml = xmltodict.parse(
                data_bytes,
                process_namespaces=False,
                attr_prefix="",
                cdata_key="_value",
            )
            parsed_xml = _strip_prefix(parsed_xml)
            report_data = parsed_xml.get("Envelope", {}).get("Body", {}).get("Report_Data") \
                or parsed_xml.get("Report_Data") \
                or parsed_xml.get("Report") \
                or parsed_xml.get("wd:Report_Data") \
                or parsed_xml.get("wd:Report")
            entries = []
            if isinstance(report_data, dict):
                entries = report_data.get("Report_Entry", [])
            if entries and not isinstance(entries, list):
                entries = [entries]
        except Exception as exc:
            self._logger.error(f"Error parsing XML response: {exc}")
            raise

        if not entries:
            self._logger.warning("No report entries found in REST XML response")
            return pd.DataFrame()

        parsed_data = parse_custom_punch_field_report_data(entries)
        entry_models = [CustomPunchFieldReportEntry(**item) for item in parsed_data]

        df = pd.json_normalize(
            [m.model_dump() for m in entry_models],
            sep="_",
            max_level=2
        ) if entry_models else pd.DataFrame()

        self._logger.info(f"Retrieved {len(df)} entries from REST custom punch report")
        return df

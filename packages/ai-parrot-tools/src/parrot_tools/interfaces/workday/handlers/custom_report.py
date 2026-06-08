"""
Generic type handler for Workday RaaS (Reports as a Service) custom reports.

This handler can execute ANY Workday custom report without requiring
specific type implementations. It uses dynamic parameter passing and
automatic DataFrame generation from XML responses with dynamic parsing.
"""
from collections import defaultdict
from typing import Optional, Dict, Any, List
import pandas as pd
from urllib.parse import urlencode
import xmltodict

from .base import WorkdayTypeBase
from ..utils import safe_serialize
from parrot.interfaces.http import HTTPService


class CustomReportType(WorkdayTypeBase):
    """
    Generic handler for ANY Workday RaaS custom report.

    This type can execute any Workday custom report by accepting:
    - report_name: The name of the report in Workday
    - report_owner: The email/ID of the report owner (optional, uses default)
    - **query_params: Any report-specific parameters

    The handler automatically:
    - Builds the correct RaaS URL
    - Authenticates with Basic Auth
    - Converts XML response to DataFrame with dynamic parsing
    - Handles nested structures and arrays appropriately

    Example usage:
        # Time blocks report
        df = await custom_report.execute(
            report_name="Extract_Time_Blocks_-_Navigator",
            Start_Date="2025-11-17",
            End_Date="2025-11-17",
            Worker="12345"
        )

        # Different report with different parameters
        df = await custom_report.execute(
            report_name="Absence_Calendar_Report",
            Year="2025",
            Month="11"
        )
    """

    def __init__(self, component):
        super().__init__(component)
        # Initialize HTTP client for REST API access
        self._http_client = None

    def _strip_namespace_prefix(self, obj: Any) -> Any:
        """
        Recursively strip namespace prefixes from XML dict keys.

        Converts keys like 'wd:Report_Entry' to 'Report_Entry'
        """
        if isinstance(obj, dict):
            new = {}
            for k, v in obj.items():
                # Remove namespace prefix (e.g., "wd:" -> "")
                key = k.split(":")[-1] if ":" in k else k
                new[key] = self._strip_namespace_prefix(v)
            return new
        if isinstance(obj, list):
            return [self._strip_namespace_prefix(i) for i in obj]
        return obj

    def _coerce_bool(self, value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y"}
        return bool(value)

    def _coerce_bool_int(self, value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, (int, float)):
            return 1 if value else 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "y"}:
                return 1
            if lowered in {"0", "false", "no", "n"}:
                return 0
        return value

    def _list_of_dicts_to_dict(self, items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(items, list) or not items or not all(isinstance(i, dict) for i in items):
            return None

        if all("type" in i and "_value" in i for i in items):
            result: Dict[str, Any] = {}
            for item in items:
                key = str(item.get("type"))
                value = item.get("_value")
                if key in result:
                    existing = result[key]
                    if isinstance(existing, list):
                        existing.append(value)
                    else:
                        result[key] = [existing, value]
                else:
                    result[key] = value
            return result

        if all("Descriptor" in i for i in items):
            result = {}
            descriptors = [i.get("Descriptor") for i in items if i.get("Descriptor") is not None]
            if descriptors:
                result["Descriptor"] = descriptors[0] if len(descriptors) == 1 else descriptors
            ids_by_type: Dict[str, List[Any]] = {}
            for item in items:
                ids = item.get("ID")
                if isinstance(ids, list):
                    for id_item in ids:
                        if isinstance(id_item, dict) and "type" in id_item and "_value" in id_item:
                            key = str(id_item.get("type"))
                            ids_by_type.setdefault(key, []).append(id_item.get("_value"))
                elif isinstance(ids, dict) and "type" in ids and "_value" in ids:
                    key = str(ids.get("type"))
                    ids_by_type.setdefault(key, []).append(ids.get("_value"))
            for key, values in ids_by_type.items():
                result[f"ID_{key}"] = values[0] if len(values) == 1 else values
            return result or None

        return None

    def _expand_list_dict_columns(self, df: pd.DataFrame, drop_original: bool) -> pd.DataFrame:
        expanded_frames = []
        drop_cols = []

        for col in df.columns:
            if df[col].dtype != 'object':
                continue
            non_null = df[col].dropna()
            sample = non_null.iloc[0] if not non_null.empty else None
            if not isinstance(sample, list):
                continue
            converted = df[col].apply(
                lambda x: self._list_of_dicts_to_dict(x) if isinstance(x, list) else None
            )
            if converted.dropna().empty:
                continue
            expanded = pd.json_normalize(converted).set_index(converted.index)
            expanded = expanded.add_prefix(f"{col}_")
            expanded_frames.append(expanded)
            if drop_original:
                drop_cols.append(col)

        if not expanded_frames:
            return df

        base_df = df.drop(columns=drop_cols) if drop_cols else df
        return pd.concat([base_df] + expanded_frames, axis=1)

    def _parse_xml_to_entries(self, xml_bytes: bytes) -> List[Dict[str, Any]]:
        """
        Parse XML response from Workday RaaS and extract report entries.

        Args:
            xml_bytes: Raw XML response as bytes

        Returns:
            List of dictionaries representing report entries
        """
        try:
            # Parse XML using xmltodict
            parsed_xml = xmltodict.parse(
                xml_bytes,
                process_namespaces=False,
                attr_prefix="",
                cdata_key="_value",
            )

            # Strip namespace prefixes from all keys
            parsed_xml = self._strip_namespace_prefix(parsed_xml)

            # Try to find report data in multiple possible locations
            # Workday may wrap in SOAP envelope or return directly
            report_data = (
                parsed_xml.get("Envelope", {}).get("Body", {}).get("Report_Data") or
                parsed_xml.get("Report_Data") or
                parsed_xml.get("Report") or
                parsed_xml
            )

            # Extract Report_Entry elements
            entries = []
            if isinstance(report_data, dict):
                entries = report_data.get("Report_Entry", [])
            elif isinstance(report_data, list):
                entries = report_data

            # Ensure entries is a list
            if entries and not isinstance(entries, list):
                entries = [entries]

            return entries

        except Exception as e:
            self._logger.error(f"Error parsing XML response: {e}")
            raise

    def _build_raas_url(
        self,
        report_name: str,
        report_owner: Optional[str] = None,
        query_params: Optional[Dict[str, Any]] = None,
        report_path: Optional[str] = None
    ) -> str:
        """
        Build the RaaS (Reports as a Service) REST API URL.

        URL pattern:
        https://<workday-url>/ccx/service/customreport2/<tenant>/<owner>/<report_name>?<params>

        Args:
            report_name: Name of the report (e.g., "Extract_Time_Blocks_-_Navigator")
            report_owner: Email of report owner (defaults to configured owner)
            query_params: Dictionary of query parameters for the report
            report_path: Optional override for the RaaS path segment.
                Useful when the Workday path differs from the display name.

        Returns:
            Full URL for the RaaS REST API request
        """
        # Get configuration from component
        tenant = getattr(self.service, 'tenant', 'nav')
        owner = report_owner or getattr(
            self.service,
            'report_owner',
            'owner@example.com'
        )
        workday_url = getattr(
            self.service,
            'workday_url',
            'https://services1.wd501.myworkday.com'
        )

        path = report_path or report_name

        # Construct base URL
        # RaaS endpoint pattern: /ccx/service/customreport2/<tenant>/<owner>/<report_name>
        url = f"{workday_url}/ccx/service/customreport2/{tenant}/{owner}/{path}"

        # Add query parameters if provided
        if query_params:
            query_string = urlencode(query_params, safe='@')
            url = f"{url}?{query_string}"

        return url

    async def execute(
        self,
        report_name: str,
        report_owner: Optional[str] = None,
        **query_params
    ) -> pd.DataFrame:
        """
        Execute any Workday RaaS custom report.

        This method accepts the report name and any report-specific parameters.
        It automatically handles authentication, request execution, and
        DataFrame conversion.

        Args:
            report_name: Name of the report in Workday (required)
            report_owner: Email/ID of report owner (optional, uses default from config)
            **query_params: Any report-specific parameters (e.g., Start_Date, Worker, etc.)
                Special flags:
                - query_string_template: str template for custom query parameters with placeholders.
                  Example: "Organization!WID={org_wid}&To_Date={end_date}&From_Date={start_date}"
                  Placeholders like {org_wid} will be replaced with the corresponding parameter values.
                - offer_and_hire: bool to map start/end dates to Ready for Hire fields and adjust path.
                - report_path: str to override the RaaS path when it differs from the display name.
                - flatten_list_dicts: bool to expand list-of-dict columns into flat columns.
                - drop_flattened_columns: bool to drop the original list columns after expansion.
                - supervisory_organizations: bool flag to map supervisory org params.
                - supervisory_organizations_wid: WID value for Supervisory_Organizations!WID.
                - supervisory_organization_wid: alias for supervisory_organizations_wid.
                - include_subordinate_organizations: bool/int for Include_Subordinate_Organizations.

        Returns:
            DataFrame with automatic column detection from JSON response

        Example:
            # Standard usage with automatic URL encoding
            df = await custom_report.execute(
                report_name="Extract_Time_Blocks_-_Navigator",
                Start_Date="2025-11-17",
                End_Date="2025-11-17",
                Worker="12345"
            )

            # Using query_string_template for custom parameter formats
            df = await custom_report.execute(
                report_name="TROC_New_Hire_Employment_-_Finance",
                report_owner="owner@example.com",
                query_string_template="Organization!WID={org_wid}&To_Date={end_date}&From_Date={start_date}&Include_Subordinate_Organizations={include_subordinate}",
                org_wid="795b89c2031c1000da0e4900aa460000",
                start_date="2025-11-01-07:00",
                end_date="2025-11-30-08:00",
                include_subordinate=1
            )
        """
        # Filter out internal parameters that shouldn't be sent to Workday
        internal_params = {
            'use_basic_auth', 'report_owner', 'report_username', 'report_password',
            'auth_type', 'wsdl_path', 'client_id', 'client_secret', 'token_url',
            'refresh_token', 'tenant', 'workday_url', 'offer_and_hire', 'report_path',
            'flatten_list_dicts', 'drop_flattened_columns',
            'supervisory_organizations', 'supervisory_organizations_wid',
            'supervisory_organization_wid', 'include_subordinate_organizations',
            'query_string_template'
        }

        offer_and_hire = self._coerce_bool(query_params.pop('offer_and_hire', False))
        flatten_list_dicts = self._coerce_bool(query_params.pop('flatten_list_dicts', False))
        drop_flattened_columns = self._coerce_bool(query_params.pop('drop_flattened_columns', False))
        report_path = query_params.pop('report_path', None)
        query_string_template = query_params.pop('query_string_template', None)

        supervisory_org_value = query_params.pop('supervisory_organizations', False)
        supervisory_org_flag = False
        supervisory_wid = None
        if isinstance(supervisory_org_value, str):
            lowered = supervisory_org_value.strip().lower()
            if lowered in {"1", "true", "yes", "y", "0", "false", "no", "n"}:
                supervisory_org_flag = lowered in {"1", "true", "yes", "y"}
            else:
                supervisory_org_flag = True
                supervisory_wid = supervisory_org_value
        elif isinstance(supervisory_org_value, bool):
            supervisory_org_flag = supervisory_org_value
        elif supervisory_org_value:
            supervisory_org_flag = True
            supervisory_wid = supervisory_org_value

        supervisory_wid = (
            query_params.pop('supervisory_organizations_wid', None)
            or query_params.pop('supervisory_organization_wid', None)
            or supervisory_wid
        )
        include_subordinate = query_params.pop('include_subordinate_organizations', None)
        include_subordinate = self._coerce_bool_int(include_subordinate)

        # Only pass Workday-specific parameters to the RaaS URL
        filtered_params = {
            k: v for k, v in query_params.items()
            if k not in internal_params
        }

        if offer_and_hire:
            self._logger.debug(
                "offer_and_hire flag enabled: mapping start/end to Ready for Hire fields and adjusting path"
            )
            start_value = filtered_params.pop('start_date', None)
            start_value = start_value if start_value is not None else filtered_params.pop('Start_Date', None)
            end_value = filtered_params.pop('end_date', None)
            end_value = end_value if end_value is not None else filtered_params.pop('End_Date', None)

            if start_value is not None and "Starting_Ready_for_Hire_Completed_Date" not in filtered_params:
                filtered_params["Starting_Ready_for_Hire_Completed_Date"] = start_value
            if end_value is not None and "Ending_Ready_for_Hire_Completed_Date" not in filtered_params:
                filtered_params["Ending_Ready_for_Hire_Completed_Date"] = end_value

            if report_path is None and report_name == "Offers & Hires V1.3 - Nav":
                # Use known slug for this report when not provided
                report_path = "Offers___Hires_V1.3_-_Nav"

        if supervisory_org_flag:
            self._logger.debug(
                "supervisory_organizations flag enabled: mapping supervisory org params"
            )
            if supervisory_wid is None:
                self._logger.warning(
                    "supervisory_organizations flag enabled but no WID provided"
                )
            if supervisory_wid is not None and "Supervisory_Organizations!WID" not in filtered_params:
                filtered_params["Supervisory_Organizations!WID"] = supervisory_wid
            if include_subordinate is None:
                include_subordinate = 1
            if include_subordinate is not None and "Include_Subordinate_Organizations" not in filtered_params:
                filtered_params["Include_Subordinate_Organizations"] = include_subordinate

        # Build the RaaS URL with filtered parameters or template
        if query_string_template:
            # Use custom query string template with placeholder replacement
            self._logger.debug(f"Using query_string_template: {query_string_template}")

            # Replace placeholders in template with actual values
            query_string = query_string_template
            for key, value in filtered_params.items():
                placeholder = f"{{{key}}}"
                if placeholder in query_string:
                    query_string = query_string.replace(placeholder, str(value))

            # Check for unreplaced placeholders and warn
            import re
            unreplaced = re.findall(r'\{([^}]+)\}', query_string)
            if unreplaced:
                self._logger.warning(
                    f"Unreplaced placeholders in query_string_template: {unreplaced}"
                )

            # Build base URL without query params, then append template
            base_url = self._build_raas_url(report_name, report_owner, None, report_path)
            url = f"{base_url}?{query_string}"
        else:
            # Use standard URL building with filtered_params
            url = self._build_raas_url(report_name, report_owner, filtered_params, report_path)

        self._logger.info(f"Executing custom report: {report_name}")
        self._logger.debug(f"RaaS URL: {url}")

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

            # Create HTTP client with Basic Auth
            self._http_client = HTTPService(
                credentials={
                    "username": username,
                    "password": password
                },
                auth_type="basic",
                accept="application/xml",
                timeout=120
            )
            # Set logger for HTTP client
            self._http_client._logger = self._logger

        # Execute the REST API request
        try:
            result, error = await self._http_client.async_request(
                url=url,
                method="GET",
                accept="application/xml"
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

        # Parse the XML response
        # Convert to bytes for xmltodict
        xml_bytes = result if isinstance(result, (bytes, bytearray)) else str(result).encode()

        # Parse XML to list of dicts
        raw_response = self._parse_xml_to_entries(xml_bytes)

        if not raw_response:
            self._logger.warning("No report entries found in XML response")
            return pd.DataFrame()

        # Convert parsed XML (now as list of dicts) to DataFrame
        # Use json_normalize to automatically flatten nested structures
        df = pd.json_normalize(
            raw_response,
            sep='_',
            max_level=None  # Flatten all levels
        )

        if flatten_list_dicts:
            df = self._expand_list_dict_columns(df, drop_flattened_columns)

        # Ensure unique column names by adding numeric suffixes to duplicates.
        if df.columns.duplicated().any():
            counts = defaultdict(int)
            new_cols = []
            for col in df.columns:
                counts[col] += 1
                if counts[col] == 1:
                    new_cols.append(col)
                else:
                    new_cols.append(f"{col}_{counts[col] - 1}")
            df.columns = new_cols

        # Handle array fields that couldn't be flattened
        # These will be serialized to JSON strings for DataFrame compatibility
        for idx, col in enumerate(df.columns):
            series = df.iloc[:, idx]
            if series.dtype == 'object':
                # Check if column contains lists of dicts (complex nested structures)
                non_null = series.dropna()
                sample = non_null.iloc[0] if not non_null.empty else None
                if isinstance(sample, list):
                    # Serialize arrays to JSON strings
                    df.iloc[:, idx] = series.apply(
                        lambda x: safe_serialize(x) if isinstance(x, list) else x
                    )

        self._logger.info(
            f"Retrieved {len(df)} entries from custom report '{report_name}' "
            f"with {len(df.columns)} columns"
        )

        return df

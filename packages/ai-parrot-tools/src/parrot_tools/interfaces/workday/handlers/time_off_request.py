"""RequestTimeOffType — handler for Request_Time_Off.

Builds the SOAP request body for submitting a time-off request to Workday
Absence Management and parses the acknowledgment into a one-row status
DataFrame.

SOAP body shapes (Absence Management WSDL, Request_Time_Off operation):
- Time_Off_Request_Data.Worker_Reference        → Employee_ID reference
- Time_Off_Request_Data.Time_Off_Request_Line_Data[] →
    Time_Off_Type_Reference, Start_Date, End_Date, Daily_Quantity
- Optional Comment field at the request level.

Acknowledgment:
- Request_Time_Off_Response → contains the submitted request WID/ID.
- zeep raises a Validation_Fault/Processing_Fault on SOAP errors before this
  point, so arriving here means the submission was accepted.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd
from zeep.helpers import serialize_object

from parrot_tools.interfaces.workday.handlers.base import WorkdayWriteTypeBase


class RequestTimeOffType(WorkdayWriteTypeBase):
    """Handler for ``Request_Time_Off`` (Absence Management write op)."""

    def _operation_name(self) -> str:
        return "Request_Time_Off"

    def build_request(
        self,
        worker_id: str,
        start_date: str,
        end_date: str,
        time_off_type: str,
        daily_quantity: float = 8.0,
        comment: Optional[str] = None,
        **kwargs: Any,
    ) -> dict:
        """Build the Request_Time_Off SOAP body.

        Args:
            worker_id: Workday Employee ID.
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            time_off_type: Time_Off_Type_ID value (e.g. "PTO").
            daily_quantity: Hours or days per calendar day (default 8.0).
            comment: Optional employee comment on the request.

        Returns:
            Dict ready to be unpacked as kwargs for ``call_operation``.
        """
        line_data: dict[str, Any] = {
            "Time_Off_Type_Reference": {
                "ID": [{"type": "Time_Off_Type_ID", "_value_1": time_off_type}]
            },
            "Start_Date": start_date,
            "End_Date": end_date,
            "Daily_Quantity": daily_quantity,
        }
        request_data: dict[str, Any] = {
            "Worker_Reference": {
                "ID": [{"type": "Employee_ID", "_value_1": worker_id}]
            },
            "Time_Off_Request_Line_Data": [line_data],
        }
        if comment:
            request_data["Comment"] = comment
        return {"Time_Off_Request_Data": request_data}

    def parse_ack(self, raw: Any) -> pd.DataFrame:
        """Parse Request_Time_Off_Response into a one-row status DataFrame.

        Args:
            raw: Raw Zeep response object.

        Returns:
            DataFrame with columns: submitted, event_id, error.
        """
        event_id: Optional[str] = None
        if raw:
            try:
                serialized = serialize_object(raw)
                event_id = str(serialized) if serialized else None
            except Exception:
                pass
        return pd.DataFrame([{"submitted": True, "event_id": event_id, "error": None}])

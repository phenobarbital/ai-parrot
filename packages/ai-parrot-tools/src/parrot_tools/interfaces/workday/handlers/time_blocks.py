from typing import List, Optional
import pandas as pd
from datetime import datetime

from .base import WorkdayTypeBase
from ..models import TimeBlock
from ..parsers import parse_time_block_data
from ..utils import safe_serialize


class TimeBlockType(WorkdayTypeBase):
    """Handler for the Workday Get_Calculated_Time_Blocks operation."""

    def _get_default_payload(self) -> dict:
        """
        Payload base específico para time blocks.
        """
        return {
            "Response_Filter": {},
            "Response_Group": {
                "Include_Worker": True,
                "Include_Date": True,
                "Include_In_Out_Time": True,
                "Include_Calculated_Quantity": True,
                "Include_Status": True,
                "Include_Deleted": True,
                "Include_Calculation_Tags": True,
                "Include_Last_Updated": True,
                 "Include_Worktags": True,
            },
        }

    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Execute the Get_Calculated_Time_Blocks operation and return a pandas DataFrame.

        Supported parameters:
        - worker_id: Specific worker ID to fetch time blocks for
        - start_date: Start date for date range filter (YYYY-MM-DD)
        - end_date: End date for date range filter (YYYY-MM-DD)
        - time_block_id: Specific time block ID to fetch (Worker_Time_Block_ID type)
        - time_block_wid: Specific time block WID to fetch (WID type)
        - status: Filter by status
        - supervisory_org: Filter by supervisory organization
        - include_deleted: Whether to include deleted time blocks (default: True via Workday)
        """
        # Extract parameters
        worker_id = kwargs.pop("worker_id", None)
        start_date = kwargs.pop("start_date", None)
        end_date = kwargs.pop("end_date", None)
        time_block_id = kwargs.pop("time_block_id", None)
        time_block_wid = kwargs.pop("time_block_wid", None)
        status = kwargs.pop("status", None)
        supervisory_org = kwargs.pop("supervisory_org", None)
        include_deleted = kwargs.pop("include_deleted", None)

        # Build request payload
        payload = self._get_default_payload()

        # Stable snapshot timestamp for pagination
        as_of_entry = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        payload["Response_Filter"]["As_Of_Entry_DateTime"] = as_of_entry

        # Toggle Include_Deleted only when explicitly requested
        if include_deleted is not None:
            payload["Response_Group"]["Include_Deleted"] = bool(include_deleted)

        # If searching by specific time block ID, use Request_References
        if time_block_id or time_block_wid:
            ids = []
            if time_block_id:
                ids.append({"type": "Worker_Time_Block_ID", "_value_1": time_block_id})
            if time_block_wid:
                ids.append({"type": "WID", "_value_1": time_block_wid})

            payload["Request_References"] = {
                "Worker_Time_Block_Reference": [{"ID": ids}]
            }
        else:
            # Otherwise, build Request_Criteria for filtering
            request_criteria = {}

            # Date range filter (both dates are required for Request_Criteria)
            if start_date and end_date:
                request_criteria["Start_Date"] = start_date
                request_criteria["End_Date"] = end_date

            # Worker filter
            if worker_id:
                request_criteria["Worker_Reference"] = [
                    {"ID": {"type": "Employee_ID", "_value_1": worker_id}}
                ]

            # Status filter
            if status:
                request_criteria["Status_Reference"] = [
                    {"ID": {"type": "Time_Tracking_Set_Up_Option_ID", "_value_1": status}}
                ]

            # Supervisory organization filter
            if supervisory_org:
                request_criteria["Supervisory_Organization_Reference"] = [
                    {"ID": {"type": "Organization_Reference_ID", "_value_1": supervisory_org}}
                ]

            if request_criteria:
                payload["Request_Criteria"] = request_criteria

        # Keep current payload available for pagination helper
        self.request_payload = payload

        # Execute the operation with pagination

        # Always use pagination for now to avoid reference issues
        time_blocks_raw = await self._paginate_soap_operation(
            operation="Get_Calculated_Time_Blocks",
            data_path=["Response_Data", "Calculated_Time_Block"],
            results_path=["Response_Results"],
            all_pages=True,
            **payload
        )

        # Parse into Pydantic models
        parsed: List[TimeBlock] = []
        for i, tb in enumerate(time_blocks_raw):
            try:
                parsed_data = parse_time_block_data(tb)
                parsed_data["raw_data"] = tb
                time_block = TimeBlock(**parsed_data)
                parsed.append(time_block)
            except Exception as e:
                print(f"❌ DEBUG: Error parsing time block {i+1}: {e}")
                continue

        # Build DataFrame and serialize complex columns
        df = pd.DataFrame([tb.dict() for tb in parsed])
        
        # Serialize complex columns
        for col in ["calculation_tags", "worktags"]:
            if col in df.columns:
                df[col] = df[col].apply(safe_serialize)

        # Add metrics
        self.service.add_metric("NUM_TIME_BLOCKS", len(parsed))
        
        return df

    async def get_time_blocks_by_worker(self, worker_id: str, start_date: Optional[str] = None, 
                                       end_date: Optional[str] = None) -> pd.DataFrame:
        """
        Convenience method to get time blocks for a specific worker.
        """
        return await self.execute(
            worker_id=worker_id,
            start_date=start_date,
            end_date=end_date
        )

    async def get_time_blocks_by_date_range(self, start_date: str, end_date: str, 
                                           status: Optional[str] = None) -> pd.DataFrame:
        """
        Convenience method to get time blocks for a date range.
        """
        return await self.execute(
            start_date=start_date,
            end_date=end_date,
            status=status
        )

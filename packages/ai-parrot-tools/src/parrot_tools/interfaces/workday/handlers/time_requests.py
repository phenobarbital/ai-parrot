from typing import Dict, Any, List, Optional
from datetime import date, timedelta
import pandas as pd

from ..models.time_request import TimeRequest
from ..parsers.time_request_parsers import parse_time_request_data
from .base import WorkdayTypeBase


class TimeRequestType(WorkdayTypeBase):
    """
    Handles Get_Time_Requests operation for Workday Time Tracking API.
    """
    
    # No custom __init__ needed - use the base class constructor
    
    def _get_default_payload(self) -> Dict[str, Any]:
        """
        Get the default payload for Get_Time_Requests operation.
        """
        return {
            "Response_Filter": {},
        }
    
    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Execute the Get_Time_Requests operation.
        """
        # Extract parameters from kwargs
        time_request_id = kwargs.pop("time_request_id", None)
        start_date = kwargs.pop("start_date", None)
        end_date = kwargs.pop("end_date", None)
        worker_id = kwargs.pop("worker_id", None)
        supervisory_organization_id = kwargs.pop("supervisory_organization_id", None)
        
        payload = {**self.request_payload}
        
        # Build request based on provided parameters
        if time_request_id:
            # Use Request_References for specific time request ID
            payload["Request_References"] = {
                "User_Time_Request_Block_Reference": [
                    {
                        "ID": [
                            {
                                "_value_1": time_request_id,
                                "type": "User_Overtime_Request_Block_ID"
                            }
                        ]
                    }
                ]
            }
        else:
            # Use Request_Criteria for filtering - at least one criterion is required
            criteria = {}
            
            # Always include date range (required by Workday)
            if start_date and end_date:
                criteria["Start_Date"] = start_date
                criteria["End_Date"] = end_date
            else:
                # Use a default date range (last 7 days to minimize data)
                end_date_default = date.today()
                start_date_default = end_date_default - timedelta(days=7)
                criteria["Start_Date"] = start_date_default
                criteria["End_Date"] = end_date_default
            
            # Add worker filter if provided
            if worker_id:
                criteria["Worker_Reference"] = [
                    {
                        "ID": [
                            {
                                "_value_1": worker_id,
                                "type": "Employee_ID"
                            }
                        ]
                    }
                ]
            
            # Add supervisory organization filter if provided
            if supervisory_organization_id:
                criteria["Supervisory_Organization_Reference"] = [
                    {
                        "ID": [
                            {
                                "_value_1": supervisory_organization_id,
                                "type": "Organization_Reference_ID"
                            }
                        ]
                    }
                ]
            
            payload["Request_Criteria"] = criteria
        
        # Debug: Log the payload being sent
        self._logger.info(f"Get_Time_Requests payload: {payload}")
        
        # Try a simpler approach first - just get one page without pagination
        try:
            # Execute the operation with pagination
            time_requests_raw = await self._paginate_soap_operation(
                operation="Get_Time_Requests",
                data_path=["Response_Data", "Time_Request_Block"],
                results_path=["Response_Results"],
                all_pages=False,  # Just get first page
                **payload
            )
        except Exception as e:
            self._logger.error(f"Error with pagination: {e}")
            # Try direct call as fallback
            raw = await self.service.call_operation(operation="Get_Time_Requests", **payload)
            time_requests_raw = [raw] if raw else []
        
        # Parse into Pydantic models
        parsed: List[TimeRequest] = []
        for i, tr in enumerate(time_requests_raw):
            try:
                if hasattr(tr, "Time_Request_Block_Data") and tr.Time_Request_Block_Data:
                    time_request_data = tr.Time_Request_Block_Data
                    
                    # Parse the time request data
                    parsed_data = parse_time_request_data(time_request_data)
                    
                    # Create TimeRequest object
                    record = {
                        **parsed_data,
                        "raw_data": tr
                    }
                    time_request = TimeRequest(**record)
                    parsed.append(time_request)
            except Exception as e:
                self._logger.warning(f"Error parsing time request {i+1}: {e}")
                continue
        
        # Build DataFrame and serialize complex columns
        if parsed:
            df = pd.DataFrame([tr.dict() for tr in parsed])
            
            # Serialize complex columns
            for col in ["worktags"]:
                if col in df.columns:
                    df[col] = df[col].apply(lambda x: str(x) if x is not None else None)
            
            return df
        else:
            return pd.DataFrame()
    
    async def get_time_request_by_id(self, time_request_id: str) -> pd.DataFrame:
        """
        Get a specific time request by ID.
        """
        return await self.execute(time_request_id=time_request_id)
    
    async def get_time_requests_by_worker(self, worker_id: str, start_date: Optional[date] = None, end_date: Optional[date] = None) -> pd.DataFrame:
        """
        Get time requests for a specific worker within an optional date range.
        """
        return await self.execute(worker_id=worker_id, start_date=start_date, end_date=end_date)
    
    async def get_time_requests_by_organization(self, supervisory_organization_id: str, start_date: Optional[date] = None, end_date: Optional[date] = None) -> pd.DataFrame:
        """
        Get time requests for a specific organization within an optional date range.
        """
        return await self.execute(supervisory_organization_id=supervisory_organization_id, start_date=start_date, end_date=end_date)
    
    async def get_time_requests_by_date_range(self, start_date: date, end_date: date) -> pd.DataFrame:
        """
        Get all time requests within a date range.
        """
        return await self.execute(start_date=start_date, end_date=end_date)
    
    def safe_serialize(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Safely serialize the DataFrame for JSON output.
        """
        if df.empty:
            return df
        
        # Convert complex objects to strings
        for col in df.columns:
            if col in ["worktags"]:
                df[col] = df[col].apply(lambda x: str(x) if x is not None else None)
        
        return df 
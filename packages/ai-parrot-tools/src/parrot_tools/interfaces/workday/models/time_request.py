from datetime import date, time
from decimal import Decimal
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class TimeRequest(BaseModel):
    """
    Pydantic model for a Workday time request record.
    `raw_data` holds the full SOAP response dict for any extra fields.
    """
    # Basic identification
    time_request_id: Optional[str]
    worker_id: Optional[str]
    worker_name: Optional[str]
    
    # Time request details
    time_request_code_id: Optional[str]
    time_request_code_name: Optional[str]
    delete_time_request: Optional[bool]
    
    # Date and time information
    start_date: Optional[date]
    end_date: Optional[date]
    start_time: Optional[time]
    end_time: Optional[time]
    total_hours: Optional[Decimal]
    
    # Additional information
    comment: Optional[str]
    status: Optional[str]
    
    # Worktags (similar to time blocks)
    worktags: Optional[Dict[str, Any]]
    
    # Raw payload
    raw_data: Dict[str, Any] = Field(..., exclude=True)
    
    class Config:
        extra = "ignore" 
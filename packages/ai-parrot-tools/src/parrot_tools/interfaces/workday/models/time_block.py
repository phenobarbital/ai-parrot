from typing import List, Optional, Dict, Any
from decimal import Decimal
from pydantic import BaseModel, Field, validator
from datetime import date, datetime

class TimeBlock(BaseModel):
    """
    Pydantic model for a Workday calculated time block record.
    `raw_data` holds the full SOAP response dict for any extra fields.
    """
    # Basic identification
    time_block_id: Optional[str]
    time_block_wid: Optional[str]
    worker_id: Optional[str]
    worker_name: Optional[str]
    
    # Date and time information
    calculated_date: Optional[date]
    calculated_in_time: Optional[datetime]
    calculated_out_time: Optional[datetime]
    shift_date: Optional[date] = None
    
    # Quantity and calculations
    calculated_quantity: Optional[float]
    
    # Status information
    status: Optional[str]
    is_deleted: Optional[bool]
    
    # Calculation details
    calculation_tags: Optional[List[str]]
    last_updated: Optional[datetime]
    
    # Worktags (additional categorization)
    worktags: Optional[Dict[str, Any]]
    
    # Raw payload
    raw_data: Dict[str, Any] = Field(..., exclude=True)

    @validator("*", pre=True)
    def _convert_decimal(cls, v):
        if isinstance(v, Decimal):
            return float(v)
        return v

    class Config:
        extra = "ignore"

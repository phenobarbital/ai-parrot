from typing import Optional, Dict, Any
from decimal import Decimal
from pydantic import BaseModel, Field, validator


class TimeOffBalance(BaseModel):
    """
    Pydantic model for a Workday Time Off Plan Balance record.
    Represents the CURRENT balance information for a worker's time off plan.

    Note: This model only includes fields actually returned by the
    Get_Time_Off_Plan_Balances API operation per the v45.0 documentation.
    """
    # Worker identification (from Employee_Reference)
    worker_id: Optional[str] = None
    worker_name: Optional[str] = None

    # Time Off Plan identification (from Time_Off_Plan_Reference)
    time_off_plan_id: Optional[str] = None
    time_off_plan_name: Optional[str] = None

    # Balance information (from Time_Off_Plan_Balance_Position_Record)
    balance: Optional[float] = None
    unit_of_time: Optional[str] = None  # Hours, Days, etc.

    # Worker position (from Position_Reference - optional field)
    position_id: Optional[str] = None
    position_title: Optional[str] = None

    # Raw payload for debugging
    raw_data: Dict[str, Any] = Field(default_factory=dict, exclude=True)

    @validator("*", pre=True)
    def _convert_decimal(cls, v):
        """Convert Decimal values to float"""
        if isinstance(v, Decimal):
            return float(v)
        return v

    class Config:
        extra = "ignore"

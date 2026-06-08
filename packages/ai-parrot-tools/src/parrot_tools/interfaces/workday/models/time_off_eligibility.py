from typing import Optional
from pydantic import BaseModel


class TimeOffEligibility(BaseModel):
    """Pydantic model for a Workday eligible time-off type.

    Represents one time-off type a worker is eligible to request,
    as returned by ``Get_Time_Off_Types`` (Absence Management WSDL).
    """

    time_off_type_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    unit: Optional[str] = None

    class Config:
        extra = "ignore"

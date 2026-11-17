from typing import Optional
from pydantic import BaseModel, ConfigDict


class WorkdayReference(BaseModel):
    """Single Reference instance returned by Workday Get_References."""

    reference_type: Optional[str] = None
    reference_id_type: Optional[str] = None
    reference_id: Optional[str] = None
    wid: Optional[str] = None
    descriptor: Optional[str] = None

    model_config = ConfigDict(
        extra="allow",
    )

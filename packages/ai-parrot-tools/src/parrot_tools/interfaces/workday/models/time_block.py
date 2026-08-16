from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, validator


class TimeBlock(BaseModel):
    """
    Pydantic model for a Workday calculated time block record.
    `raw_data` holds the full SOAP response dict for any extra fields.
    """
    # Basic identification
    # NOTE: every field below is genuinely optional — Workday omits many of them
    # depending on the worker/time-block (e.g. unprocessed clock events, or
    # tenants that don't populate is_deleted). In Pydantic v2 ``Optional[X]``
    # WITHOUT a default is still REQUIRED, so each carries ``= None`` to stay
    # tolerant of partial responses (only ``raw_data`` is mandatory).
    time_block_id: str | None = None
    time_block_wid: str | None = None
    worker_id: str | None = None
    worker_name: str | None = None

    # Date and time information
    calculated_date: date | None = None
    calculated_in_time: datetime | None = None
    calculated_out_time: datetime | None = None
    shift_date: date | None = None

    # Quantity and calculations
    calculated_quantity: float | None = None

    # Status information
    status: str | None = None
    is_deleted: bool | None = None

    # Calculation details
    calculation_tags: list[str] | None = None
    last_updated: datetime | None = None

    # Worktags (additional categorization)
    worktags: dict[str, Any] | None = None

    # Raw payload
    raw_data: dict[str, Any] = Field(..., exclude=True)

    @validator("*", pre=True)
    def _convert_decimal(cls, v):
        if isinstance(v, Decimal):
            return float(v)
        return v

    class Config:
        extra = "ignore"

"""
Pydantic models for Workday Custom Punch - Field Report.

This report provides detailed punch/time entry information with calculated fields,
wages, and override information.
"""
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import date


class WorkerGroup(BaseModel):
    """Worker group information containing employee details."""
    employee_id: Optional[str] = None
    worker_status: Optional[str] = None
    pay_rate: Optional[float] = None


class CustomPunchFieldReportEntry(BaseModel):
    """
    Model for a single entry in the Custom Punch - Field Report.

    This report includes time block information, worker details, punch times,
    calculated quantities, and wage information.
    """
    # Time Block reference
    time_block_id: Optional[str] = None
    time_block_name: Optional[str] = None

    # Reference ID
    reference_id: Optional[str] = None

    # Worker reference
    worker_id: Optional[str] = None
    worker_name: Optional[str] = None

    # Worker group data (nested)
    worker_group: Optional[WorkerGroup] = None

    # Position reference
    primary_position_id: Optional[str] = None
    primary_position_name: Optional[str] = None

    # Cost Center references
    default_cost_center_id: Optional[str] = None
    default_cost_center_name: Optional[str] = None
    override_cost_center_id: Optional[str] = None
    override_cost_center_name: Optional[str] = None

    # Location references
    default_location_id: Optional[str] = None
    default_location_name: Optional[str] = None
    override_location_id: Optional[str] = None
    override_location_name: Optional[str] = None

    # Date and time information
    reported_date: Optional[date] = None
    in_time: Optional[str] = None
    out_time: Optional[str] = None

    # Time Entry Code reference
    time_entry_code_id: Optional[str] = None
    time_entry_code_name: Optional[str] = None

    # Calculated Tags (can be multiple)
    calculated_tag_ids: List[str] = Field(default_factory=list)
    calculated_tag_names: List[str] = Field(default_factory=list)

    # Units reference
    units_id: Optional[str] = None
    units_name: Optional[str] = None

    # Calculated quantities and rates
    calculated_quantity: Optional[float] = None
    override_rate: Optional[float] = None
    test_override_rate: Optional[float] = None  # XMLNAME__TEST__Override_Rate
    total_wages: Optional[float] = None

    # Raw payload for debugging
    raw_data: dict = Field(default_factory=dict, exclude=True)

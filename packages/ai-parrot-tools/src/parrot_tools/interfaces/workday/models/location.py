from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import date

class Location(BaseModel):
    """
    Pydantic model for a Workday location record.
    `raw_data` holds the full SOAP response dict for any extra fields.
    """
    # Basic identification
    location_id: Optional[str] = None
    location_name: Optional[str] = None

    # Status and dates
    effective_date: Optional[date] = None
    inactive: Optional[bool] = None

    # Location details
    location_type: Optional[str] = None
    location_usage: Optional[List[str]] = None
    location_attributes: Optional[List[str]] = None

    # Hierarchy
    superior_location_id: Optional[str] = None
    superior_location_name: Optional[str] = None

    # Address and coordinates
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    allow_duplicate_coordinates: Optional[bool] = None

    # Address information
    formatted_address: Optional[str] = None
    address_line_1: Optional[str] = None
    municipality: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    country_region: Optional[str] = None

    # Additional fields
    time_profile: Optional[str] = None
    locale: Optional[str] = None
    user_language: Optional[str] = None
    time_zone: Optional[str] = None
    currency: Optional[str] = None
    trade_name: Optional[str] = None
    worksite_id: Optional[str] = None
    default_job_posting_location: Optional[str] = None
    location_hierarchy: Optional[List[str]] = None

    # Raw payload
    raw_data: Dict[str, Any] = Field(..., exclude=True)

    class Config:
        extra = "ignore" 
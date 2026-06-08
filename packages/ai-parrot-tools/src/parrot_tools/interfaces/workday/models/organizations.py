from typing import List, Optional, Union
from pydantic import BaseModel, validator


class Organization(BaseModel):
    """Complete organization model based on actual Workday payload."""
    
    # Organization Reference
    organization_id: Optional[str] = None
    organization_name: Optional[str] = None
    organization_code: Optional[str] = None
    organization_type: Optional[str] = None
    organization_subtype: Optional[str] = None
    
    # Core Organization Data
    reference_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    organization_code_data: Optional[str] = None
    include_manager_in_name: Optional[Union[bool, str]] = None
    include_organization_code_in_name: Optional[Union[bool, str]] = None
    
    # Type and Subtype References
    organization_type_id: Optional[str] = None
    organization_subtype_id: Optional[str] = None
    
    # Dates
    availability_date: Optional[str] = None  # Keep as string for now
    last_updated_datetime: Optional[str] = None  # Keep as string for now
    inactive_date: Optional[str] = None  # Keep as string for now
    
    # Status
    inactive: Optional[Union[bool, str]] = None
    
    # Manager Information (not present in basic response)
    manager_reference: Optional[str] = None
    manager_name: Optional[str] = None
    manager_id: Optional[str] = None
    
    # Hierarchy Data (not present in basic response)
    parent_organization_id: Optional[str] = None
    parent_organization_name: Optional[str] = None
    hierarchy_level: Optional[str] = None
    is_top_level: Optional[Union[bool, str]] = None
    
    # Supervisory Data (not present in basic response)
    staffing_model: Optional[str] = None
    location_reference: Optional[str] = None
    staffing_restrictions: Optional[List[str]] = None
    available_for_hire: Optional[Union[bool, str]] = None
    hiring_freeze: Optional[Union[bool, str]] = None
    
    # Roles Data (not present in basic response)
    roles: Optional[List[str]] = None
    
    # External IDs
    external_ids: Optional[List[str]] = None
    
    # Leadership and Owner References (not present in basic response)
    leadership_reference: Optional[List[str]] = None
    organization_owner_reference: Optional[str] = None
    organization_visibility_reference: Optional[str] = None
    external_url_reference: Optional[str] = None

    @validator('inactive', 'is_top_level', 'include_manager_in_name', 'include_organization_code_in_name', 
               'available_for_hire', 'hiring_freeze', pre=True)
    def validate_boolean_fields(cls, v):
        if isinstance(v, str):
            return v.lower() == 'true' or v == "1"
        return bool(v) if v is not None else False

    @validator('availability_date', 'last_updated_datetime', 'inactive_date', pre=True)
    def validate_dates(cls, v):
        # Keep dates as strings for now to avoid parsing issues
        if isinstance(v, str) and v and v != "1900-01-01T00:00:00.000-08:00":
            return v
        return v

    class Config:
        arbitrary_types_allowed = True 
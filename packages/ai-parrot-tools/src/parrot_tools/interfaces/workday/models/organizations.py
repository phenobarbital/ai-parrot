
from pydantic import BaseModel, validator


class Organization(BaseModel):
    """Complete organization model based on actual Workday payload."""
    
    # Organization Reference
    organization_id: str | None = None
    organization_name: str | None = None
    organization_code: str | None = None
    organization_type: str | None = None
    organization_subtype: str | None = None
    
    # Core Organization Data
    reference_id: str | None = None
    name: str | None = None
    description: str | None = None
    organization_code_data: str | None = None
    include_manager_in_name: bool | str | None = None
    include_organization_code_in_name: bool | str | None = None
    
    # Type and Subtype References
    organization_type_id: str | None = None
    organization_subtype_id: str | None = None
    
    # Dates
    availability_date: str | None = None  # Keep as string for now
    last_updated_datetime: str | None = None  # Keep as string for now
    inactive_date: str | None = None  # Keep as string for now
    
    # Status
    inactive: bool | str | None = None
    
    # Manager Information (not present in basic response)
    manager_reference: str | None = None
    manager_name: str | None = None
    manager_id: str | None = None
    
    # Hierarchy Data (not present in basic response)
    parent_organization_id: str | None = None
    parent_organization_name: str | None = None
    hierarchy_level: str | None = None
    is_top_level: bool | str | None = None
    
    # Supervisory Data (not present in basic response)
    staffing_model: str | None = None
    location_reference: str | None = None
    staffing_restrictions: list[str] | None = None
    available_for_hire: bool | str | None = None
    hiring_freeze: bool | str | None = None
    
    # Roles Data (not present in basic response)
    roles: list[str] | None = None
    
    # External IDs
    external_ids: list[str] | None = None
    
    # Leadership and Owner References (not present in basic response)
    leadership_reference: list[str] | None = None
    organization_owner_reference: str | None = None
    organization_visibility_reference: str | None = None
    external_url_reference: str | None = None

    @validator('inactive', 'is_top_level', 'include_manager_in_name', 'include_organization_code_in_name', 
               'available_for_hire', 'hiring_freeze', pre=True)
    def validate_boolean_fields(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return v.lower() == 'true' or v == "1"
        return bool(v)

    @validator('availability_date', 'last_updated_datetime', 'inactive_date', pre=True)
    def validate_dates(cls, v):
        # Keep dates as strings for now to avoid parsing issues
        if isinstance(v, str) and v and v != "1900-01-01T00:00:00.000-08:00":
            return v
        return v

    class Config:
        arbitrary_types_allowed = True 
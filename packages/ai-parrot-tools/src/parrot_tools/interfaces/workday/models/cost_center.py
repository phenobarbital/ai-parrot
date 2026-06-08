from typing import List, Optional, Union
from pydantic import BaseModel, Field, validator


class CostCenter(BaseModel):
    """Complete cost center model based on Workday Get_Cost_Centers API documentation."""
    
    # Cost Center Reference
    cost_center_id: Optional[str] = None
    cost_center_wid: Optional[str] = None
    cost_center_name: Optional[str] = None
    cost_center_code: Optional[str] = None
    
    # Organization Data
    organization_id: Optional[str] = None
    organization_name: Optional[str] = None
    organization_code: Optional[str] = None
    include_organization_code_in_name: Optional[Union[bool, str]] = None
    organization_active: Optional[Union[bool, str]] = None
    organization_visibility: Optional[str] = None
    external_url: Optional[str] = None
    
    # Organization Type and Subtype
    organization_type: Optional[str] = None
    organization_type_id: Optional[str] = None
    organization_subtype: Optional[str] = None
    organization_subtype_id: Optional[str] = None
    
    # Dates
    effective_date: Optional[str] = None
    availability_date: Optional[str] = None
    last_updated_datetime: Optional[str] = None
    inactive_date: Optional[str] = None
    
    # Status
    inactive: Optional[Union[bool, str]] = None
    
    # Organization Container
    container_organization_id: Optional[str] = None
    container_organization_name: Optional[str] = None
    container_organization_wid: Optional[str] = None
    
    # Worktags
    worktags: Optional[List[str]] = Field(default_factory=list)
    
    # Integration ID Data  
    integration_ids: Optional[List[str]] = Field(default_factory=list)
    external_integration_id: Optional[str] = None
    
    # Manager Information
    manager_reference: Optional[str] = None
    manager_name: Optional[str] = None
    manager_id: Optional[str] = None
    
    # Hierarchy Information
    hierarchy_data: Optional[dict] = None
    superior_organization_id: Optional[str] = None
    superior_organization_name: Optional[str] = None
    
    # Financial Information
    budget_reference: Optional[str] = None
    cost_center_type: Optional[str] = None
    
    @validator('organization_active', 'include_organization_code_in_name', 'inactive', pre=True)
    def parse_boolean_fields(cls, v):
        """Convert boolean-like values to proper booleans."""
        if isinstance(v, str):
            return v.lower() in ('true', '1', 'yes')
        return v
    
    @validator('worktags', 'integration_ids', pre=True)
    def parse_list_fields(cls, v):
        """Ensure list fields are properly parsed."""
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return v
        return []
    
    @validator('effective_date', 'availability_date', 'last_updated_datetime', 'inactive_date', pre=True)
    def parse_date_fields(cls, v):
        """Convert date objects to string format."""
        if v is None:
            return None
        if hasattr(v, 'isoformat'):  # datetime.date or datetime.datetime objects
            return v.isoformat()
        if isinstance(v, str):
            return v
        return str(v)
    
    class Config:
        # Allow extra fields that might come from the API
        extra = "allow"
        # Use enum values for validation
        use_enum_values = True 
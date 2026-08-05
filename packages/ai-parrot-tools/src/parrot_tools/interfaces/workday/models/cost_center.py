
from pydantic import BaseModel, Field, validator


class CostCenter(BaseModel):
    """Complete cost center model based on Workday Get_Cost_Centers API documentation."""
    
    # Cost Center Reference
    cost_center_id: str | None = None
    cost_center_wid: str | None = None
    cost_center_name: str | None = None
    cost_center_code: str | None = None
    
    # Organization Data
    organization_id: str | None = None
    organization_name: str | None = None
    organization_code: str | None = None
    include_organization_code_in_name: bool | str | None = None
    organization_active: bool | str | None = None
    organization_visibility: str | None = None
    external_url: str | None = None
    
    # Organization Type and Subtype
    organization_type: str | None = None
    organization_type_id: str | None = None
    organization_subtype: str | None = None
    organization_subtype_id: str | None = None
    
    # Dates
    effective_date: str | None = None
    availability_date: str | None = None
    last_updated_datetime: str | None = None
    inactive_date: str | None = None
    
    # Status
    inactive: bool | str | None = None
    
    # Organization Container
    container_organization_id: str | None = None
    container_organization_name: str | None = None
    container_organization_wid: str | None = None
    
    # Worktags
    worktags: list[str] | None = Field(default_factory=list)
    
    # Integration ID Data  
    integration_ids: list[str] | None = Field(default_factory=list)
    external_integration_id: str | None = None
    
    # Manager Information
    manager_reference: str | None = None
    manager_name: str | None = None
    manager_id: str | None = None
    
    # Hierarchy Information
    hierarchy_data: dict | None = None
    superior_organization_id: str | None = None
    superior_organization_name: str | None = None
    
    # Financial Information
    budget_reference: str | None = None
    cost_center_type: str | None = None

    # Organization enrichment (cost-centre organisation-hierarchy enrichment)
    org_parent_organization_id: str | None = None
    org_parent_organization_name: str | None = None
    org_parent_organization_type: str | None = None
    org_roles: list[str] | None = None
    org_external_ids: list[str] | None = None
    org_last_updated: str | None = None
    org_hierarchy_chain: str | None = None

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
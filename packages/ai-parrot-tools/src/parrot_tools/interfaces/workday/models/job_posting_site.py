from typing import List, Optional, Union
from pydantic import BaseModel, Field, field_validator, ConfigDict


class JobPostingSite(BaseModel):
    """Job Posting Site model based on Workday Get_Job_Posting_Sites API."""

    # Job Posting Site Reference
    job_posting_site_id: Optional[str] = None
    job_posting_site_wid: Optional[str] = None
    job_posting_site_name: Optional[str] = None

    # Site Details
    site_type: Optional[str] = None
    site_type_id: Optional[str] = None

    # Site Configuration
    external_url: Optional[str] = None
    site_url: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None

    # Status
    is_active: Optional[Union[bool, str]] = None
    is_internal: Optional[Union[bool, str]] = None
    is_external: Optional[Union[bool, str]] = None

    # Priority/Order
    display_order: Optional[int] = None
    priority: Optional[int] = None

    # Integration IDs
    integration_ids: Optional[List[str]] = Field(default_factory=list)
    external_integration_id: Optional[str] = None

    # Dates
    created_date: Optional[str] = None
    last_updated_date: Optional[str] = None

    @field_validator('is_active', 'is_internal', 'is_external', mode="before")
    @classmethod
    def parse_boolean_fields(cls, v):
        """Convert boolean-like values to proper booleans."""
        if isinstance(v, str):
            return v.lower() in ('true', '1', 'yes', 'active')
        return v

    @field_validator('integration_ids', mode="before")
    @classmethod
    def parse_list_fields(cls, v):
        """Ensure list fields are properly parsed."""
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return v
        return []

    @field_validator('display_order', 'priority', mode="before")
    @classmethod
    def parse_integer_fields(cls, v):
        """Convert integer-like values to proper integers."""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str):
            try:
                return int(float(v))
            except (ValueError, TypeError):
                return None
        return None

    @field_validator('created_date', 'last_updated_date', mode="before")
    @classmethod
    def parse_date_fields(cls, v):
        """Convert date objects to string format."""
        if v is None:
            return None
        if hasattr(v, 'isoformat'):  # datetime.date or datetime.datetime objects
            return v.isoformat()
        if isinstance(v, str):
            return v
        return str(v)

    model_config = ConfigDict(
        extra="allow",
        use_enum_values=True,
    )

from typing import List, Optional, Union
from pydantic import BaseModel, Field, validator


class JobPosting(BaseModel):
    """Job Posting model based on Workday Get_Job_Postings API."""

    # Job Posting Reference
    job_posting_id: Optional[str] = None
    job_posting_wid: Optional[str] = None
    job_posting_name: Optional[str] = None

    # Job Requisition Reference (parent)
    job_requisition_id: Optional[str] = None
    job_requisition_wid: Optional[str] = None
    job_requisition_name: Optional[str] = None

    # Job Posting Status
    job_posting_status: Optional[str] = None
    job_posting_status_id: Optional[str] = None

    # Job Posting Details
    job_posting_title: Optional[str] = None
    job_description: Optional[str] = None
    external_job_description: Optional[str] = None
    posting_instructions: Optional[str] = None

    # External URL
    external_url: Optional[str] = None
    external_application_url: Optional[str] = None

    # Dates
    posting_date: Optional[str] = None
    removal_date: Optional[str] = None
    job_posting_start_date: Optional[str] = None
    job_posting_end_date: Optional[str] = None
    expiration_date: Optional[str] = None
    created_date: Optional[str] = None
    last_updated_date: Optional[str] = None
    recruiting_start_date: Optional[str] = None
    target_hire_date: Optional[str] = None

    # Job Posting Sites (where it's published)
    job_posting_sites: Optional[List[str]] = Field(default_factory=list)
    job_posting_site_ids: Optional[List[str]] = Field(default_factory=list)

    # Location
    location_id: Optional[str] = None
    location_wid: Optional[str] = None
    location_name: Optional[str] = None

    # Supervisory Organization
    supervisory_organization_id: Optional[str] = None
    supervisory_organization_wid: Optional[str] = None
    supervisory_organization_name: Optional[str] = None

    # Job Profile
    job_profile_id: Optional[str] = None
    job_profile_wid: Optional[str] = None
    job_profile_name: Optional[str] = None

    # Worker Type
    worker_type_id: Optional[str] = None
    worker_type_wid: Optional[str] = None
    worker_type_name: Optional[str] = None

    # Position Worker Type (Employee Type like Seasonal, Full-time, etc.)
    position_worker_type_id: Optional[str] = None
    position_worker_type_wid: Optional[str] = None
    position_worker_type_name: Optional[str] = None

    # Job Type (Employee Type)
    job_type_id: Optional[str] = None
    job_type_wid: Optional[str] = None
    job_type_name: Optional[str] = None

    # Time Type
    time_type_id: Optional[str] = None
    time_type_name: Optional[str] = None

    # Job Family
    job_family_id: Optional[str] = None
    job_family_wid: Optional[str] = None
    job_family_name: Optional[str] = None

    # Job Family Group
    job_family_group_id: Optional[str] = None
    job_family_group_wid: Optional[str] = None
    job_family_group_name: Optional[str] = None

    # Primary Job Posting Location
    primary_job_posting_location_id: Optional[str] = None
    primary_job_posting_location_wid: Optional[str] = None
    primary_job_posting_location_name: Optional[str] = None

    # Posting flags
    is_posted: Optional[Union[bool, str]] = None
    is_internal: Optional[Union[bool, str]] = None
    is_external: Optional[Union[bool, str]] = None
    primary_posting: Optional[Union[bool, str]] = None
    spotlight_job: Optional[Union[bool, str]] = None
    available_for_recruiting: Optional[Union[bool, str]] = None
    confidential_job_requisition: Optional[Union[bool, str]] = None
    academic_tenure_eligible: Optional[Union[bool, str]] = None

    # Number of openings
    number_of_openings: Optional[int] = None
    positions_allocated: Optional[int] = None
    positions_available: Optional[int] = None

    # Additional fields
    forecasted_payout: Optional[Union[int, float, str]] = None
    scheduled_weekly_hours: Optional[Union[int, float, str]] = None

    # External paths
    external_job_path: Optional[str] = None
    external_apply_url: Optional[str] = None

    # Job Application Template
    job_application_template_id: Optional[str] = None
    job_application_template_wid: Optional[str] = None
    job_application_template_name: Optional[str] = None

    # Qualifications
    competencies: Optional[List[str]] = Field(default_factory=list)

    # Integration IDs
    integration_ids: Optional[List[str]] = Field(default_factory=list)
    external_integration_id: Optional[str] = None

    @validator('is_posted', 'is_internal', 'is_external', 'primary_posting', 'spotlight_job',
               'available_for_recruiting', 'confidential_job_requisition', 'academic_tenure_eligible', pre=True)
    def parse_boolean_fields(cls, v):
        """Convert boolean-like values to proper booleans."""
        if isinstance(v, str):
            return v.lower() in ('true', '1', 'yes')
        if isinstance(v, (int, float)):
            return bool(v)
        return v

    @validator('job_posting_sites', 'job_posting_site_ids', 'integration_ids', 'competencies', pre=True)
    def parse_list_fields(cls, v):
        """Ensure list fields are properly parsed."""
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return v
        return []

    @validator('number_of_openings', 'positions_allocated', 'positions_available', pre=True)
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

    @validator('forecasted_payout', 'scheduled_weekly_hours', pre=True)
    def parse_numeric_fields(cls, v):
        """Convert numeric-like values to proper numbers (int or float)."""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return v
        if isinstance(v, str):
            try:
                if '.' in v:
                    return float(v)
                return int(v)
            except (ValueError, TypeError):
                return None
        return None

    @validator('posting_date', 'removal_date', 'job_posting_start_date', 'job_posting_end_date',
               'expiration_date', 'created_date', 'last_updated_date', 'recruiting_start_date',
               'target_hire_date', pre=True)
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
        extra = "allow"
        use_enum_values = True

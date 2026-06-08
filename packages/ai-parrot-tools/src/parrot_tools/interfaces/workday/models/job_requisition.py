from typing import List, Optional, Union
from pydantic import BaseModel, Field, validator


class JobRequisition(BaseModel):
    """Complete job requisition model based on Workday Get_Job_Requisitions API documentation."""

    # Job Requisition Reference
    job_requisition_id: Optional[str] = None
    job_requisition_wid: Optional[str] = None
    job_requisition_name: Optional[str] = None

    # Job Requisition Status
    job_requisition_status: Optional[str] = None
    job_requisition_status_id: Optional[str] = None
    job_requisition_status_wid: Optional[str] = None

    # Job Posting Details
    job_posting_title: Optional[str] = None
    job_description: Optional[str] = None
    recruiting_instructions: Optional[str] = None

    # Job Requisition Flags
    academic_tenure_eligible: Optional[Union[bool, str]] = None
    available_for_recruiting: Optional[Union[bool, str]] = None
    confidential_job_requisition: Optional[Union[bool, str]] = None
    spotlight_job: Optional[Union[bool, str]] = None

    # Job Application Template
    job_application_template_id: Optional[str] = None
    job_application_template_wid: Optional[str] = None
    job_application_template_name: Optional[str] = None

    # Positions
    number_of_openings: Optional[int] = None
    positions_allocated: Optional[int] = None
    positions_filled: Optional[int] = None
    positions_available: Optional[int] = None

    # Hiring Requirements - Dates
    recruiting_start_date: Optional[str] = None
    target_hire_date: Optional[str] = None
    earliest_hire_date: Optional[str] = None

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

    # Location (Primary Location)
    location_id: Optional[str] = None
    location_wid: Optional[str] = None
    location_name: Optional[str] = None

    # Primary Job Posting Location (can be different from primary location)
    primary_job_posting_location_id: Optional[str] = None
    primary_job_posting_location_wid: Optional[str] = None
    primary_job_posting_location_name: Optional[str] = None

    # Supervisory Organization
    supervisory_organization_id: Optional[str] = None
    supervisory_organization_wid: Optional[str] = None
    supervisory_organization_name: Optional[str] = None

    # Position Details
    position_id: Optional[str] = None
    position_wid: Optional[str] = None
    position_title: Optional[str] = None

    # Time Type
    time_type_id: Optional[str] = None
    time_type_wid: Optional[str] = None
    time_type_name: Optional[str] = None

    # Job Family
    job_family_id: Optional[str] = None
    job_family_name: Optional[str] = None

    # Dates
    created_date: Optional[str] = None
    last_updated_date: Optional[str] = None
    effective_date: Optional[str] = None

    # Qualifications - stored as lists
    competencies: Optional[List[str]] = Field(default_factory=list)
    certifications: Optional[List[str]] = Field(default_factory=list)
    education_requirements: Optional[List[str]] = Field(default_factory=list)
    language_skills: Optional[List[str]] = Field(default_factory=list)
    work_experience: Optional[List[str]] = Field(default_factory=list)
    training_requirements: Optional[List[str]] = Field(default_factory=list)

    # Additional fields
    primary_location_id: Optional[str] = None
    primary_location_wid: Optional[str] = None
    primary_location_name: Optional[str] = None

    # Integration IDs
    integration_ids: Optional[List[str]] = Field(default_factory=list)
    external_integration_id: Optional[str] = None

    # Employment Type
    employment_type_id: Optional[str] = None
    employment_type_name: Optional[str] = None

    # Posting Information
    is_posted: Optional[Union[bool, str]] = None
    posting_date: Optional[str] = None
    removal_date: Optional[str] = None

    # Hiring Manager
    hiring_manager_id: Optional[str] = None
    hiring_manager_wid: Optional[str] = None
    hiring_manager_name: Optional[str] = None

    # Recruiter (single - for backward compatibility)
    recruiter_id: Optional[str] = None
    recruiter_wid: Optional[str] = None
    recruiter_name: Optional[str] = None

    # Recruiters (multiple - from Role_Assignment_Data)
    recruiters: Optional[List[dict]] = Field(default_factory=list)

    # Organization Assignments
    company_id: Optional[str] = None
    company_wid: Optional[str] = None
    company_name: Optional[str] = None
    cost_center_id: Optional[str] = None
    cost_center_wid: Optional[str] = None
    cost_center_name: Optional[str] = None

    # Compensation Data
    primary_compensation_basis: Optional[Union[int, str]] = None
    compensation_package_id: Optional[str] = None
    compensation_package_wid: Optional[str] = None
    compensation_package_name: Optional[str] = None
    compensation_grade_id: Optional[str] = None
    compensation_grade_wid: Optional[str] = None
    compensation_grade_name: Optional[str] = None
    compensation_grade_profile_id: Optional[str] = None
    compensation_grade_profile_wid: Optional[str] = None
    compensation_grade_profile_name: Optional[str] = None
    pay_plan_id: Optional[str] = None
    pay_plan_wid: Optional[str] = None
    pay_plan_name: Optional[str] = None
    pay_rate_amount: Optional[Union[int, float, str]] = None
    pay_rate_currency: Optional[str] = None
    pay_rate_frequency: Optional[str] = None

    # Questionnaires
    internal_questionnaire_id: Optional[str] = None
    internal_questionnaire_wid: Optional[str] = None
    internal_questionnaire_name: Optional[str] = None
    external_questionnaire_id: Optional[str] = None
    external_questionnaire_wid: Optional[str] = None
    external_questionnaire_name: Optional[str] = None

    # Additional Hiring Data
    scheduled_weekly_hours: Optional[Union[int, float, str]] = None

    @validator('is_posted', pre=True)
    def parse_boolean_fields(cls, v):
        """Convert boolean-like values to proper booleans."""
        if isinstance(v, str):
            return v.lower() in ('true', '1', 'yes')
        return v

    @validator('competencies', 'certifications', 'education_requirements', 'language_skills',
               'work_experience', 'training_requirements', 'integration_ids', 'recruiters', pre=True)
    def parse_list_fields(cls, v):
        """Ensure list fields are properly parsed."""
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return v
        return []

    @validator('number_of_openings', 'positions_allocated', 'positions_filled', 'positions_available',
               'primary_compensation_basis', pre=True)
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

    @validator('pay_rate_amount', 'scheduled_weekly_hours', pre=True)
    def parse_numeric_fields(cls, v):
        """Convert numeric-like values to proper numbers (int or float)."""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return v
        if isinstance(v, str):
            try:
                # Try int first, then float
                if '.' in v:
                    return float(v)
                return int(v)
            except (ValueError, TypeError):
                return None
        return None

    @validator('recruiting_start_date', 'target_hire_date', 'earliest_hire_date',
               'created_date', 'last_updated_date', 'effective_date', 'posting_date', 'removal_date', pre=True)
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

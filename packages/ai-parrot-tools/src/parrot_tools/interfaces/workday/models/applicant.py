from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class Applicant(BaseModel):
    """
    Pydantic model for a Workday Applicant/Pre-hire record.
    Based on Get_Applicants operation from Recruiting API v44.2
    https://community.workday.com/sites/default/files/file-hosting/productionapi/Recruiting/v44.2/Get_Applicants.html
    """
    # Applicant Reference
    applicant_id: Optional[str] = None
    applicant_wid: Optional[str] = None
    
    # Personal Data
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    formatted_name: Optional[str] = None
    legal_name: Optional[str] = None
    preferred_name: Optional[str] = None
    
    # Demographics
    birth_date: Optional[str] = None
    gender: Optional[str] = None
    hispanic_or_latino: Optional[bool] = None
    ethnicity: Optional[str] = None
    tobacco_use: Optional[bool] = None
    
    # Contact Information
    email: Optional[str] = None
    emails: Optional[List[str]] = None
    personal_email: Optional[str] = None  # Public=0 (personal email)
    corporate_email: Optional[str] = None  # Public=1 (work email)
    email_usage_public: Optional[bool] = None
    email_id: Optional[str] = None
    phone: Optional[str] = None
    phones: Optional[List[str]] = None
    
    # Address
    address: Optional[str] = None
    address_city: Optional[str] = None
    address_state: Optional[str] = None
    address_postal_code: Optional[str] = None
    address_country: Optional[str] = None
    
    # Recruitment Data
    job_requisition_id: Optional[str] = None
    job_requisition_title: Optional[str] = None
    application_date: Optional[str] = None
    candidate_status: Optional[str] = None
    candidate_stage: Optional[str] = None
    source: Optional[str] = None
    recruiter_id: Optional[str] = None
    recruiter_name: Optional[str] = None
    
    # Pre-hire specific
    is_pre_hire: Optional[bool] = None
    expected_hire_date: Optional[str] = None
    original_hire_date: Optional[str] = None
    position_title: Optional[str] = None
    business_title: Optional[str] = None
    
    # Location/Organization
    location: Optional[str] = None
    location_id: Optional[str] = None
    supervisory_organization: Optional[str] = None
    supervisory_organization_id: Optional[str] = None
    company: Optional[str] = None
    company_id: Optional[str] = None
    cost_center: Optional[str] = None
    cost_center_id: Optional[str] = None
    
    # Education
    highest_education_level: Optional[str] = None
    schools: Optional[List[str]] = None
    
    # Experience
    years_of_experience: Optional[int] = None
    previous_employers: Optional[List[str]] = None
    
    # Skills & Competencies
    skills: Optional[List[str]] = None
    competencies: Optional[List[Dict[str, Any]]] = None
    
    # Identifiers
    national_id: Optional[str] = None
    national_id_type: Optional[str] = None
    passport_number: Optional[str] = None
    license_id: Optional[str] = None
    license_state: Optional[str] = None
    license_type: Optional[str] = None
    license_expiration_date: Optional[str] = None
    
    # Custom IDs (Workday specific)
    associate_oid: Optional[str] = None
    adp_payroll_id: Optional[str] = None
    adp_payroll_group: Optional[str] = None
    old_corporate_email: Optional[str] = None
    icims_id: Optional[str] = None
    mso_dealer_code: Optional[str] = None
    netsuite_internal_id: Optional[str] = None
    
    # Background Check
    background_check_status: Optional[str] = None
    background_check_date: Optional[str] = None
    
    # References
    references: Optional[List[Dict[str, Any]]] = None
    
    # Attachments/Documents
    resume_attached: Optional[bool] = None
    documents: Optional[List[str]] = None
    
    # Additional Data
    custom_fields: Optional[Dict[str, Any]] = None
    
    # Raw SOAP response (excluded from DataFrame exports)
    raw_data: Optional[Dict[str, Any]] = Field(default_factory=dict, exclude=True)
    
    class Config:
        arbitrary_types_allowed = True 
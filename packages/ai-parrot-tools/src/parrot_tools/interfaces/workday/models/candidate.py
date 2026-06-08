from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class Candidate(BaseModel):
    """
    Pydantic model for a Workday Candidate record.
    Based on Get_Candidates operation from Recruiting API v45.0
    https://community.workday.com/sites/default/files/file-hosting/productionapi/Recruiting/v45.0/Get_Candidates.html
    
    NOTE: Get_Candidates returns LIMITED data compared to Get_Applicants.
    Many fields available in Get_Applicants are NOT available here.
    """
    # Candidate Reference
    candidate_id: Optional[str] = None
    candidate_wid: Optional[str] = None
    applications: Optional[List[Dict[str, Any]]] = None

    # Related References
    applicant_id: Optional[str] = None  # From Pre-Hire_Reference
    applicant_wid: Optional[str] = None  # From Pre-Hire_Reference
    associate_id: Optional[str] = None  # From Worker_Reference -> Employee_ID (when converted to worker)
    worker_wid: Optional[str] = None  # From Worker_Reference -> WID
    
    # Personal Data (from Name_Data)
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    formatted_name: Optional[str] = None
    legal_name: Optional[str] = None
    preferred_name: Optional[str] = None
    
    # Demographics (from Job_Applied_To_Data -> Personal_Information_Data)
    birth_date: Optional[str] = None
    gender: Optional[str] = None
    hispanic_or_latino: Optional[bool] = None
    ethnicity: Optional[str] = None
    veterans_status: Optional[str] = None
    disability_status: Optional[str] = None
    disability_status_date: Optional[str] = None
    gender_wid: Optional[str] = None
    ethnicity_wid: Optional[str] = None
    veterans_status_wid: Optional[str] = None
    disability_status_wid: Optional[str] = None
    
    # Contact Information (from Contact_Data)
    email: Optional[str] = None
    emails: Optional[List[str]] = None
    personal_email: Optional[str] = None  # From email parsing
    corporate_email: Optional[str] = None
    phone: Optional[str] = None
    phones: Optional[List[str]] = None
    phone_device_type_id: Optional[str] = None
    phone_device_type_wid: Optional[str] = None
    country_phone_code_id: Optional[str] = None
    country_phone_code_wid: Optional[str] = None
    
    # Address (from Contact_Data -> Location_Data)
    address: Optional[str] = None
    address_line_1: Optional[str] = None
    address_city: Optional[str] = None
    address_state: Optional[str] = None
    address_postal_code: Optional[str] = None
    address_country: Optional[str] = None
    
    # Recruitment Data (from Job_Application_Data -> Job_Applied_To_Data)
    job_application_id: Optional[str] = None
    job_application_wid: Optional[str] = None
    job_requisition_id: Optional[str] = None
    job_requisition_title: Optional[str] = None
    application_date: Optional[str] = None
    applied_date: Optional[str] = None
    application_timestamp: Optional[str] = None
    candidate_status: Optional[str] = None
    candidate_stage: Optional[str] = None
    candidate_stage_wid: Optional[str] = None
    recruiting_step: Optional[str] = None
    source: Optional[str] = None
    source_wid: Optional[str] = None
    recruiter_id: Optional[str] = None
    recruiter_name: Optional[str] = None
    current_step: Optional[str] = None
    current_step_date: Optional[str] = None
    current_step_timestamp: Optional[str] = None
    disqualified: Optional[bool] = None
    disqualification_reason: Optional[str] = None

    # 🔹 Nuevos campos para estado, disposición y flujo
    candidate_stage_desc: Optional[str] = None
    status_display: Optional[str] = None
    workflow_step_id: Optional[str] = None
    workflow_step_desc: Optional[str] = None
    workflow_step_wid: Optional[str] = None
    disposition_code: Optional[str] = None
    disposition_desc: Optional[str] = None
    
    # Status Data
    do_not_hire: Optional[bool] = None
    withdrawn: Optional[bool] = None
    
    # Prospect Data
    prospect: Optional[bool] = None
    confidential: Optional[bool] = None
    prospect_status: Optional[str] = None
    prospect_type: Optional[str] = None
    referral_consent_given: Optional[bool] = None
    added_by_worker_id: Optional[str] = None
    added_by_worker_name: Optional[str] = None
    
    # Education (from Resume_Data -> Education_Data)
    schools: Optional[List[str]] = None
    degrees: Optional[List[Dict[str, Any]]] = None
    education_history: Optional[List[Dict[str, Any]]] = None
    
    # Experience (from Resume_Data -> Experience_Data)
    years_of_experience: Optional[int] = None
    previous_employers: Optional[List[str]] = None
    work_experience: Optional[List[Dict[str, Any]]] = None
    
    # Skills & Competencies (from Resume_Data if available)
    skills: Optional[List[str]] = None
    competencies: Optional[List[Dict[str, Any]]] = None
    
    # Language
    language: Optional[str] = None 
    languages: Optional[List[Dict[str, Any]]] = None 
        
    # Documents & Attachments (from Resume_Attachment_Data)
    resume_attached: Optional[bool] = None
    resume_filename: Optional[str] = None
    resume_mime_type: Optional[str] = None
    pdf_path: Optional[str] = None  # Path to saved PDF/resume file
    cover_letter_attached: Optional[bool] = None
    documents: Optional[List[str]] = None
    attachments: Optional[List[Dict[str, Any]]] = None  # All attachments with metadata (JSONB)
    
    class Config:
        """Pydantic configuration"""
        arbitrary_types_allowed = True
        extra = "allow"
        # exclude_none = True  # Uncomment if quieres excluir campos None en output

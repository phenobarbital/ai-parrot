---
type: Wiki Summary
title: parrot_tools.interfaces.workday.parsers.candidate_parsers
id: mod:parrot_tools.interfaces.workday.parsers.candidate_parsers
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot_tools.interfaces.workday.parsers.candidate_parsers
relates_to:
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.ensure_list
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.extract_id_by_type
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_applications
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_assessment_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_background_check_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_contact_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_document_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_education_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_experience_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_identification_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_interview_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_language_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_metadata
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_offer_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_organization_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_personal_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_prospect_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_recruitment_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_reference
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_reference_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_skills_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_status_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.safe_get_reference
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.save_attachment
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.to_date_string
  rel: defines
---

# `parrot_tools.interfaces.workday.parsers.candidate_parsers`

## Functions

- `def save_attachment(file_content_base64: str, filename: str, candidate_id: str, storage_path: Optional[str]=None) -> Optional[str]` — Save attachment file from base64 content to disk.
- `def to_date_string(value: Any) -> Optional[str]` — Convert datetime/date objects to ISO format string (YYYY-MM-DD)
- `def extract_id_by_type(id_list: Any, id_type: str) -> Optional[str]` — Helper function to extract ID value by type from ID list
- `def ensure_list(value: Any) -> List` — Ensure value is a list
- `def safe_get_reference(data: Dict[str, Any], key: str) -> Dict[str, Any]` — Safely get a _Reference field that might be a dict, list, or None.
- `def parse_candidate_reference(candidate_raw: Dict[str, Any], candidate_data: Dict[str, Any]=None) -> Dict[str, Any]` — Parse Candidate Reference data and related references (Pre-Hire, Worker).
- `def parse_candidate_personal_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Personal Data for Candidate - based on actual Workday XML structure
- `def parse_candidate_contact_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Contact Information for Candidate - based on actual Workday XML structure
- `def parse_candidate_recruitment_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Recruitment-specific data for Candidate (campos "planos" a partir de la
- `def parse_candidate_status_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Status Data for Candidate (Do Not Hire, Withdrawn)
- `def parse_candidate_prospect_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Prospect Data for Candidate
- `def parse_candidate_language_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Language data for Candidate
- `def parse_candidate_organization_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Organization/Location data for Candidate
- `def parse_candidate_education_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Education data for Candidate.
- `def parse_candidate_experience_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Experience data for Candidate.
- `def parse_candidate_skills_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Skills, Competencies and Languages data for Candidate.
- `def parse_candidate_identification_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Identification data for Candidate
- `def parse_candidate_background_check_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Background Check data for Candidate
- `def parse_candidate_interview_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Interview data for Candidate
- `def parse_candidate_offer_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Offer data for Candidate
- `def parse_candidate_assessment_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Assessment/Rating data for Candidate
- `def parse_candidate_document_data(candidate_data: Dict[str, Any], candidate_id: Optional[str]=None, pdf_directory: Optional[str]=None) -> Dict[str, Any]` — Parse Document/Attachment data for Candidate.
- `def parse_candidate_reference_data(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Reference (employment references) data for Candidate
- `def parse_candidate_metadata(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Parse metadata like created date, modified date, tags
- `def parse_candidate_applications(candidate_data: Dict[str, Any]) -> Dict[str, Any]` — Devuelve todas las postulaciones del candidato como una lista en 'applications'.

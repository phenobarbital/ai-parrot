---
type: Wiki Summary
title: parrot_tools.interfaces.workday.parsers.applicant_parsers
id: mod:parrot_tools.interfaces.workday.parsers.applicant_parsers
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot_tools.interfaces.workday.parsers.applicant_parsers
relates_to:
- concept: func:parrot_tools.interfaces.workday.parsers.applicant_parsers.extract_id_by_type
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.applicant_parsers.parse_applicant_background_check_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.applicant_parsers.parse_applicant_contact_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.applicant_parsers.parse_applicant_document_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.applicant_parsers.parse_applicant_education_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.applicant_parsers.parse_applicant_experience_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.applicant_parsers.parse_applicant_identification_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.applicant_parsers.parse_applicant_organization_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.applicant_parsers.parse_applicant_personal_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.applicant_parsers.parse_applicant_recruitment_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.applicant_parsers.parse_applicant_reference
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.applicant_parsers.parse_applicant_skills_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.applicant_parsers.safe_get_dict
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.applicant_parsers.to_date_string
  rel: defines
---

# `parrot_tools.interfaces.workday.parsers.applicant_parsers`

## Functions

- `def to_date_string(value: Any) -> Optional[str]` — Convert datetime/date objects to ISO format string (YYYY-MM-DD)
- `def extract_id_by_type(id_list: Any, id_type: str) -> Optional[str]` — Helper function to extract ID value by type from ID list
- `def safe_get_dict(data: Any, key: str, default: Any=None) -> Any` — Safely get a value from data, handling cases where data might be a list.
- `def parse_applicant_reference(applicant_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Applicant Reference data
- `def parse_applicant_personal_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Personal Data for Applicant
- `def parse_applicant_contact_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Contact Information for Applicant
- `def parse_applicant_recruitment_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Recruitment specific data for Applicant
- `def parse_applicant_organization_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Organization/Location data for Applicant
- `def parse_applicant_education_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Education data for Applicant
- `def parse_applicant_experience_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Experience data for Applicant
- `def parse_applicant_skills_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Skills and Competencies data for Applicant
- `def parse_applicant_identification_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Identification data for Applicant
- `def parse_applicant_background_check_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Background Check data for Applicant
- `def parse_applicant_document_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]` — Parse Document/Attachment data for Applicant

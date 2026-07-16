---
type: Wiki Summary
title: parrot_tools.interfaces.workday.parsers.job_requisition_parsers
id: mod:parrot_tools.interfaces.workday.parsers.job_requisition_parsers
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Job Requisition parsers for Workday Get_Job_Requisitions operation.
relates_to:
- concept: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_compensation_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_hiring_manager_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_integration_id_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_job_profile_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_job_requisition_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_job_requisition_reference
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_jr_location_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_organization_assignments_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_position_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_qualifications_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_questionnaire_references
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_recruiter_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_role_assignment_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_supervisory_organization_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_worker_type_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.safe_get_nested
  rel: defines
- concept: mod:parrot_tools.interfaces.workday.utils
  rel: references
---

# `parrot_tools.interfaces.workday.parsers.job_requisition_parsers`

Job Requisition parsers for Workday Get_Job_Requisitions operation.

## Functions

- `def safe_get_nested(data: Dict, *keys, default=None) -> Any` — Safely get nested dictionary values.
- `def parse_integration_id_data(integration_data: Union[List, Dict, None]) -> Dict[str, Any]` — Parse Integration ID Data from Job Requisition response.
- `def parse_job_requisition_reference(jr_ref: Dict) -> Dict[str, str]` — Parse Job Requisition Reference to extract WID and ID.
- `def parse_job_profile_data(job_profile_ref: Dict) -> Dict[str, Any]` — Parse Job Profile Reference data.
- `def parse_worker_type_data(worker_type_ref: Dict) -> Dict[str, Any]` — Parse Worker Type Reference data.
- `def parse_jr_location_data(location_ref: Dict) -> Dict[str, Any]` — Parse Location Reference data for Job Requisitions.
- `def parse_supervisory_organization_data(org_ref: Dict) -> Dict[str, Any]` — Parse Supervisory Organization Reference data.
- `def parse_position_data(position_ref: Dict) -> Dict[str, Any]` — Parse Position Reference data.
- `def parse_hiring_manager_data(manager_ref: Dict) -> Dict[str, Any]` — Parse Hiring Manager Reference data.
- `def parse_recruiter_data(recruiter_ref: Dict) -> Dict[str, Any]` — Parse Recruiter Reference data (single recruiter).
- `def parse_role_assignment_data(role_assignment_data: Union[List, Dict, None]) -> Dict[str, List[Dict[str, str]]]` — Parse Role Assignment Data to extract recruiters and other role assignees.
- `def parse_organization_assignments_data(org_assignments: Dict) -> Dict[str, Any]` — Parse Organization Assignments Data (Company, Cost Center, etc.).
- `def parse_compensation_data(compensation_data: Dict) -> Dict[str, Any]` — Parse Requisition Compensation Data.
- `def parse_questionnaire_references(questionnaire_data: Dict) -> Dict[str, Any]` — Parse Questionnaire Reference data.
- `def parse_qualifications_data(qualifications_data: Union[List, Dict, None]) -> Dict[str, List[str]]` — Parse Qualifications data (competencies, certifications, education, etc.).
- `def parse_job_requisition_data(job_requisition: Dict) -> Dict[str, Any]` — Parse complete Job Requisition data from Workday response.

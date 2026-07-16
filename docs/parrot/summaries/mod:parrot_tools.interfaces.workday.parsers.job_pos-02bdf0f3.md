---
type: Wiki Summary
title: parrot_tools.interfaces.workday.parsers.job_posting_parsers
id: mod:parrot_tools.interfaces.workday.parsers.job_posting_parsers
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Job Posting parsers for Workday Get_Job_Postings operation.
relates_to:
- concept: func:parrot_tools.interfaces.workday.parsers.job_posting_parsers.coalesce
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_posting_parsers.parse_integration_id_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_posting_parsers.parse_job_posting_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_posting_parsers.parse_job_posting_reference
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_posting_parsers.parse_job_posting_sites
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_posting_parsers.parse_job_profile_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_posting_parsers.parse_job_requisition_reference
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_posting_parsers.parse_location_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_posting_parsers.parse_qualifications_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_posting_parsers.parse_supervisory_organization_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_posting_parsers.parse_worker_type_data
  rel: defines
- concept: mod:parrot_tools.interfaces.workday.utils
  rel: references
---

# `parrot_tools.interfaces.workday.parsers.job_posting_parsers`

Job Posting parsers for Workday Get_Job_Postings operation.

## Functions

- `def coalesce(*args)` — Return the first non-None value from the arguments.
- `def parse_job_posting_reference(jp_ref: Dict) -> Dict[str, str]` — Parse Job Posting Reference to extract WID and ID.
- `def parse_job_requisition_reference(jr_ref: Dict) -> Dict[str, str]` — Parse Job Requisition Reference from Job Posting.
- `def parse_job_posting_sites(sites_data: Union[List, Dict, None]) -> Dict[str, List[str]]` — Parse Job Posting Sites data.
- `def parse_location_data(location_ref: Dict) -> Dict[str, Any]` — Parse Location Reference data.
- `def parse_supervisory_organization_data(org_ref: Dict) -> Dict[str, Any]` — Parse Supervisory Organization Reference data.
- `def parse_job_profile_data(job_profile_ref: Dict) -> Dict[str, Any]` — Parse Job Profile Reference data.
- `def parse_worker_type_data(worker_type_ref: Dict) -> Dict[str, Any]` — Parse Worker Type Reference data.
- `def parse_integration_id_data(integration_data: Union[List, Dict, None]) -> Dict[str, Any]` — Parse Integration ID Data from Job Posting response.
- `def parse_qualifications_data(qualifications_data: Union[List, Dict, None]) -> Dict[str, List[str]]` — Parse Qualifications data (competencies).
- `def parse_job_posting_data(job_posting: Dict) -> Dict[str, Any]` — Parse complete Job Posting data from Workday response.

---
type: Wiki Summary
title: parrot_tools.interfaces.workday.parsers.job_posting_site_parsers
id: mod:parrot_tools.interfaces.workday.parsers.job_posting_site_parsers
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Job Posting Site parsers for Workday Get_Job_Posting_Sites operation.
relates_to:
- concept: func:parrot_tools.interfaces.workday.parsers.job_posting_site_parsers.parse_integration_id_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_posting_site_parsers.parse_job_posting_site_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_posting_site_parsers.parse_job_posting_site_reference
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.job_posting_site_parsers.parse_site_type_data
  rel: defines
- concept: mod:parrot_tools.interfaces.workday.utils
  rel: references
---

# `parrot_tools.interfaces.workday.parsers.job_posting_site_parsers`

Job Posting Site parsers for Workday Get_Job_Posting_Sites operation.

## Functions

- `def parse_job_posting_site_reference(site_ref: Dict) -> Dict[str, str]` — Parse Job Posting Site Reference to extract WID and ID.
- `def parse_site_type_data(site_type_ref: Dict) -> Dict[str, str]` — Parse Site Type Reference data.
- `def parse_integration_id_data(integration_data: Union[List, Dict, None]) -> Dict[str, Any]` — Parse Integration ID Data from Job Posting Site response.
- `def parse_job_posting_site_data(job_posting_site: Dict) -> Dict[str, Any]` — Parse complete Job Posting Site data from Workday response.

---
type: Concept
title: parse_job_posting_site_data()
id: func:parrot_tools.interfaces.workday.parsers.job_posting_site_parsers.parse_job_posting_site_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse complete Job Posting Site data from Workday response.
---

# parse_job_posting_site_data

```python
def parse_job_posting_site_data(job_posting_site: Dict) -> Dict[str, Any]
```

Parse complete Job Posting Site data from Workday response.

Args:
    job_posting_site: Job Posting Site data from Get_Job_Posting_Sites response

Returns:
    Dictionary with all parsed job posting site information

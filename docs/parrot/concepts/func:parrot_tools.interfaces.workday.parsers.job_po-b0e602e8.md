---
type: Concept
title: parse_job_posting_data()
id: func:parrot_tools.interfaces.workday.parsers.job_posting_parsers.parse_job_posting_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse complete Job Posting data from Workday response.
---

# parse_job_posting_data

```python
def parse_job_posting_data(job_posting: Dict) -> Dict[str, Any]
```

Parse complete Job Posting data from Workday response.

Args:
    job_posting: Job Posting data from Get_Job_Postings response

Returns:
    Dictionary with all parsed job posting information

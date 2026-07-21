---
type: Concept
title: parse_job_posting_site_reference()
id: func:parrot_tools.interfaces.workday.parsers.job_posting_site_parsers.parse_job_posting_site_reference
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse Job Posting Site Reference to extract WID and ID.
---

# parse_job_posting_site_reference

```python
def parse_job_posting_site_reference(site_ref: Dict) -> Dict[str, str]
```

Parse Job Posting Site Reference to extract WID and ID.

Args:
    site_ref: Job Posting Site Reference data

Returns:
    Dictionary with job_posting_site_wid, job_posting_site_id, and job_posting_site_name

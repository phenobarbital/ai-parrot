---
type: Concept
title: parse_job_posting_reference()
id: func:parrot_tools.interfaces.workday.parsers.job_posting_parsers.parse_job_posting_reference
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse Job Posting Reference to extract WID and ID.
---

# parse_job_posting_reference

```python
def parse_job_posting_reference(jp_ref: Dict) -> Dict[str, str]
```

Parse Job Posting Reference to extract WID and ID.

Args:
    jp_ref: Job Posting Reference data

Returns:
    Dictionary with job_posting_wid, job_posting_id, and job_posting_name

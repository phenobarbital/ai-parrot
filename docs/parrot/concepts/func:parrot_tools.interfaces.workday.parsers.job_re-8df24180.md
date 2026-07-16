---
type: Concept
title: parse_recruiter_data()
id: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_recruiter_data
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse Recruiter Reference data (single recruiter).
---

# parse_recruiter_data

```python
def parse_recruiter_data(recruiter_ref: Dict) -> Dict[str, Any]
```

Parse Recruiter Reference data (single recruiter).

Args:
    recruiter_ref: Worker Reference from the response

Returns:
    Dictionary with parsed recruiter information

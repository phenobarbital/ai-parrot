---
type: Concept
title: parse_job_requisition_reference()
id: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_job_requisition_reference
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse Job Requisition Reference to extract WID and ID.
---

# parse_job_requisition_reference

```python
def parse_job_requisition_reference(jr_ref: Dict) -> Dict[str, str]
```

Parse Job Requisition Reference to extract WID and ID.

Args:
    jr_ref: Job Requisition Reference data

Returns:
    Dictionary with job_requisition_wid and job_requisition_id

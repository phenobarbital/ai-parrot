---
type: Concept
title: parse_job_requisition_data()
id: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_job_requisition_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse complete Job Requisition data from Workday response.
---

# parse_job_requisition_data

```python
def parse_job_requisition_data(job_requisition: Dict) -> Dict[str, Any]
```

Parse complete Job Requisition data from Workday response.

Args:
    job_requisition: Job Requisition data from Get_Job_Requisitions response

Returns:
    Dictionary with all parsed job requisition information

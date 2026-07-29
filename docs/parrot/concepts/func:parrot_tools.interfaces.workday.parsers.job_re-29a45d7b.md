---
type: Concept
title: parse_jr_location_data()
id: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_jr_location_data
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse Location Reference data for Job Requisitions.
---

# parse_jr_location_data

```python
def parse_jr_location_data(location_ref: Dict) -> Dict[str, Any]
```

Parse Location Reference data for Job Requisitions.

Args:
    location_ref: Location Reference from the response

Returns:
    Dictionary with parsed location information (simplified for job requisitions)

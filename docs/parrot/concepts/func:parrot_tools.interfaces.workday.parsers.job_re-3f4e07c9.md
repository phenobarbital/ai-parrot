---
type: Concept
title: parse_hiring_manager_data()
id: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_hiring_manager_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse Hiring Manager Reference data.
---

# parse_hiring_manager_data

```python
def parse_hiring_manager_data(manager_ref: Dict) -> Dict[str, Any]
```

Parse Hiring Manager Reference data.

Args:
    manager_ref: Worker Reference from the response

Returns:
    Dictionary with parsed hiring manager information

---
type: Concept
title: parse_role_assignment_data()
id: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_role_assignment_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse Role Assignment Data to extract recruiters and other role assignees.
---

# parse_role_assignment_data

```python
def parse_role_assignment_data(role_assignment_data: Union[List, Dict, None]) -> Dict[str, List[Dict[str, str]]]
```

Parse Role Assignment Data to extract recruiters and other role assignees.

Args:
    role_assignment_data: Role Assignment Data from the response

Returns:
    Dictionary with lists of recruiters and other role assignments

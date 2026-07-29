---
type: Concept
title: parse_organization_assignments_data()
id: func:parrot_tools.interfaces.workday.parsers.job_requisition_parsers.parse_organization_assignments_data
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse Organization Assignments Data (Company, Cost Center, etc.).
---

# parse_organization_assignments_data

```python
def parse_organization_assignments_data(org_assignments: Dict) -> Dict[str, Any]
```

Parse Organization Assignments Data (Company, Cost Center, etc.).

Args:
    org_assignments: Organization Assignments Data from the response

Returns:
    Dictionary with parsed organization assignments

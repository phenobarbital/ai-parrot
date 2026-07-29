---
type: Concept
title: parse_organization_assignment()
id: func:parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers.parse_organization_assignment
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse organization assignment by type data.
---

# parse_organization_assignment

```python
def parse_organization_assignment(assignment_data: Dict[str, Any]) -> OrganizationAssignment
```

Parse organization assignment by type data.

Args:
    assignment_data: Raw organization assignment data
    
Returns:
    Parsed OrganizationAssignment object

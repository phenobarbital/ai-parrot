---
type: Concept
title: parse_location_hierarchy_assignment()
id: func:parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers.parse_location_hierarchy_assignment
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse location hierarchy organization assignment data.
---

# parse_location_hierarchy_assignment

```python
def parse_location_hierarchy_assignment(assignment_data: Dict[str, Any]) -> LocationHierarchyAssignment
```

Parse location hierarchy organization assignment data.

Args:
    assignment_data: Raw assignment data from the API (already Location_Hierarchy_Organization_Assignments_Data)
    
Returns:
    Parsed LocationHierarchyAssignment object

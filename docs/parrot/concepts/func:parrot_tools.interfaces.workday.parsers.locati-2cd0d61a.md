---
type: Concept
title: parse_location_hierarchy_assignments_response()
id: func:parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers.parse_location_hierarchy_assignments_response
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse the complete location hierarchy assignments response.
---

# parse_location_hierarchy_assignments_response

```python
def parse_location_hierarchy_assignments_response(response_data: Dict[str, Any]) -> List[LocationHierarchyAssignment]
```

Parse the complete location hierarchy assignments response.

Args:
    response_data: Raw response data from the API
    
Returns:
    List of parsed LocationHierarchyAssignment objects

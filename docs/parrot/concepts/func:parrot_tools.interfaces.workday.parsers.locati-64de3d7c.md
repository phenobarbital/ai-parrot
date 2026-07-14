---
type: Concept
title: parse_location_hierarchy_assignments_data()
id: func:parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers.parse_location_hierarchy_assignments_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Main parser function for location hierarchy assignments data.
---

# parse_location_hierarchy_assignments_data

```python
def parse_location_hierarchy_assignments_data(raw_data: Dict[str, Any]) -> Dict[str, Any]
```

Main parser function for location hierarchy assignments data.

Args:
    raw_data: Raw data from the API response
    
Returns:
    Dictionary with parsed assignments and metadata

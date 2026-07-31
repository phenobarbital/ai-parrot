---
type: Concept
title: parse_response_results()
id: func:parrot_tools.interfaces.workday.parsers.location_hierarchy_assignments_parsers.parse_response_results
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse response results (pagination info).
---

# parse_response_results

```python
def parse_response_results(response_data: Dict[str, Any]) -> Dict[str, Any]
```

Parse response results (pagination info).

Args:
    response_data: Raw response data from the API
    
Returns:
    Dictionary with pagination information

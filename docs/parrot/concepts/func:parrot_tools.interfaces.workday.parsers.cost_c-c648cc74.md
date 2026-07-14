---
type: Concept
title: parse_organization_type_data()
id: func:parrot_tools.interfaces.workday.parsers.cost_center_parsers.parse_organization_type_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse Organization Type and Subtype data.
---

# parse_organization_type_data

```python
def parse_organization_type_data(type_data: Dict) -> Dict[str, Any]
```

Parse Organization Type and Subtype data.

Args:
    type_data: Organization type data from the response
    
Returns:
    Dictionary with parsed type information

---
type: Concept
title: parse_organization_data()
id: func:parrot_tools.interfaces.workday.parsers.cost_center_parsers.parse_organization_data
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse Organization Data section from Cost Center response.
---

# parse_organization_data

```python
def parse_organization_data(org_data: Dict) -> Dict[str, Any]
```

Parse Organization Data section from Cost Center response.

Args:
    org_data: Organization data from the response
    
Returns:
    Dictionary with parsed organization information

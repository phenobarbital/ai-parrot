---
type: Concept
title: parse_cost_center_data()
id: func:parrot_tools.interfaces.workday.parsers.cost_center_parsers.parse_cost_center_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse complete Cost Center data from Workday response.
---

# parse_cost_center_data

```python
def parse_cost_center_data(cost_center: Dict) -> Dict[str, Any]
```

Parse complete Cost Center data from Workday response.

Args:
    cost_center: Cost Center data from Get_Cost_Centers response
    
Returns:
    Dictionary with all parsed cost center information

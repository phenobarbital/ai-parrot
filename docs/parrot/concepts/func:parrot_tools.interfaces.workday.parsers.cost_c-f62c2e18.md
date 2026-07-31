---
type: Concept
title: parse_cost_center_reference()
id: func:parrot_tools.interfaces.workday.parsers.cost_center_parsers.parse_cost_center_reference
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse Cost Center Reference to extract WID and ID.
---

# parse_cost_center_reference

```python
def parse_cost_center_reference(cc_ref: Dict) -> Dict[str, str]
```

Parse Cost Center Reference to extract WID and ID.

Args:
    cc_ref: Cost Center Reference data
    
Returns:
    Dictionary with cost_center_wid and cost_center_id

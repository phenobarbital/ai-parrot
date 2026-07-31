---
type: Concept
title: safe_get_dict()
id: func:parrot_tools.interfaces.workday.parsers.applicant_parsers.safe_get_dict
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Safely get a value from data, handling cases where data might be a list.
---

# safe_get_dict

```python
def safe_get_dict(data: Any, key: str, default: Any=None) -> Any
```

Safely get a value from data, handling cases where data might be a list.
If data is a list, try to get from the first dict item.

---
type: Concept
title: safe_get_reference()
id: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.safe_get_reference
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Safely get a _Reference field that might be a dict, list, or None.
---

# safe_get_reference

```python
def safe_get_reference(data: Dict[str, Any], key: str) -> Dict[str, Any]
```

Safely get a _Reference field that might be a dict, list, or None.
Returns the first item if it's a list, or the dict if it's a dict, or empty dict.

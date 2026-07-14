---
type: Concept
title: safe_get_nested()
id: func:parrot_tools.interfaces.workday.parsers.cost_center_parsers.safe_get_nested
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Safely get nested dictionary values.
---

# safe_get_nested

```python
def safe_get_nested(data: Dict, *keys, default=None) -> Any
```

Safely get nested dictionary values.

Args:
    data: Dictionary to traverse
    *keys: Keys to traverse
    default: Default value if key path doesn't exist
    
Returns:
    Value at key path or default

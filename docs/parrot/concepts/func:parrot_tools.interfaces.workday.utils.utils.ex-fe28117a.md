---
type: Concept
title: extract_by_type()
id: func:parrot_tools.interfaces.workday.utils.utils.extract_by_type
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Given a list of {'_value_1':…, 'type':…} dicts (or a single dict),
---

# extract_by_type

```python
def extract_by_type(ids: Any, desired_type: str) -> Optional[str]
```

Given a list of {'_value_1':…, 'type':…} dicts (or a single dict),
return the value whose type matches `desired_type`, or None.

---
type: Concept
title: list_templates()
id: func:parrot.helpers.infographics.list_templates
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: List available infographic template names.
---

# list_templates

```python
def list_templates(detailed: bool=False) -> Union[List[str], List[Dict[str, str]]]
```

List available infographic template names.

Args:
    detailed: When True, return list of dicts with name + description.

Returns:
    Sorted list of names, or sorted list of detailed dicts when
    ``detailed=True``.

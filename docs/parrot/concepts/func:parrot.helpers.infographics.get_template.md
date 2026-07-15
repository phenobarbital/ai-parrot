---
type: Concept
title: get_template()
id: func:parrot.helpers.infographics.get_template
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Retrieve a template by name.
---

# get_template

```python
def get_template(name: str) -> InfographicTemplate
```

Retrieve a template by name.

Args:
    name: Template identifier.

Returns:
    The matching InfographicTemplate instance.

Raises:
    KeyError: If the template name is not registered.

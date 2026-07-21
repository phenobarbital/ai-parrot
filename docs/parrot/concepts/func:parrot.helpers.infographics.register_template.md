---
type: Concept
title: register_template()
id: func:parrot.helpers.infographics.register_template
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Register a custom infographic template.
---

# register_template

```python
def register_template(template: Union[InfographicTemplate, dict]) -> InfographicTemplate
```

Register a custom infographic template.

Accepts either an InfographicTemplate instance or a raw dict that
will be validated via InfographicTemplate.model_validate. Returns
the validated template instance.

Args:
    template: InfographicTemplate instance or a dict conforming to
        the InfographicTemplate schema.

Returns:
    The registered InfographicTemplate instance.

Raises:
    TypeError: If ``template`` is neither a dict nor an
        ``InfographicTemplate`` instance.
    pydantic.ValidationError: If the dict payload is malformed.

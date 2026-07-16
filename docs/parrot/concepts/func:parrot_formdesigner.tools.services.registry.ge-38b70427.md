---
type: Concept
title: get_form_service()
id: func:parrot_formdesigner.tools.services.registry.get_form_service
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Resolve a registered form-service class by name.
---

# get_form_service

```python
def get_form_service(name: str) -> type[AbstractFormService]
```

Resolve a registered form-service class by name.

Args:
    name: The service name to look up.

Returns:
    The registered AbstractFormService subclass.

Raises:
    KeyError: if no service is registered under ``name``.

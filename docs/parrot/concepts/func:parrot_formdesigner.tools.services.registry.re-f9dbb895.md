---
type: Concept
title: register_form_service()
id: func:parrot_formdesigner.tools.services.registry.register_form_service
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register (or overwrite) a form-service class under ``name``.
---

# register_form_service

```python
def register_form_service(name: str, service_cls: type[AbstractFormService]) -> None
```

Register (or overwrite) a form-service class under ``name``.

Idempotent: re-registering the same name overwrites and logs a warning.

Args:
    name: Identifier exposed to DatabaseFormInput.service.
    service_cls: AbstractFormService subclass.

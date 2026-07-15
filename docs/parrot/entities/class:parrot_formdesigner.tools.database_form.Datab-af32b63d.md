---
type: Wiki Entity
title: DatabaseFormInput
id: class:parrot_formdesigner.tools.database_form.DatabaseFormInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input schema for DatabaseFormTool — service-aware.
---

# DatabaseFormInput

Defined in [`parrot_formdesigner.tools.database_form`](../summaries/mod:parrot_formdesigner.tools.database_form.md).

```python
class DatabaseFormInput(BaseModel)
```

Input schema for DatabaseFormTool — service-aware.

Attributes:
    service: Form source service name. Must be registered via
        register_form_service(...). Defaults to 'networkninja'.
    formid: Numeric form identifier in the database.
    orgid: Organization ID that owns the form.
    params: Optional service-specific extras forwarded to
        AbstractFormService.fetch(**params).
    persist: Whether to save the resulting FormSchema to the registry storage.

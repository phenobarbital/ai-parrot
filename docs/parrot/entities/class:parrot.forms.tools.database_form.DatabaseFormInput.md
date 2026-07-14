---
type: Wiki Entity
title: DatabaseFormInput
id: class:parrot.forms.tools.database_form.DatabaseFormInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input schema for DatabaseFormTool.
---

# DatabaseFormInput

Defined in [`parrot.forms.tools.database_form`](../summaries/mod:parrot.forms.tools.database_form.md).

```python
class DatabaseFormInput(BaseModel)
```

Input schema for DatabaseFormTool.

Attributes:
    formid: Numeric form identifier in the database.
    orgid: Organization ID that owns the form.
    persist: Whether to save the resulting FormSchema to the registry storage.

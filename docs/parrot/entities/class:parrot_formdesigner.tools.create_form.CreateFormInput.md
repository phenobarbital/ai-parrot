---
type: Wiki Entity
title: CreateFormInput
id: class:parrot_formdesigner.tools.create_form.CreateFormInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input schema for the create_form tool.
---

# CreateFormInput

Defined in [`parrot_formdesigner.tools.create_form`](../summaries/mod:parrot_formdesigner.tools.create_form.md).

```python
class CreateFormInput(BaseModel)
```

Input schema for the create_form tool.

Attributes:
    prompt: Natural language description of the form to create.
    form_id: Custom form ID. Auto-generated if not provided.
    persist: Whether to save the form to the registry storage.
    refine_form_id: ID of an existing form to load and modify.

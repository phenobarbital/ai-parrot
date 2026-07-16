---
type: Wiki Entity
title: RequestFormInput
id: class:parrot_formdesigner.tools.request_form.RequestFormInput
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Input schema for the request_form tool.
---

# RequestFormInput

Defined in [`parrot_formdesigner.tools.request_form`](../summaries/mod:parrot_formdesigner.tools.request_form.md).

```python
class RequestFormInput(BaseModel)
```

Input schema for the request_form tool.

Attributes:
    target_tool: Name of the tool to execute after form completion.
    known_values: Parameter values already extracted from conversation.
    fields_to_collect: Specific field names to include in the form.
    form_title: Custom form title.
    context_message: Message explaining to the user why the form is needed.

---
type: Wiki Entity
title: SubmitAction
id: class:parrot_formdesigner.core.schema.SubmitAction
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Defines what happens when a form is submitted.
---

# SubmitAction

Defined in [`parrot_formdesigner.core.schema`](../summaries/mod:parrot_formdesigner.core.schema.md).

```python
class SubmitAction(BaseModel)
```

Defines what happens when a form is submitted.

Attributes:
    action_type: How the submission is handled.
    action_ref: Reference to the handler (tool name, URL, event name, callback ID).
    method: HTTP method for endpoint submissions.
    confirm_message: Optional confirmation message shown before submission.

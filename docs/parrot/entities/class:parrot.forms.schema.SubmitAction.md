---
type: Wiki Entity
title: SubmitAction
id: class:parrot.forms.schema.SubmitAction
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Defines what happens when a form is submitted.
---

# SubmitAction

Defined in [`parrot.forms.schema`](../summaries/mod:parrot.forms.schema.md).

```python
class SubmitAction(BaseModel)
```

Defines what happens when a form is submitted.

Attributes:
    action_type: How the submission is handled.
    action_ref: Reference to the handler (tool name, URL, event name, callback ID).
    method: HTTP method for endpoint submissions.
    confirm_message: Optional confirmation message shown before submission.

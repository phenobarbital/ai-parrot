---
type: Wiki Entity
title: FormAlreadyExistsError
id: class:parrot_formdesigner.services.registry.FormAlreadyExistsError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised when registering a form whose ``form_id`` is already taken.
---

# FormAlreadyExistsError

Defined in [`parrot_formdesigner.services.registry`](../summaries/mod:parrot_formdesigner.services.registry.md).

```python
class FormAlreadyExistsError(ValueError)
```

Raised when registering a form whose ``form_id`` is already taken.

Subclasses ``ValueError`` so existing ``except ValueError`` blocks keep
working, but lets API handlers distinguish 409 Conflict (duplicate id)
from 422 Unprocessable Entity (validation failure).

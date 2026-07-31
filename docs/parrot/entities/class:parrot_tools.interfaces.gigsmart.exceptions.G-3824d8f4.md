---
type: Wiki Entity
title: GigSmartValidationError
id: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartValidationError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Input validation failure.
relates_to:
- concept: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartError
  rel: extends
---

# GigSmartValidationError

Defined in [`parrot_tools.interfaces.gigsmart.exceptions`](../summaries/mod:parrot_tools.interfaces.gigsmart.exceptions.md).

```python
class GigSmartValidationError(GigSmartError)
```

Input validation failure.

Raised when the API returns ``BAD_USER_INPUT`` — the caller supplied
invalid values for a query argument or mutation field.

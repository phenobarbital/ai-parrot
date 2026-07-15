---
type: Wiki Entity
title: GigSmartNotFoundError
id: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartNotFoundError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Requested resource does not exist.
relates_to:
- concept: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartError
  rel: extends
---

# GigSmartNotFoundError

Defined in [`parrot_tools.interfaces.gigsmart.exceptions`](../summaries/mod:parrot_tools.interfaces.gigsmart.exceptions.md).

```python
class GigSmartNotFoundError(GigSmartError)
```

Requested resource does not exist.

Raised when the API returns a ``NOT_FOUND`` extension code.

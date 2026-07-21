---
type: Wiki Entity
title: GigSmartAuthError
id: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartAuthError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Authentication or authorisation failure.
relates_to:
- concept: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartError
  rel: extends
---

# GigSmartAuthError

Defined in [`parrot_tools.interfaces.gigsmart.exceptions`](../summaries/mod:parrot_tools.interfaces.gigsmart.exceptions.md).

```python
class GigSmartAuthError(GigSmartError)
```

Authentication or authorisation failure.

Raised when the API returns ``UNAUTHENTICATED`` or ``FORBIDDEN`` error codes,
or when a write-scope operation is attempted with a client_credentials token.

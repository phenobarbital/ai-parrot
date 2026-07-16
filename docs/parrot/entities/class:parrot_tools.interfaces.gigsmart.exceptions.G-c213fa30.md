---
type: Wiki Entity
title: GigSmartGraphQLError
id: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartGraphQLError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Generic GraphQL protocol error.
relates_to:
- concept: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartError
  rel: extends
---

# GigSmartGraphQLError

Defined in [`parrot_tools.interfaces.gigsmart.exceptions`](../summaries/mod:parrot_tools.interfaces.gigsmart.exceptions.md).

```python
class GigSmartGraphQLError(GigSmartError)
```

Generic GraphQL protocol error.

Raised when the response contains ``errors`` that do not match any
other classified code.

Args:
    message: Human-readable summary.
    errors: The raw ``errors`` list from the GraphQL response body,
        preserving the full ``extensions`` payload for diagnostics.

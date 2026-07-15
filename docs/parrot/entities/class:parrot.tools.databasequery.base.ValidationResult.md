---
type: Wiki Entity
title: ValidationResult
id: class:parrot.tools.databasequery.base.ValidationResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result of a query validation operation.
---

# ValidationResult

Defined in [`parrot.tools.databasequery.base`](../summaries/mod:parrot.tools.databasequery.base.md).

```python
class ValidationResult(BaseModel)
```

Result of a query validation operation.

Attributes:
    valid: Whether the query is syntactically valid.
    error: Error message if validation failed.
    dialect: The query dialect that was validated against.

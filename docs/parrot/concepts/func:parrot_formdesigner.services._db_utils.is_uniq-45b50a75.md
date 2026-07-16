---
type: Concept
title: is_unique_violation()
id: func:parrot_formdesigner.services._db_utils.is_unique_violation
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return True when ``exc`` is a Postgres UNIQUE constraint violation.
---

# is_unique_violation

```python
def is_unique_violation(exc: Exception) -> bool
```

Return True when ``exc`` is a Postgres UNIQUE constraint violation.

Works for asyncpg (``UniqueViolationError``), psycopg2/3, and drivers
that wrap the original error — without importing driver-specific types.

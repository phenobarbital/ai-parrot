---
type: Wiki Entity
title: RlsPredicate
id: class:parrot.auth.rls_registry.RlsPredicate
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A rendered RLS predicate ready for injection.
---

# RlsPredicate

Defined in [`parrot.auth.rls_registry`](../summaries/mod:parrot.auth.rls_registry.md).

```python
class RlsPredicate(BaseModel)
```

A rendered RLS predicate ready for injection.

Attributes:
    table: The physical table this predicate applies to.
    sql_predicate: SQL WHERE clause fragment with parameter placeholders
        (e.g. ``"region IN (:p0, :p1)"``).  Subject values are *never*
        interpolated into this string — they live in ``bound_params``.
    bound_params: Mapping from placeholder name to list of string values
        to bind (e.g. ``{"p0": ["northeast"], "p1": ["southeast"]}``).

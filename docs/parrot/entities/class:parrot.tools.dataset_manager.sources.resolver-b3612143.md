---
type: Wiki Entity
title: ReadOnlyViolation
id: class:parrot.tools.dataset_manager.sources.resolver.ReadOnlyViolation
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised when a SQL statement is not read-only (DML/DDL detected).
---

# ReadOnlyViolation

Defined in [`parrot.tools.dataset_manager.sources.resolver`](../summaries/mod:parrot.tools.dataset_manager.sources.resolver.md).

```python
class ReadOnlyViolation(Exception)
```

Raised when a SQL statement is not read-only (DML/DDL detected).

The read-only gate is enforced before any network round-trip so that
mutation attempts are caught at parse time.

---
type: Wiki Entity
title: SeverityBreakdown
id: class:parrot.storage.security_reports.models.SeverityBreakdown
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Count container for findings by severity level.
---

# SeverityBreakdown

Defined in [`parrot.storage.security_reports.models`](../summaries/mod:parrot.storage.security_reports.models.md).

```python
class SeverityBreakdown(BaseModel)
```

Count container for findings by severity level.

Note: do NOT confuse with ``parrot_tools.security.models.SeverityLevel``
which is a level enum. This is a count container (see spec §7 R6).

## Methods

- `def total(self) -> int` — Sum of all severity counts.

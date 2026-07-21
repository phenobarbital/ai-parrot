---
type: Wiki Entity
title: SecurityFinding
id: class:parrot_tools.security.models.SecurityFinding
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Unified security finding from any scanner.
---

# SecurityFinding

Defined in [`parrot_tools.security.models`](../summaries/mod:parrot_tools.security.models.md).

```python
class SecurityFinding(BaseModel)
```

Unified security finding from any scanner.

This model normalizes findings from Prowler, Trivy, and Checkov into a
consistent format for aggregation and reporting.

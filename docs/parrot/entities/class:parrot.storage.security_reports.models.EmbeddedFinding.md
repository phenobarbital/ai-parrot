---
type: Wiki Entity
title: EmbeddedFinding
id: class:parrot.storage.security_reports.models.EmbeddedFinding
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single security finding embedded in a ReportRef.
---

# EmbeddedFinding

Defined in [`parrot.storage.security_reports.models`](../summaries/mod:parrot.storage.security_reports.models.md).

```python
class EmbeddedFinding(BaseModel)
```

A single security finding embedded in a ReportRef.

Top-10 (by severity) per report — not a full finding record.
For full finding detail, fetch the report content.

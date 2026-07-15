---
type: Wiki Entity
title: EcrSeverity
id: class:parrot_tools.cloudsploit.models.EcrSeverity
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: ECR / vulnerability scan severities (distinct from SeverityLevel).
---

# EcrSeverity

Defined in [`parrot_tools.cloudsploit.models`](../summaries/mod:parrot_tools.cloudsploit.models.md).

```python
class EcrSeverity(str, Enum)
```

ECR / vulnerability scan severities (distinct from SeverityLevel).

Maps to the severity strings returned by ECR Basic Scanning via
``describe_image_scan_findings``.  NOT compatible with
``SeverityLevel(OK/WARN/FAIL/UNKNOWN)`` — that enum is for CSPM.

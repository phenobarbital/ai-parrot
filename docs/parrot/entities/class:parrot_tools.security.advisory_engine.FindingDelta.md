---
type: Wiki Entity
title: FindingDelta
id: class:parrot_tools.security.advisory_engine.FindingDelta
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Day-over-day change for a single finding (aligned to SecurityFinding).
---

# FindingDelta

Defined in [`parrot_tools.security.advisory_engine`](../summaries/mod:parrot_tools.security.advisory_engine.md).

```python
class FindingDelta(BaseModel)
```

Day-over-day change for a single finding (aligned to SecurityFinding).

Attributes:
    finding_id: Unique finding identifier (SecurityFinding.id).
    status: Change classification — new, resolved, persisting, or
        severity_changed.
    severity: Current severity level (SeverityLevel value).
    previous_severity: Prior severity when status == 'severity_changed'.
    title: Short finding title.
    resource: Affected resource identifier (SecurityFinding.resource).
    check_id: Scanner-specific check ID (SecurityFinding.check_id).
    soc2_control_ids: SOC2 control IDs from ComplianceMapper.

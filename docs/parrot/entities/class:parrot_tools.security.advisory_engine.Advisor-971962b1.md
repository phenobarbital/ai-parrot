---
type: Wiki Entity
title: AdvisoryRecommendation
id: class:parrot_tools.security.advisory_engine.AdvisoryRecommendation
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: One actionable recommendation tied to SOC2 controls.
---

# AdvisoryRecommendation

Defined in [`parrot_tools.security.advisory_engine`](../summaries/mod:parrot_tools.security.advisory_engine.md).

```python
class AdvisoryRecommendation(BaseModel)
```

One actionable recommendation tied to SOC2 controls.

Attributes:
    title: Short recommendation title.
    severity: Severity level driving this recommendation.
    soc2_control_ids: SOC2 control IDs from ComplianceMapper.
    affected_resources: Resource identifiers affected.
    recommended_action: Concrete remediation step.
    is_material: True for new/severity-increased CRITICAL or HIGH
        findings; gates Jira ticket creation.

---
type: Wiki Entity
title: AdvisoryReport
id: class:parrot_tools.security.advisory_engine.AdvisoryReport
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Structured day-over-day SOC2 advisory for one framework.
---

# AdvisoryReport

Defined in [`parrot_tools.security.advisory_engine`](../summaries/mod:parrot_tools.security.advisory_engine.md).

```python
class AdvisoryReport(BaseModel)
```

Structured day-over-day SOC2 advisory for one framework.

No narrative: the agent's LLM writes prose from this model.

Attributes:
    framework: Compliance framework identifier (e.g. ``'soc2'``).
    baseline_report_id: Prior-day report ID (``None`` on first run).
    current_report_id: ID of the most-recent report analysed.
    severity_delta: Signed severity counts (current − baseline).
    deltas: Per-finding delta records, sorted by severity desc then id.
    soc2_coverage: Output of ``ComplianceMapper.get_framework_coverage``.
    control_findings: Mapping of control_id → number of failing findings.
    recommendations: Actionable recommendations, material items first.
    provider: Cloud provider (recorded for the persisted ReportRef).

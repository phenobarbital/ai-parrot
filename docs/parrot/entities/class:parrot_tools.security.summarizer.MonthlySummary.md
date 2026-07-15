---
type: Wiki Entity
title: MonthlySummary
id: class:parrot_tools.security.summarizer.MonthlySummary
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A month-scoped security posture summary for one (provider, framework) pair.
---

# MonthlySummary

Defined in [`parrot_tools.security.summarizer`](../summaries/mod:parrot_tools.security.summarizer.md).

```python
class MonthlySummary(BaseModel)
```

A month-scoped security posture summary for one (provider, framework) pair.

Produced by consuming the four weekly summaries for the month.  The diff
math operates on weekly ``persistent_findings`` sets (findings that
persisted across the whole week are more signal-worthy at monthly scope).

Attributes:
    framework: Compliance framework (e.g., ``"HIPAA"``).
    provider: Cloud / infra provider.
    period_start: Earliest ``period_start`` among source weekly summaries.
    period_end: Latest ``period_end`` among source weekly summaries.
    severity_totals: Sum of ``severity_totals`` across weekly summaries.
    persistent_findings: Findings present across ALL weekly summaries.
    executive_paragraph: 3–5 sentence monthly narrative from the LLM.
    source_report_ids: UUIDs of the ``ReportRef`` weekly_summary reports
        consumed (typically 4, one per week).

---
type: Wiki Entity
title: ReportRef
id: class:parrot.storage.security_reports.models.ReportRef
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Canonical metadata record for any security report.
---

# ReportRef

Defined in [`parrot.storage.security_reports.models`](../summaries/mod:parrot.storage.security_reports.models.md).

```python
class ReportRef(BaseModel)
```

Canonical metadata record for any security report.

Fractal: used for raw scans (report_kind=SCAN) and for aggregated
summaries (WEEKLY_SUMMARY, MONTHLY_SUMMARY, DRIFT_COMPARISON).

The ``uri`` field points to the content in S3 (``s3://bucket/key``) or
on the local filesystem (``file://path``). Content is NOT stored here.

``produced_at`` MUST be tz-aware UTC. Callers pass
``datetime.now(timezone.utc)`` — the model does not validate this.

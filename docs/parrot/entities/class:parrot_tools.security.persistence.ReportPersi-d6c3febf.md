---
type: Wiki Entity
title: ReportPersistenceMixin
id: class:parrot_tools.security.persistence.ReportPersistenceMixin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mixin that gives producer toolkits catalog write capability.
---

# ReportPersistenceMixin

Defined in [`parrot_tools.security.persistence`](../summaries/mod:parrot_tools.security.persistence.md).

```python
class ReportPersistenceMixin
```

Mixin that gives producer toolkits catalog write capability.

When ``file_manager`` AND ``report_store`` are both non-``None``,
``_persist_report`` uploads content to S3 and indexes metadata in
Postgres via the store. When either dependency is ``None``, the method
is a **no-op** (returns ``None`` silently) — existing callers that do
not inject persistence deps continue working unchanged.

Class attributes (set per-instance in the constructor):
    file_manager: Active ``FileManagerInterface`` or ``None``.
    report_store: Active ``SecurityReportStore`` or ``None``.
    parser_version: Version string forwarded to ``ReportRef.parser_version``.

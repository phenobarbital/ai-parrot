---
type: Wiki Entity
title: ReportFilter
id: class:parrot.storage.security_reports.models.ReportFilter
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Query filter for the security report store.
---

# ReportFilter

Defined in [`parrot.storage.security_reports.models`](../summaries/mod:parrot.storage.security_reports.models.md).

```python
class ReportFilter(BaseModel)
```

Query filter for the security report store.

IMPORTANT: No implicit age filtering at this layer — the store returns
ALL reports that match the filter, including very old ones. The caller
is responsible for setting ``since`` when a time window is desired
(spec §5 hard requirement, test: test_store_query_no_implicit_since).

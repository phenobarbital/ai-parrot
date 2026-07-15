---
type: Wiki Entity
title: RefreshReport
id: class:parrot.knowledge.ontology.refresh.RefreshReport
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Report from a full refresh pipeline run.
---

# RefreshReport

Defined in [`parrot.knowledge.ontology.refresh`](../summaries/mod:parrot.knowledge.ontology.refresh.md).

```python
class RefreshReport(BaseModel)
```

Report from a full refresh pipeline run.

Args:
    tenant: Tenant identifier.
    started_at: When the refresh started.
    completed_at: When the refresh completed.
    entity_results: Upsert results per entity name.
    discovery_results: Discovery stats per relation name.
    errors: Error messages encountered.

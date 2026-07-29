---
type: Wiki Entity
title: IngestReport
id: class:parrot.knowledge.wiki.ingest.IngestReport
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result of a single wiki ingest run.
---

# IngestReport

Defined in [`parrot.knowledge.wiki.ingest`](../summaries/mod:parrot.knowledge.wiki.ingest.md).

```python
class IngestReport(BaseModel)
```

Result of a single wiki ingest run.

Attributes:
    source_id: Stable identifier for the ingested source.
    source_uri: Absolute path / URI of the source document.
    pages_created: Number of new wiki pages created.
    pages_updated: Number of existing pages updated.
    graph_nodes_created: Number of GraphIndex nodes created.
    duration_ms: Wall-clock time in milliseconds.
    status: ``"ok"`` or ``"error"``.
    error: Optional error message when ``status == "error"``.

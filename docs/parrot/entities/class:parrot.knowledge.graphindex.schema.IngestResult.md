---
type: Wiki Entity
title: IngestResult
id: class:parrot.knowledge.graphindex.schema.IngestResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Outcome of an incremental ``GraphIndexBuilder.ingest_document()`` run.
---

# IngestResult

Defined in [`parrot.knowledge.graphindex.schema`](../summaries/mod:parrot.knowledge.graphindex.schema.md).

```python
class IngestResult(BaseModel)
```

Outcome of an incremental ``GraphIndexBuilder.ingest_document()`` run.

Args:
    tenant_id: Tenant that was updated.
    document_uri: URI of the document that was reprocessed.
    nodes_replaced: Number of nodes soft-deleted and replaced.
    edges_replaced: Number of edges replaced.
    errors: List of non-fatal error messages.

---
type: Wiki Entity
title: WikiPageRecord
id: class:parrot.knowledge.wiki.store.WikiPageRecord
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A single wiki page row in the retrieval plane.
---

# WikiPageRecord

Defined in [`parrot.knowledge.wiki.store`](../summaries/mod:parrot.knowledge.wiki.store.md).

```python
class WikiPageRecord(BaseModel)
```

A single wiki page row in the retrieval plane.

Attributes:
    concept_id: Stable page identity (primary key, link target).
    node_id: Volatile PageIndex node id (secondary lookup only).
    title: Page title.
    category: Open-string category (e.g. ``"summary"``, ``"entity"``).
    summary: Short summary used for stubs and FTS.
    body: Full markdown body (lives in the DB — no sidecar reads).
    source_id: Originating source id (``sources.source_id``).
    token_count: Estimated token cost of the body.

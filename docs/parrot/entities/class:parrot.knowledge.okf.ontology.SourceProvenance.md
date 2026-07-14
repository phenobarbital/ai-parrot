---
type: Wiki Entity
title: SourceProvenance
id: class:parrot.knowledge.okf.ontology.SourceProvenance
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Per-node provenance, citable.
---

# SourceProvenance

Defined in [`parrot.knowledge.okf.ontology`](../summaries/mod:parrot.knowledge.okf.ontology.md).

```python
class SourceProvenance(BaseModel)
```

Per-node provenance, citable.

Attributes:
    document: Source document filename (e.g. ``AICPA_SOC2.pdf``).
    pages: Optional list of page numbers (``[start_page, end_page]``).
    url: Optional source URL if available.

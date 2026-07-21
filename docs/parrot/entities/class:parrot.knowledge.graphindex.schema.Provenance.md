---
type: Wiki Entity
title: Provenance
id: class:parrot.knowledge.graphindex.schema.Provenance
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: How a node or edge was created.
---

# Provenance

Defined in [`parrot.knowledge.graphindex.schema`](../summaries/mod:parrot.knowledge.graphindex.schema.md).

```python
class Provenance(str, Enum)
```

How a node or edge was created.

Attributes:
    EXTRACTED: Directly extracted from source material.
    INFERRED: Inferred via embedding similarity (cross-domain resolution).
    AMBIGUOUS: Extraction was attempted but produced uncertain results
        (e.g., dynamic code features, malformed input).

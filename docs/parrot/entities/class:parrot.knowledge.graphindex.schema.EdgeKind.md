---
type: Wiki Entity
title: EdgeKind
id: class:parrot.knowledge.graphindex.schema.EdgeKind
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Semantic category of a directed graph edge.
---

# EdgeKind

Defined in [`parrot.knowledge.graphindex.schema`](../summaries/mod:parrot.knowledge.graphindex.schema.md).

```python
class EdgeKind(str, Enum)
```

Semantic category of a directed graph edge.

Attributes:
    CONTAINS: Parent–child containment (document→section, class→method).
    REFERENCES: One node cites or imports another.
    DEFINES: A module or document provides the authoritative definition.
    MENTIONS: Cross-domain inferred link (provenance=INFERRED).
    EXPLAINS: A rationale/docstring explains a symbol.
    EXTENDS: Odoo model inheritance — a class extends a canonical model
        node via ``_inherit`` or ``_inherits``. Added by FEAT-240.

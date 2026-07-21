---
type: Wiki Entity
title: RelationType
id: class:parrot.knowledge.okf.ontology.RelationType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Typed edge vocabulary (OKF-superset).
---

# RelationType

Defined in [`parrot.knowledge.okf.ontology`](../summaries/mod:parrot.knowledge.okf.ontology.md).

```python
class RelationType(str, Enum)
```

Typed edge vocabulary (OKF-superset).

Existing PageIndex values are unchanged.  FEAT-239 adds 4 graph edge kinds:
DEFINES, MENTIONS, EXPLAINS, CONTAINS.  FEAT-240 adds EXTENDS for Odoo
model inheritance.

``REFERENCES`` is the default for untyped prose link fallback.

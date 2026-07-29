---
type: Wiki Entity
title: ConceptType
id: class:parrot.knowledge.okf.ontology.ConceptType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Controlled ontological vocabulary for OKF node types.
---

# ConceptType

Defined in [`parrot.knowledge.okf.ontology`](../summaries/mod:parrot.knowledge.okf.ontology.md).

```python
class ConceptType(str, Enum)
```

Controlled ontological vocabulary for OKF node types.

Existing PageIndex values are unchanged.  FEAT-239 adds 5 graph-native
values: SYMBOL, RATIONALE, SKILL, CONCEPT_NODE, DOCUMENT_NODE.

``SECTION`` is the structural fallback for both PageIndex sections and
GraphIndex SECTION nodes — same string value, zero ambiguity.

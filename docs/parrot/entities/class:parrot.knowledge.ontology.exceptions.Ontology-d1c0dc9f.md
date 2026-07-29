---
type: Wiki Entity
title: OntologyIntegrityError
id: class:parrot.knowledge.ontology.exceptions.OntologyIntegrityError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised during post-merge integrity validation.
relates_to:
- concept: class:parrot.knowledge.ontology.exceptions.OntologyError
  rel: extends
---

# OntologyIntegrityError

Defined in [`parrot.knowledge.ontology.exceptions`](../summaries/mod:parrot.knowledge.ontology.exceptions.md).

```python
class OntologyIntegrityError(OntologyError)
```

Raised during post-merge integrity validation.

Examples:
    - Relation references a non-existent entity
    - Vectorize field references a non-existent property

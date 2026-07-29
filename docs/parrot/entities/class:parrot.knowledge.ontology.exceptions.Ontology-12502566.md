---
type: Wiki Entity
title: OntologyMergeError
id: class:parrot.knowledge.ontology.exceptions.OntologyMergeError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised during YAML merge when rules are violated.
relates_to:
- concept: class:parrot.knowledge.ontology.exceptions.OntologyError
  rel: extends
---

# OntologyMergeError

Defined in [`parrot.knowledge.ontology.exceptions`](../summaries/mod:parrot.knowledge.ontology.exceptions.md).

```python
class OntologyMergeError(OntologyError)
```

Raised during YAML merge when rules are violated.

Examples:
    - Duplicate entity without ``extend: true``
    - Attempting to change an immutable field (key_field, collection)
    - Relation endpoint mismatch between layers

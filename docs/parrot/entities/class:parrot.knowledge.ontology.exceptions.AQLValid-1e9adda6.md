---
type: Wiki Entity
title: AQLValidationError
id: class:parrot.knowledge.ontology.exceptions.AQLValidationError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised when LLM-generated AQL fails safety validation.
relates_to:
- concept: class:parrot.knowledge.ontology.exceptions.OntologyError
  rel: extends
---

# AQLValidationError

Defined in [`parrot.knowledge.ontology.exceptions`](../summaries/mod:parrot.knowledge.ontology.exceptions.md).

```python
class AQLValidationError(OntologyError)
```

Raised when LLM-generated AQL fails safety validation.

Examples:
    - AQL contains mutation keywords (INSERT, UPDATE, REMOVE)
    - Traversal depth exceeds ONTOLOGY_MAX_TRAVERSAL_DEPTH
    - Access to system collections (_system, _graphs)
    - Inline JavaScript execution attempts

---
type: Wiki Entity
title: SynonymConflictError
id: class:parrot.knowledge.ontology.exceptions.SynonymConflictError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised when a synonym conflicts with an existing approved concept synonym.
relates_to:
- concept: class:parrot.knowledge.ontology.exceptions.OntologyError
  rel: extends
---

# SynonymConflictError

Defined in [`parrot.knowledge.ontology.exceptions`](../summaries/mod:parrot.knowledge.ontology.exceptions.md).

```python
class SynonymConflictError(OntologyError)
```

Raised when a synonym conflicts with an existing approved concept synonym.

Synonym uniqueness is enforced within a tenant's approved concepts.

Args:
    message: Human-readable error description.
    synonym: The conflicting synonym string.
    existing_slug: Slug of the concept that already owns the synonym.

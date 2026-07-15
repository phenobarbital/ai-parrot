---
type: Wiki Entity
title: DryRunFailedError
id: class:parrot.knowledge.ontology.exceptions.DryRunFailedError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised when a schema overlay dry-run fails validation.
relates_to:
- concept: class:parrot.knowledge.ontology.exceptions.OntologyError
  rel: extends
---

# DryRunFailedError

Defined in [`parrot.knowledge.ontology.exceptions`](../summaries/mod:parrot.knowledge.ontology.exceptions.md).

```python
class DryRunFailedError(OntologyError)
```

Raised when a schema overlay dry-run fails validation.

The dry-run report is stored so callers can surface check details to users.

Args:
    message: Human-readable error description.
    report: The DryRunReport (or a plain dict) describing what failed.

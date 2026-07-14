---
type: Wiki Entity
title: InvalidTransitionError
id: class:parrot.knowledge.ontology.exceptions.InvalidTransitionError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised when a state-machine transition is not permitted.
relates_to:
- concept: class:parrot.knowledge.ontology.exceptions.OntologyError
  rel: extends
---

# InvalidTransitionError

Defined in [`parrot.knowledge.ontology.exceptions`](../summaries/mod:parrot.knowledge.ontology.exceptions.md).

```python
class InvalidTransitionError(OntologyError)
```

Raised when a state-machine transition is not permitted.

Args:
    message: Human-readable error description.
    current_state: The current state of the entity.
    requested_action: The action that was attempted.

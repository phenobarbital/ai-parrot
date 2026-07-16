---
type: Wiki Entity
title: EdgeDefinition
id: class:parrot.bots.flows.flow.definition.EdgeDefinition
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Definition of an edge (transition) between nodes.
---

# EdgeDefinition

Defined in [`parrot.bots.flows.flow.definition`](../summaries/mod:parrot.bots.flows.flow.definition.md).

```python
class EdgeDefinition(BaseModel)
```

Definition of an edge (transition) between nodes.

Conditions:
- always: Unconditional transition
- on_success: Only if source completed successfully
- on_error: Only if source failed
- on_timeout: Only if source timed out
- on_condition: Custom CEL predicate

## Methods

- `def validate_predicate(self) -> 'EdgeDefinition'` — on_condition edges require predicate.

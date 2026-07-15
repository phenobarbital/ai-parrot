---
type: Wiki Entity
title: ValidateAction
id: class:parrot.bots.flows.flow.actions.ValidateAction
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Validate the result against a JSON schema.
---

# ValidateAction

Defined in [`parrot.bots.flows.flow.actions`](../summaries/mod:parrot.bots.flows.flow.actions.md).

```python
class ValidateAction(BaseAction)
```

Validate the result against a JSON schema.

Behavior on validation failure depends on `on_failure`:
- "raise": Raise ValueError
- "skip": Log warning and continue
- "fallback": Replace result with fallback_value (not implemented here)

---
type: Wiki Entity
title: SelectionState
id: class:parrot.advisors.state.SelectionState
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Current state of product selection.
---

# SelectionState

Defined in [`parrot.advisors.state`](../summaries/mod:parrot.advisors.state.md).

```python
class SelectionState(BaseModel)
```

Current state of product selection.

This is what gets stored in Redis and snapshotted for Memento.

## Methods

- `def products_remaining(self) -> int`
- `def products_eliminated(self) -> int`
- `def should_recommend(self) -> bool` — Check if we should move to recommendation phase.

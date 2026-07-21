---
type: Wiki Entity
title: StateSnapshot
id: class:parrot.advisors.state.StateSnapshot
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Memento: Immutable snapshot of SelectionState.'
---

# StateSnapshot

Defined in [`parrot.advisors.state`](../summaries/mod:parrot.advisors.state.md).

```python
class StateSnapshot
```

Memento: Immutable snapshot of SelectionState.

Used for undo/redo functionality.

## Methods

- `def from_state(cls, state: SelectionState, action: str='', question: str=None, answer: str=None) -> 'StateSnapshot'` — Create snapshot from current state (deep copy).

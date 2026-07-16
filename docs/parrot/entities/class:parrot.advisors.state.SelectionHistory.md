---
type: Wiki Entity
title: SelectionHistory
id: class:parrot.advisors.state.SelectionHistory
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Memento Caretaker: Manages state history for undo/redo.'
---

# SelectionHistory

Defined in [`parrot.advisors.state`](../summaries/mod:parrot.advisors.state.md).

```python
class SelectionHistory(BaseModel)
```

Memento Caretaker: Manages state history for undo/redo.

Stored alongside SelectionState in Redis.

## Methods

- `def push(self, snapshot: StateSnapshot) -> None` — Add a new snapshot (discards any redo history).
- `def can_undo(self) -> bool` — Check if undo is possible.
- `def can_redo(self) -> bool` — Check if redo is possible.
- `def undo(self) -> Optional[StateSnapshot]` — Go back one step, return the previous state.
- `def redo(self) -> Optional[StateSnapshot]` — Go forward one step, return the next state.
- `def get_history_summary(self) -> List[Dict[str, Any]]` — Get human-readable history for display.

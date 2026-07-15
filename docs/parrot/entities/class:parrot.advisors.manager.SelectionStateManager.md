---
type: Wiki Entity
title: SelectionStateManager
id: class:parrot.advisors.manager.SelectionStateManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Manages selection state with Redis persistence and Memento pattern.
---

# SelectionStateManager

Defined in [`parrot.advisors.manager`](../summaries/mod:parrot.advisors.manager.md).

```python
class SelectionStateManager
```

Manages selection state with Redis persistence and Memento pattern.

Responsibilities:
- CRUD for SelectionState
- Memento history management (undo/redo)
- State transitions
- TTL management

## Methods

- `async def create_state(self, session_id: str, user_id: str, catalog_id: str, product_ids: List[str], metadata: Dict[str, Any]=None) -> SelectionState` — Create a new selection state.
- `async def get_state(self, session_id: str, user_id: str) -> Optional[SelectionState]` — Get current selection state.
- `async def apply_criteria(self, session_id: str, user_id: str, criteria_key: str, criteria_value: Any, question: str=None, answer: str=None, products_to_keep: List[str]=None) -> Tuple[SelectionState, int]` — Apply a criterion and filter products.
- `async def undo(self, session_id: str, user_id: str) -> Tuple[Optional[SelectionState], Optional[str]]` — Undo last action.
- `async def redo(self, session_id: str, user_id: str) -> Tuple[Optional[SelectionState], Optional[str]]` — Redo previously undone action.
- `async def get_history_summary(self, session_id: str, user_id: str) -> List[Dict[str, Any]]` — Get human-readable history for display.
- `async def can_undo(self, session_id: str, user_id: str) -> bool` — Check if undo is available.
- `async def can_redo(self, session_id: str, user_id: str) -> bool` — Check if redo is available.
- `async def delete_state(self, session_id: str, user_id: str) -> bool` — Delete selection state and history.
- `async def close(self)` — Close Redis connection.

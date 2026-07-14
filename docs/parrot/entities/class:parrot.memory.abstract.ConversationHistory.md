---
type: Wiki Entity
title: ConversationHistory
id: class:parrot.memory.abstract.ConversationHistory
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Manages conversation history for a session - replaces ConversationSession.
---

# ConversationHistory

Defined in [`parrot.memory.abstract`](../summaries/mod:parrot.memory.abstract.md).

```python
class ConversationHistory
```

Manages conversation history for a session - replaces ConversationSession.

## Methods

- `def add_turn(self, turn: ConversationTurn) -> None` — Add a new turn to the conversation history.
- `def get_recent_turns(self, count: int=5) -> List[ConversationTurn]` — Get the most recent turns for context.
- `def get_messages_for_api(self, model: str='claude') -> List[Dict[str, Any]]` — Convert turns to API message format for LLM Model.
- `def clear_turns(self) -> None` — Clear all turns from the conversation history.
- `def to_dict(self) -> Dict[str, Any]` — Serialize conversation history to dictionary.
- `def from_dict(cls, data: Dict[str, Any]) -> 'ConversationHistory'` — Deserialize conversation history from dictionary.

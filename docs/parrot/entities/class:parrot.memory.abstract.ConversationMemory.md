---
type: Wiki Entity
title: ConversationMemory
id: class:parrot.memory.abstract.ConversationMemory
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class for conversation memory storage.
---

# ConversationMemory

Defined in [`parrot.memory.abstract`](../summaries/mod:parrot.memory.abstract.md).

```python
class ConversationMemory(ABC)
```

Abstract base class for conversation memory storage.

## Methods

- `async def create_history(self, user_id: str, session_id: str, metadata: Optional[Dict[str, Any]]=None, chatbot_id: Optional[str]=None) -> ConversationHistory` — Create a new conversation history.
- `async def get_history(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> Optional[ConversationHistory]` — Get a conversation history.
- `async def update_history(self, history: ConversationHistory) -> None` — Update a conversation history.
- `async def add_turn(self, user_id: str, session_id: str, turn: ConversationTurn, chatbot_id: Optional[str]=None) -> None` — Add a turn to the conversation.
- `async def clear_history(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> None` — Clear a conversation history.
- `async def list_sessions(self, user_id: str, chatbot_id: Optional[str]=None) -> List[str]` — List all session IDs for a user.
- `async def delete_history(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> bool` — Delete a conversation history entirely.

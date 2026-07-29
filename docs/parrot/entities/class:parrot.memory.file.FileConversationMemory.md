---
type: Wiki Entity
title: FileConversationMemory
id: class:parrot.memory.file.FileConversationMemory
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: File-based implementation of conversation memory.
relates_to:
- concept: class:parrot.memory.abstract.ConversationMemory
  rel: extends
---

# FileConversationMemory

Defined in [`parrot.memory.file`](../summaries/mod:parrot.memory.file.md).

```python
class FileConversationMemory(ConversationMemory)
```

File-based implementation of conversation memory.

## Methods

- `async def create_history(self, user_id: str, session_id: str, metadata: Optional[Dict[str, Any]]=None, chatbot_id: Optional[str]=None) -> ConversationHistory` — Create a new conversation history.
- `async def get_history(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> Optional[ConversationHistory]` — Get a conversation history.
- `async def update_history(self, history: ConversationHistory) -> None` — Update a conversation history.
- `async def add_turn(self, user_id: str, session_id: str, turn: ConversationTurn, chatbot_id: Optional[str]=None) -> None` — Add a turn to the conversation.
- `async def clear_history(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> None` — Clear a conversation history.
- `async def list_sessions(self, user_id: str, chatbot_id: Optional[str]=None) -> List[str]` — List all session IDs for a user.
- `async def delete_history(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> bool` — Delete a conversation history entirely.

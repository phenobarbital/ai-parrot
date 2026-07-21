---
type: Wiki Entity
title: RedisConversation
id: class:parrot.memory.redis.RedisConversation
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Redis-based conversation memory with proper encoding handling.
relates_to:
- concept: class:parrot.memory.abstract.ConversationMemory
  rel: extends
---

# RedisConversation

Defined in [`parrot.memory.redis`](../summaries/mod:parrot.memory.redis.md).

```python
class RedisConversation(ConversationMemory)
```

Redis-based conversation memory with proper encoding handling.

## Methods

- `async def create_history(self, user_id: str, session_id: str, metadata: Optional[Dict[str, Any]]=None, chatbot_id: Optional[str]=None) -> ConversationHistory` — Create a new conversation history.
- `async def get_history(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> Optional[ConversationHistory]` — Get a conversation history.
- `async def update_history(self, history: ConversationHistory) -> None` — Update a conversation history.
- `async def add_turn(self, user_id: str, session_id: str, turn: ConversationTurn, chatbot_id: Optional[str]=None) -> None` — Add a turn to the conversation efficiently.
- `async def clear_history(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> None` — Clear a conversation history.
- `async def list_sessions(self, user_id: str, chatbot_id: Optional[str]=None) -> List[str]` — List all session IDs for a user.
- `async def delete_history(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> bool` — Delete a conversation history entirely.
- `async def close(self)` — Close the Redis connection.
- `async def ping(self) -> bool` — Test Redis connection.
- `async def get_raw_data(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> Optional[Dict]` — Get raw data from Redis for debugging.
- `async def debug_conversation(self, user_id: str, session_id: str, chatbot_id: Optional[str]=None) -> Dict[str, Any]` — Debug method to inspect conversation data.
- `async def list_sessions_by_chatbot(self, chatbot_id: str, user_id: Optional[str]=None) -> List[str]` — List all sessions for a specific chatbot.
- `async def get_chatbot_stats(self, chatbot_id: str) -> Dict[str, Any]` — Get statistics for a specific chatbot.
- `async def delete_all_chatbot_conversations(self, chatbot_id: str, user_id: Optional[str]=None) -> int` — Delete all conversations for a chatbot.
- `async def get_chatbot_users(self, chatbot_id: str) -> List[str]` — Get all users who have interacted with a chatbot.

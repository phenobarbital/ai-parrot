---
type: Wiki Entity
title: ChatStorage
id: class:parrot.storage.chat.ChatStorage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Unified chat persistence with Redis hot cache and DynamoDB cold storage.
---

# ChatStorage

Defined in [`parrot.storage.chat`](../summaries/mod:parrot.storage.chat.md).

```python
class ChatStorage
```

Unified chat persistence with Redis hot cache and DynamoDB cold storage.

## Methods

- `async def initialize(self) -> None` — Connect DynamoDB backend and set up Redis.
- `async def close(self) -> None` — Release connections.
- `async def save_turn(self, *, turn_id: Optional[str]=None, user_id: str, session_id: str, agent_id: str, user_message: str, assistant_response: str, output: Any=None, output_mode: Optional[str]=None, data: Any=None, code: Optional[str]=None, model: Optional[str]=None, provider: Optional[str]=None, response_time_ms: Optional[int]=None, tool_calls: Optional[List[Dict[str, Any]]]=None, sources: Optional[List[Dict[str, Any]]]=None, metadata: Optional[Dict[str, Any]]=None) -> str` — Save a complete user->assistant turn.
- `async def load_conversation(self, user_id: str, session_id: str, agent_id: Optional[str]=None, limit: int=DEFAULT_LIST_LIMIT) -> List[Dict[str, Any]]` — Load messages for a conversation, Redis-first with DynamoDB fallback.
- `async def get_conversation_metadata(self, session_id: str) -> Optional[Dict[str, Any]]` — Load conversation metadata.
- `async def list_user_conversations(self, user_id: str, agent_id: Optional[str]=None, limit: int=DEFAULT_LIST_LIMIT, since: Optional[datetime]=None) -> List[Dict[str, Any]]` — List conversations for a user from DynamoDB.
- `async def create_conversation(self, user_id: str, session_id: str, agent_id: str, title: str='New Conversation') -> Optional[Dict[str, Any]]` — Create a conversation thread in DynamoDB.
- `async def update_conversation_title(self, session_id: str, title: str, user_id: Optional[str]=None, agent_id: Optional[str]=None) -> bool` — Update the title of a conversation in DynamoDB.
- `async def delete_conversation(self, user_id: str, session_id: str, agent_id: Optional[str]=None) -> bool` — Delete a conversation from both Redis and DynamoDB.
- `async def delete_turn(self, session_id: str, turn_id: str, user_id: Optional[str]=None, agent_id: Optional[str]=None) -> bool` — Delete a single turn from DynamoDB.
- `async def get_context_for_agent(self, user_id: str, session_id: str, agent_id: Optional[str]=None, max_turns: int=DEFAULT_CONTEXT_TURNS, model: str='claude') -> List[Dict[str, str]]` — Return recent messages formatted for LLM context window.

---
type: Wiki Entity
title: ChatInteractionHandler
id: class:parrot.handlers.chat_interaction.ChatInteractionHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Manage persisted chat interactions.
---

# ChatInteractionHandler

Defined in [`parrot.handlers.chat_interaction`](../summaries/mod:parrot.handlers.chat_interaction.md).

```python
class ChatInteractionHandler(BaseView)
```

Manage persisted chat interactions.

GET    /api/v1/chat/interactions          — list conversations
GET    /api/v1/chat/interactions/{sid}     — load messages for a session
POST   /api/v1/chat/interactions          — create a conversation
PUT    /api/v1/chat/interactions/{sid}     — update conversation title
DELETE /api/v1/chat/interactions/{sid}     — delete a conversation

## Methods

- `async def get(self) -> web.Response` — List conversations or load a specific session's messages.
- `async def post(self) -> web.Response` — Create a new conversation.
- `async def put(self) -> web.Response` — Update the title of a conversation.
- `async def delete(self) -> web.Response` — Delete a conversation by session_id.
- `async def patch(self) -> web.Response` — Delete a specific turn from a conversation.

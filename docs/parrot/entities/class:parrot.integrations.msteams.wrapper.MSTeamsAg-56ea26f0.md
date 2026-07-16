---
type: Wiki Entity
title: MSTeamsAgentWrapper
id: class:parrot.integrations.msteams.wrapper.MSTeamsAgentWrapper
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wraps an Agent for MS Teams integration.
relates_to:
- concept: class:parrot.integrations.msteams.handler.MessageHandler
  rel: extends
---

# MSTeamsAgentWrapper

Defined in [`parrot.integrations.msteams.wrapper`](../summaries/mod:parrot.integrations.msteams.wrapper.md).

```python
class MSTeamsAgentWrapper(ActivityHandler, MessageHandler)
```

Wraps an Agent for MS Teams integration.

Features:
- Sends responses as Adaptive Cards with markdown support
- Handles images, documents, code blocks, and tables
- Supports rich formatting via ParsedResponse
- Automatic form detection when LLM calls request_form
- YAML-based form definitions
- Multi-step wizard dialogs
- Post-form tool execution

## Methods

- `async def handle_request(self, request: web.Request) -> web.Response` — Handle incoming webhook requests.
- `async def on_turn(self, turn_context: TurnContext)` — Handle the turn. Application logic.
- `async def on_message_activity(self, turn_context: TurnContext)` — Handle incoming messages including voice notes.
- `async def on_members_added_activity(self, members_added: list[ChannelAccount], turn_context: TurnContext)` — Welcome new members.
- `async def send_typing(self, turn_context: TurnContext)`
- `async def close_voice_transcriber(self) -> None` — Close voice transcriber and release resources.

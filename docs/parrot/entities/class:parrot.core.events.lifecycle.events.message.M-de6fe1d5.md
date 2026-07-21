---
type: Wiki Entity
title: MessageAddedEvent
id: class:parrot.core.events.lifecycle.events.message.MessageAddedEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted when a message is added to the conversation history.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# MessageAddedEvent

Defined in [`parrot.core.events.lifecycle.events.message`](../summaries/mod:parrot.core.events.lifecycle.events.message.md).

```python
class MessageAddedEvent(LifecycleEvent)
```

Emitted when a message is added to the conversation history.

Emitted from the canonical history-insertion point in AbstractBot
(save_conversation_turn / add_turn) so every code path is covered
by a single emission site.

Attributes:
    agent_name: Name of the agent whose history is updated.
    role: Message role (``"user"``, ``"assistant"``, ``"tool"``,
        ``"system"``).
    content_length: Character length of the message content.
    has_tool_calls: True if the message contains tool call blocks.

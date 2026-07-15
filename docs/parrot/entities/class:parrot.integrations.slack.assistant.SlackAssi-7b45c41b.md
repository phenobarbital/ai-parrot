---
type: Wiki Entity
title: SlackAssistantHandler
id: class:parrot.integrations.slack.assistant.SlackAssistantHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handles Slack's Agents & AI Apps events.
---

# SlackAssistantHandler

Defined in [`parrot.integrations.slack.assistant`](../summaries/mod:parrot.integrations.slack.assistant.md).

```python
class SlackAssistantHandler
```

Handles Slack's Agents & AI Apps events.

Provides a native AI assistant experience in Slack with:
- Split-view panel UI
- Suggested prompts
- Loading states with rotating messages
- Thread titles
- Chat streaming (when agent supports it)

Attributes:
    wrapper: The parent SlackAgentWrapper instance.
    config: Slack configuration from the wrapper.

Example::

    handler = SlackAssistantHandler(wrapper)
    await handler.handle_thread_started(event, payload)

## Methods

- `async def handle_thread_started(self, event: Dict[str, Any], payload: Dict[str, Any]) -> None` — Handle assistant_thread_started — user opens assistant container.
- `async def handle_context_changed(self, event: Dict[str, Any]) -> None` — Handle assistant_thread_context_changed — user switched channels.
- `async def handle_user_message(self, event: Dict[str, Any]) -> None` — Handle message.im in an assistant thread.
- `def get_thread_context(self, thread_ts: str) -> Optional[Dict[str, Any]]` — Get stored context for a thread.

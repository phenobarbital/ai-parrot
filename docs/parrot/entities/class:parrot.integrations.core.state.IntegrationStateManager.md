---
type: Wiki Entity
title: IntegrationStateManager
id: class:parrot.integrations.core.state.IntegrationStateManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Manages state for chat integrations (Telegram, MS Teams, Slack, Matrix).
---

# IntegrationStateManager

Defined in [`parrot.integrations.core.state`](../summaries/mod:parrot.integrations.core.state.md).

```python
class IntegrationStateManager
```

Manages state for chat integrations (Telegram, MS Teams, Slack, Matrix).

Tracks when a user in a specific chat context is waiting for a handoff response
(Human-in-the-Loop) rather than starting a new conversation turn.

## Methods

- `async def set_suspended_state(self, integration_id: str, chat_id: str, user_id: str, session_id: str, agent_name: str, execution_state: str='handoff_waiting') -> bool` — Mark a user/chat context as suspended, waiting for human input.
- `async def get_suspended_session(self, integration_id: str, chat_id: str, user_id: str) -> Optional[Dict[str, Any]]` — Check if there's a suspended session for this user/chat context.
- `async def clear_suspended_state(self, integration_id: str, chat_id: str, user_id: str) -> bool` — Clear the suspended state for a user context.

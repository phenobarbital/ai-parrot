---
type: Wiki Entity
title: MatrixCrewAgentWrapper
id: class:parrot.integrations.matrix.crew.crew_wrapper.MatrixCrewAgentWrapper
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Per-agent handler for incoming Matrix crew messages.
---

# MatrixCrewAgentWrapper

Defined in [`parrot.integrations.matrix.crew.crew_wrapper`](../summaries/mod:parrot.integrations.matrix.crew.crew_wrapper.md).

```python
class MatrixCrewAgentWrapper
```

Per-agent handler for incoming Matrix crew messages.

Processes messages directed at a specific agent:
1. Updates registry status to ``busy``.
2. Sends a typing indicator (background task, cancelled on completion).
3. Resolves the agent via ``BotManager.get_bot(chatbot_id)``.
4. Calls ``agent.ask(body)`` to get a response.
5. Sends the response as the agent's virtual MXID.
6. Updates registry status back to ``ready``.

Args:
    agent_name: Internal agent name (key in the crew config).
    config: ``MatrixCrewAgentEntry`` for this agent.
    appservice: Shared ``MatrixAppService`` managing virtual users.
    registry: Shared ``MatrixCrewRegistry``.
    coordinator: Shared ``MatrixCoordinator`` for status-board updates.
    server_name: Matrix server domain (e.g. ``"example.com"``).
    streaming: Whether to use edit-based streaming.
    max_message_length: Chunk responses longer than this.

## Methods

- `async def handle_message(self, room_id: str, sender: str, body: str, event_id: str) -> None` — Process an incoming message directed at this agent.

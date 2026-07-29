---
type: Wiki Entity
title: CrewAgentWrapper
id: class:parrot.integrations.telegram.crew.crew_wrapper.CrewAgentWrapper
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per-agent wrapper that handles @mention messages in a crew supergroup.
---

# CrewAgentWrapper

Defined in [`parrot.integrations.telegram.crew.crew_wrapper`](../summaries/mod:parrot.integrations.telegram.crew.crew_wrapper.md).

```python
class CrewAgentWrapper
```

Per-agent wrapper that handles @mention messages in a crew supergroup.

Responsibilities:
- Registers aiogram handlers for @mention and document messages.
- Routes incoming queries to the agent via ``agent.ask()``.
- Prefixes every response with the sender's @mention.
- Sends typing indicator while the agent processes.
- Notifies the :class:`CoordinatorBot` of busy/ready status transitions.
- Chunks long messages to stay under Telegram's 4096-char limit.
- Downloads documents via :class:`DataPayload` and passes them to the agent.

Args:
    bot: The aiogram ``Bot`` instance for this agent.
    agent: An AI-Parrot agent (``AbstractBot`` subclass).
    card: The ``AgentCard`` describing this agent.
    group_id: Telegram supergroup chat ID.
    coordinator: The ``CoordinatorBot`` managing the pinned registry.
    config: Optional dict with extra configuration overrides.
    payload: Optional :class:`DataPayload` for file handling.

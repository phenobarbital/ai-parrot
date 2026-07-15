---
type: Wiki Summary
title: parrot.handlers.agents.abstract
id: mod:parrot.handlers.agents.abstract
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.handlers.agents.abstract
relates_to:
- concept: class:parrot.handlers.agents.abstract.AgentHandler
  rel: defines
- concept: class:parrot.handlers.agents.abstract.JobWSManager
  rel: defines
- concept: class:parrot.handlers.agents.abstract.RedisWriter
  rel: defines
- concept: func:parrot.handlers.agents.abstract.auth_by_attribute
  rel: defines
- concept: func:parrot.handlers.agents.abstract.auth_groups
  rel: defines
- concept: mod:parrot.bots.agent
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.handlers.agents.abstract`

## Classes

- **`RedisWriter`** — RedisWriter class.
- **`JobWSManager(WebSocketManager)`** — Extends the generic WebSocketManager with one helper that sends
- **`AgentHandler(BaseView)`** — Abstract class for chatbot/agent handlers.

## Functions

- `def auth_groups(allowed: Sequence[str]) -> Callable[[Callable[..., Awaitable]], Callable[..., Awaitable]]` — Ensure the request is authenticated *and* the user belongs
- `def auth_by_attribute(allowed: Sequence[str], attribute: str='job_code') -> Callable[[Callable[..., Awaitable]], Callable[..., Awaitable]]` — Ensure the request is authenticated *and* the user belongs

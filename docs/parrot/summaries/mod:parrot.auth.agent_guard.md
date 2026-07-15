---
type: Wiki Summary
title: parrot.auth.agent_guard
id: mod:parrot.auth.agent_guard
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Agent-level PBAC guard for bot resolution.
relates_to:
- concept: class:parrot.auth.agent_guard.AgentAccessDenied
  rel: defines
- concept: func:parrot.auth.agent_guard.enforce_agent_access
  rel: defines
- concept: func:parrot.auth.agent_guard.parse_bot_permissions
  rel: defines
- concept: mod:parrot.auth.models
  rel: references
---

# `parrot.auth.agent_guard`

Agent-level PBAC guard for bot resolution.

This module provides the building blocks for enforcing PBAC policies at the
bot-resolution entry points (``BotManager.get_bot`` and
``AgentRegistry.get_instance``).

Public API:
    - ``AgentAccessDenied``: Exception raised when a caller is denied resolution.
    - ``parse_bot_permissions``: Validate and parse the JSONB shape stored in
      ``navigator.ai_bots.permissions``.
    - ``enforce_agent_access``: Async helper that raises ``AgentAccessDenied``
      when the evaluator denies access.

## Classes

- **`AgentAccessDenied(PermissionError)`** — Raised by ``enforce_agent_access`` when PBAC denies bot resolution.

## Functions

- `def parse_bot_permissions(value: dict | list | None) -> list[PolicyRuleConfig]` — Validate and parse the JSONB shape stored in ``ai_bots.permissions``.
- `async def enforce_agent_access(evaluator: object | None, bot_name: str, request: Optional[web.Request]) -> None` — Raise ``AgentAccessDenied`` if the request's subject cannot resolve ``bot_name``.

---
type: Wiki Summary
title: parrot.observability.context
id: mod:parrot.observability.context
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agent-identity ContextVar for per-agent cost and usage metrics.
relates_to:
- concept: func:parrot.observability.context.agent_identity
  rel: defines
---

# `parrot.observability.context`

Agent-identity ContextVar for per-agent cost and usage metrics.

FEAT-228 TASK-1499. Provides a task-local carrier that the bot sets around
each public invocation and the LLM client reads when building its lifecycle
events. Because ``ContextVar`` values are copied into tasks spawned via
``asyncio.create_task``, any LLM client call made within the invocation
observes the correct agent name. Nested invocations push/pop their own
token, so an inner agent's calls are attributed to the inner agent and the
outer value is restored on exit.

Public surface:
  * ``current_agent_name`` — module-level ``ContextVar[Optional[str]]`` with
    default ``None``.
  * ``agent_identity(name)`` — context-manager helper that does a token-based
    ``set()`` / ``reset()`` so nested scopes restore the prior value.

Stdlib only — no third-party dependency.

## Functions

- `def agent_identity(name: Optional[str]) -> Iterator[None]` — Bind *name* as the active agent for the duration of the block.

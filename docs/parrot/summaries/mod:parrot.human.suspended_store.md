---
type: Wiki Summary
title: parrot.human.suspended_store
id: mod:parrot.human.suspended_store
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Suspended-execution store for the stateless Web HITL suspend/resume path.
relates_to:
- concept: class:parrot.human.suspended_store.SuspendedExecution
  rel: defines
- concept: class:parrot.human.suspended_store.SuspendedExecutionStore
  rel: defines
---

# `parrot.human.suspended_store`

Suspended-execution store for the stateless Web HITL suspend/resume path.

FEAT-204 / TASK-1380

When an agent tool raises :class:`~parrot.core.exceptions.HumanInteractionInterrupt`
in SUSPEND mode, the HTTP handler must serialise the in-flight tool-loop state
so a later ``hitl_response`` request can reload it and call ``agent.resume()``.

This module provides:

* :class:`SuspendedExecution` — Pydantic v2 model holding the tool-loop state
  blob (messages, tool_call_id, agent_name, session_id, user_id).
* :class:`SuspendedExecutionStore` — thin Redis-backed store that saves/loads
  blobs under ``hitl:suspended:{interaction_id}`` with a TTL aligned to the
  matching ``hitl:interaction:{id}`` key.

The ``delete`` method removes ONLY the suspended key — the interaction key is
left intact so that the escalation sweeper (future feature) can still observe
pending interactions via TTL expiry.

## Classes

- **`SuspendedExecution(BaseModel)`** — Tool-loop state blob for a suspended HITL interaction.
- **`SuspendedExecutionStore`** — Redis-backed store for :class:`SuspendedExecution` blobs.

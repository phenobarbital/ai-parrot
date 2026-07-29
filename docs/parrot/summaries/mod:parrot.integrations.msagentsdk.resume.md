---
type: Wiki Summary
title: parrot.integrations.msagentsdk.resume
id: mod:parrot.integrations.msagentsdk.resume
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: MSAgentSDK conversation-reference store and proactive-resume helper.
relates_to:
- concept: class:parrot.integrations.msagentsdk.resume.MsaConversationRefStore
  rel: defines
- concept: class:parrot.integrations.msagentsdk.resume.MsaConversationReference
  rel: defines
- concept: func:parrot.integrations.msagentsdk.resume.proactive_resume
  rel: defines
- concept: mod:parrot.auth.permission
  rel: references
- concept: mod:parrot.integrations.msagentsdk.agent
  rel: references
---

# `parrot.integrations.msagentsdk.resume`

MSAgentSDK conversation-reference store and proactive-resume helper.

FEAT-264 / TASK-1674

When a tool raises :class:`~parrot.auth.credentials.CredentialRequired` during
``ParrotM365Agent._handle_message``, the agent:

1. Saves a :class:`~parrot.human.suspended_store.SuspendedExecution` record
   (keyed by nonce = ``interaction_id``) so the original question can be
   replayed without user re-typing.
2. Saves a :class:`MsaConversationReference` record (also keyed by nonce and
   by ``user_id``) so the proactive-resume helper can route the reply back to
   the correct conversation.

On consent completion, two resume triggers call
:func:`proactive_resume`:

- **OAuth/OBO** — the Bot Framework Token Service sends a ``signin/verifyState``
  or ``signin/tokenExchange`` invoke. The agent looks up the conversation
  reference **by user_id** (since the invoke carries no nonce) and calls
  :func:`proactive_resume`.
- **Static key** — the OOB capture route (TASK-1677) calls
  :meth:`ParrotM365Agent.resume_by_nonce` passing the nonce extracted from
  the callback URL.

Proactive delivery uses the Microsoft 365 Agents SDK::

    await adapter.continue_conversation(agent_app_id, continuation_activity, callback)

Where ``continuation_activity.conversation.id`` and
``continuation_activity.service_url`` are required fields
(``_validate_continuation_activity`` check in the SDK).

The ``MsaConversationRefStore`` falls back to an in-memory dict when no Redis
client is supplied, which makes it usable in unit tests and local dev without
a Redis dependency.

## Classes

- **`MsaConversationReference(BaseModel)`** — Minimal conversation reference for MSAgentSDK proactive resume.
- **`MsaConversationRefStore`** — Async store for :class:`MsaConversationReference` records.

## Functions

- `async def proactive_resume(adapter: Any, agent_app_id: str, conv_ref: MsaConversationReference, parrot_agent: Any, question: str, session_id: str, user_id: str, broker: Optional[Any]=None, on_sent: Optional[Callable[[Any], Awaitable[None]]]=None) -> None` — Re-run the suspended ask() and proactively deliver the response.

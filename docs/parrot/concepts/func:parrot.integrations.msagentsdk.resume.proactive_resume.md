---
type: Concept
title: proactive_resume()
id: func:parrot.integrations.msagentsdk.resume.proactive_resume
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Re-run the suspended ask() and proactively deliver the response.
---

# proactive_resume

```python
async def proactive_resume(adapter: Any, agent_app_id: str, conv_ref: MsaConversationReference, parrot_agent: Any, question: str, session_id: str, user_id: str, broker: Optional[Any]=None, on_sent: Optional[Callable[[Any], Awaitable[None]]]=None) -> None
```

Re-run the suspended ask() and proactively deliver the response.

Confirmed proactive SDK API (FEAT-264 TASK-1674 — open question §8)::

    await adapter.continue_conversation(
        agent_app_id,          # str — Microsoft App ID
        continuation_activity, # Activity with .conversation.id + .service_url
        callback,              # async (TurnContext) -> None
    )

The ``continuation_activity`` must carry:
- ``continuation_activity.conversation.id`` — the original conversation
- ``continuation_activity.service_url`` — required by SDK validation

On credential failure during the re-run, a fallback error message is sent
rather than raising (no card loop).

Args:
    adapter: The ``CloudAdapter`` instance from ``MSAgentSDKWrapper``.
    agent_app_id: Microsoft App ID (``config.client_id``).
    conv_ref: Stored :class:`MsaConversationReference` with conversation
        context for the proactive send.
    parrot_agent: The ai-parrot bot to call ``ask()`` on.
    question: The original user question to replay (no re-typing required).
    session_id: Agent session identifier (forwarded to ``ask()``).
    user_id: Canonical user identity (forwarded to ``ask()``).
    broker: Optional :class:`~parrot.auth.broker.CredentialBroker` — passed
        as the broker seam kwargs to ``ask()`` so the re-run can resolve
        credentials.
    on_sent: Optional async callback invoked with the ``TurnContext`` after
        the reply is sent.  Used in tests to capture the context.

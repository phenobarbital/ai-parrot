---
type: Wiki Entity
title: ProactiveMessenger
id: class:parrot.integrations.msteams.proactive.ProactiveMessenger
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Orchestrates proactive 1:1 messaging via the Bot Framework.
---

# ProactiveMessenger

Defined in [`parrot.integrations.msteams.proactive`](../summaries/mod:parrot.integrations.msteams.proactive.md).

```python
class ProactiveMessenger
```

Orchestrates proactive 1:1 messaging via the Bot Framework.

Two paths:
- **Warm**: a ``ConversationReference`` exists in the cache →
  ``adapter.continue_conversation(ref, callback, app_id)``
- **Cold**: no cache entry → ``adapter.create_conversation(...)`` to
  bootstrap the 1:1 (requires org-wide bot install, OQ-COLD), then
  captures and caches the new reference.

On any failure the messenger raises :class:`ProactiveDeliveryError`;
the caller (``TeamsHumanChannel``) catches it and returns ``False``.

Args:
    adapter: A :class:`~.hitl_adapter.HitlCloudAdapter` instance.
    convref_store: The :class:`ConversationReferenceStore`.
    app_id: The HITL bot's Microsoft App ID.
    tenant_id: AAD tenant ID (for single-tenant create_conversation).

## Methods

- `async def send(self, recipient: ResolvedTeamsUser, build_activity: Callable[[TurnContext], Awaitable[Optional[str]]]) -> str` — Send a proactive message in the recipient's 1:1 thread.
- `async def capture_reference(self, activity: Activity, email: str) -> None` — Capture and cache a ``ConversationReference`` from an inbound activity.

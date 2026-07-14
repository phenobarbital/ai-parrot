---
type: Wiki Entity
title: MsaConversationReference
id: class:parrot.integrations.msagentsdk.resume.MsaConversationReference
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Minimal conversation reference for MSAgentSDK proactive resume.
---

# MsaConversationReference

Defined in [`parrot.integrations.msagentsdk.resume`](../summaries/mod:parrot.integrations.msagentsdk.resume.md).

```python
class MsaConversationReference(BaseModel)
```

Minimal conversation reference for MSAgentSDK proactive resume.

Stored alongside the :class:`~parrot.human.suspended_store.SuspendedExecution`
record so the resume helper can open a proactive turn to the correct
conversation and channel.

Attributes:
    nonce: Unique per-suspended-interaction ID (``uuid4().hex``).
        Used as the ``interaction_id`` in the companion
        :class:`~parrot.human.suspended_store.SuspendedExecution` record.
    conversation_id: Bot Framework conversation ID (from
        ``activity.conversation.id``). Required by the SDK's
        ``continue_conversation`` call.
    service_url: Channel service URL (from ``activity.service_url``).
        Required by the SDK's ``continue_conversation`` call.
    user_id: Canonical user identity at the time of suspension.
    channel_id: Bot Framework channel identifier (default: ``"msteams"``).
    created_at: UTC timestamp of record creation.

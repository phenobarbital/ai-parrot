---
type: Wiki Summary
title: parrot.integrations.msteams.proactive
id: mod:parrot.integrations.msteams.proactive
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Proactive 1:1 bootstrap and Redis-backed conversation-reference cache.
relates_to:
- concept: class:parrot.integrations.msteams.proactive.ConversationReferenceStore
  rel: defines
- concept: class:parrot.integrations.msteams.proactive.ProactiveDeliveryError
  rel: defines
- concept: class:parrot.integrations.msteams.proactive.ProactiveMessenger
  rel: defines
- concept: class:parrot.integrations.msteams.proactive.SentActivityStore
  rel: defines
- concept: mod:parrot.integrations.msteams.graph
  rel: references
---

# `parrot.integrations.msteams.proactive`

Proactive 1:1 bootstrap and Redis-backed conversation-reference cache.

This module is the net-new core of the Teams HITL channel (spec §3 Module 3).
It implements two capabilities that do not exist anywhere else in the repo:

1. **ConversationReferenceStore** — Redis-backed cache for
   ``ConversationReference`` objects keyed by recipient email
   (``hitl:teams:convref:{email}``).  Long TTL (~30 days) refreshed on
   every inbound activity so frequently-contacted users never see a cold
   bootstrap again.

2. **SentActivityStore** — Redis map
   ``hitl:teams:sent:{interaction_id}`` that records
   ``{conversation_reference, activity_id, recipient}`` for every sent
   card.  Used by ``cancel_interaction`` (``update_activity``) and for
   cross-worker stateless delivery.

3. **ProactiveMessenger** — orchestrates the proactive 1:1:
   - *Warm path*: convref cached →
     ``adapter.continue_conversation(ref, callback, bot_app_id)``.
   - *Cold path*: no cache → ``adapter.create_conversation(...)`` to
     bootstrap the 1:1, capture the new ``ConversationReference``, post.
   Returns the posted ``activity_id`` (for the sent map) or raises
   ``ProactiveDeliveryError`` on failure.

OQ-2 resolution (botbuilder v4.17.1):
    ``CloudAdapter.continue_conversation(reference, callback, bot_app_id)``
    ``CloudAdapter.create_conversation(bot_app_id, callback,
        conversation_parameters, service_url=...)``
    ``ConversationParameters(is_group=False, bot=ChannelAccount(id=app_id),
        members=[ChannelAccount(id=aad_object_id)], tenant_id=tenant_id)``
    ``TurnContext.get_conversation_reference(activity)`` — static method.
    ``MicrosoftAppCredentials.trust_service_url(service_url)`` — before send.

Serialisation format: ``ConversationReference.serialize()`` → JSON string.
Deserialisation: ``ConversationReference.deserialize(json.loads(json_str))``.

## Classes

- **`ProactiveDeliveryError(Exception)`** — Raised when a proactive send fails fatally (cold-create + org-install).
- **`ConversationReferenceStore`** — Redis-backed store for Bot Framework ``ConversationReference`` objects.
- **`SentActivityStore`** — Redis-backed map of sent HITL activities.
- **`ProactiveMessenger`** — Orchestrates proactive 1:1 messaging via the Bot Framework.

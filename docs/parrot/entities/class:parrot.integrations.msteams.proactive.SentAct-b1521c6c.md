---
type: Wiki Entity
title: SentActivityStore
id: class:parrot.integrations.msteams.proactive.SentActivityStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Redis-backed map of sent HITL activities.
---

# SentActivityStore

Defined in [`parrot.integrations.msteams.proactive`](../summaries/mod:parrot.integrations.msteams.proactive.md).

```python
class SentActivityStore
```

Redis-backed map of sent HITL activities.

Keys: ``hitl:teams:sent:{interaction_id}`` → JSON dict with
``{conversation_reference, activity_id, recipient}``.

Used by ``cancel_interaction`` to call ``update_activity`` on the
exact card that was sent, and by cross-worker deployments to look up
sent cards without local state.

Args:
    redis: An async Redis client.
    ttl: Entry TTL in seconds (default: 7 days).

## Methods

- `async def set(self, interaction_id: str, conversation_reference: ConversationReference, activity_id: str, recipient: str) -> None` — Store the sent-activity metadata for an interaction.
- `async def get(self, interaction_id: str) -> Optional[Dict[str, Any]]` — Retrieve the sent-activity metadata for an interaction.
- `async def delete(self, interaction_id: str) -> None` — Delete a sent-activity entry (e.g. after successful cancel).

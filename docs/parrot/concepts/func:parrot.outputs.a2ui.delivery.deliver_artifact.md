---
type: Concept
title: deliver_artifact()
id: func:parrot.outputs.a2ui.delivery.deliver_artifact
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Deliver a ``RenderedArtifact`` via ``owner.send_notification`` (per-provider
  policy).
---

# deliver_artifact

```python
async def deliver_artifact(owner: Any, artifact: RenderedArtifact, *, recipients: Any, provider: Any=_EMAIL, message: str='', subject: Optional[str]=None, artifact_store: Any=None, user_id: Optional[str]=None, agent_id: Optional[str]=None, session_id: Optional[str]=None) -> dict[str, Any]
```

Deliver a ``RenderedArtifact`` via ``owner.send_notification`` (per-provider policy).

Args:
    owner: A ``NotificationMixin``-bearing object (e.g. ``BasicAgent``).
    artifact: The baked artifact to deliver.
    recipients: Recipient(s) in the provider's expected shape.
    provider: Delivery provider.
    message: Message text.
    subject: Optional subject (email).
    artifact_store: ``ArtifactStore`` for computing a Slack public URL.
    user_id / agent_id / session_id: Delivery context for ``get_public_url``.

Returns:
    The ``send_notification`` result dict.

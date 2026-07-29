---
type: Wiki Entity
title: WebhookBackend
id: class:parrot.human.actions.backends.webhook.WebhookBackend
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Posts an escalation payload to a configurable webhook endpoint.
relates_to:
- concept: class:parrot.human.actions.backends.base.ActionBackend
  rel: extends
---

# WebhookBackend

Defined in [`parrot.human.actions.backends.webhook`](../summaries/mod:parrot.human.actions.backends.webhook.md).

```python
class WebhookBackend(ActionBackend)
```

Posts an escalation payload to a configurable webhook endpoint.

The webhook is expected to return a JSON body containing a ``deep_link``
field pointing to the live-chat or external system session.

Args:
    default_url: Fallback URL when ``action_metadata`` does not provide one.
    timeout_seconds: HTTP request timeout (default 10s).

Payload POSTed to the webhook::

    {
        "interaction_id": "<uuid>",
        "question": "<question text>",
        "severity": "<low|normal|high|critical>",
        "user_id": "<source_agent or None>"
    }

Expected response::

    {"deep_link": "https://livechat.example.com/sessions/abc123"}

## Methods

- `async def execute(self, interaction: 'HumanInteraction', tier: 'EscalationTier') -> Dict[str, Any]` — POST escalation payload to the configured webhook.

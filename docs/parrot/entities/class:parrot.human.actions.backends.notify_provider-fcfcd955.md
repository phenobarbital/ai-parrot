---
type: Wiki Entity
title: NotifyBackend
id: class:parrot.human.actions.backends.notify_provider.NotifyBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Sends an escalation notification through any async-notify provider.
relates_to:
- concept: class:parrot.human.actions.backends.base.ActionBackend
  rel: extends
---

# NotifyBackend

Defined in [`parrot.human.actions.backends.notify_provider`](../summaries/mod:parrot.human.actions.backends.notify_provider.md).

```python
class NotifyBackend(ActionBackend)
```

Sends an escalation notification through any async-notify provider.

The provider is chosen at call time from ``action_metadata["provider"]``
(falling back to ``default_provider``), so a single backend instance can
deliver email, SES, SMS, Telegram, Teams, etc.

Args:
    default_provider: Provider used when the tier does not set one
        (default ``"email"`` — preserves legacy ``kind:"email"`` behaviour).
    default_from: Default ``From``/sender used by providers that support it.
    provider_options: Connection-level kwargs forwarded to the async-notify
        provider constructor (e.g. SMTP ``hostname``/``port``/``username``/
        ``password`` for email, ``bot_token`` for Telegram). Merged with —
        and overridden by — the per-tier ``action_metadata["provider_options"]``.

## Methods

- `def build_recipients(provider: str, addresses: List[str]) -> List[Any]` — Wrap raw address strings into async-notify recipient models.
- `async def execute(self, interaction: 'HumanInteraction', tier: 'EscalationTier') -> Dict[str, Any]` — Deliver the escalation notification via the configured provider.

---
type: Wiki Entity
title: NotifyAction
id: class:parrot.human.actions.notify.NotifyAction
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Dispatches one-way escalation notifications to a backend.
relates_to:
- concept: class:parrot.human.actions.base.EscalationAction
  rel: extends
---

# NotifyAction

Defined in [`parrot.human.actions.notify`](../summaries/mod:parrot.human.actions.notify.md).

```python
class NotifyAction(EscalationAction)
```

Dispatches one-way escalation notifications to a backend.

The backend is selected by ``tier.action_metadata["kind"]`` (or the legacy
``"channel"`` key).  Supported kinds:

- ``"notify"`` → :class:`~parrot.human.actions.backends.NotifyBackend`
  (async-notify; the delivery channel is the ``provider`` attribute —
  email / ses / sms / telegram / teams). **Recommended.**
- ``"email"`` → :class:`~parrot.human.actions.backends.EmailBackend`
  (async-notify email provider; kept for backwards compatibility).
- ``"webhook"`` → :class:`~parrot.human.actions.backends.WebhookBackend`

When a backend fails it raises :class:`ActionBackendError`, which is
re-raised so the manager can advance to the next tier.

Args:
    email_cfg: Keyword arguments forwarded to :class:`EmailBackend.__init__`
        (SMTP-flavoured options for the legacy ``"email"`` kind).
    webhook_cfg: Keyword arguments forwarded to :class:`WebhookBackend.__init__`.
    notify_cfg: Keyword arguments forwarded to :class:`NotifyBackend.__init__`
        (``default_provider``, ``default_from``, ``provider_options``) for
        the ``"notify"`` kind.

## Methods

- `async def execute(self, interaction, tier) -> Dict[str, Any]` — Dispatch to the appropriate notification backend.

---
type: Wiki Entity
title: EmailBackend
id: class:parrot.human.actions.backends.email.EmailBackend
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Send an escalation email via async-notify's email provider.
relates_to:
- concept: class:parrot.human.actions.backends.notify_provider.NotifyBackend
  rel: extends
---

# EmailBackend

Defined in [`parrot.human.actions.backends.email`](../summaries/mod:parrot.human.actions.backends.email.md).

```python
class EmailBackend(NotifyBackend)
```

Send an escalation email via async-notify's email provider.

Backwards-compatible wrapper over :class:`NotifyBackend` with
``default_provider="email"``. The SMTP-style arguments are mapped onto the
async-notify email provider's connection options.

Args:
    host: SMTP server hostname (mapped to async-notify ``hostname``).
    port: SMTP server port.
    username: SMTP auth username (optional).
    password: SMTP auth password (optional).
    default_from: Default ``From`` address.
    use_tls: STARTTLS after connect (port 587 style).
    use_ssl: Implicit TLS on connect (port 465 style). Currently ignored by
        async-notify's email provider (which uses STARTTLS). Included for
        future compatibility.

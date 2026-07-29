---
type: Wiki Summary
title: parrot.human.actions.backends.email
id: mod:parrot.human.actions.backends.email
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Email action backend — async-notify backed (back-compat shim).
relates_to:
- concept: class:parrot.human.actions.backends.email.EmailBackend
  rel: defines
- concept: mod:parrot.human.actions.backends.notify_provider
  rel: references
---

# `parrot.human.actions.backends.email`

Email action backend — async-notify backed (back-compat shim).

Historically this backend talked to ``aiosmtplib`` directly. It now delegates
to :class:`~parrot.human.actions.backends.notify_provider.NotifyBackend`, which
sends through **async-notify**, so the delivery channel is a configuration
attribute (``provider``) rather than hard-wired SMTP.

The constructor keeps its original SMTP-flavoured signature so existing
callers (e.g. ``NotifyAction(email_cfg=...)``) keep working: the SMTP kwargs
are translated into async-notify email provider options.

## Classes

- **`EmailBackend(NotifyBackend)`** — Send an escalation email via async-notify's email provider.

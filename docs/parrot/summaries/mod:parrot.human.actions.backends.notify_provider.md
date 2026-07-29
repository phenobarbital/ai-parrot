---
type: Wiki Summary
title: parrot.human.actions.backends.notify_provider
id: mod:parrot.human.actions.backends.notify_provider
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: async-notify-backed escalation notification backend.
relates_to:
- concept: class:parrot.human.actions.backends.notify_provider.NotifyBackend
  rel: defines
- concept: mod:parrot.human.actions.backends.base
  rel: references
- concept: mod:parrot.human.models
  rel: references
---

# `parrot.human.actions.backends.notify_provider`

async-notify-backed escalation notification backend.

This backend replaces the legacy ``aiosmtplib``-only :class:`EmailBackend`
with a provider-agnostic sender built on **async-notify**. The delivery
channel becomes a single ``provider`` attribute on the tier's
``action_metadata`` — switching email → SES → Twilio SMS → Telegram → Teams
is a configuration change, not new code.

Selected by :class:`~parrot.human.actions.notify.NotifyAction` for
``action_metadata["kind"] in {"notify", "email"}``.

``action_metadata`` consumed by this backend::

    {
        "kind": "notify",                # or legacy "email"
        "provider": "email",             # email | ses | telegram | teams | sms/twilio | slack
        "to": ["ops@example.com", "manager@example.com"],
        "cc": ["audit@example.com"],     # optional
        "cc_originator": true,            # append interaction.originator to CC
        "subject_template": "HITL Escalation: {question}",
        "body_template": "...{question}...",   # optional; a sensible default is built
        "provider_options": {"hostname": "smtp...", "port": 587},  # per-call creds
    }

## Classes

- **`NotifyBackend(ActionBackend)`** — Sends an escalation notification through any async-notify provider.
